"""Story 5.2: staff alert emails (AD-16, CAP-14, CAP-15, UX-DR23). The analytics
refresh job runs as the pipeline login against a real PostgreSQL 18 (so the test also
proves its SELECT on master and its UPDATE of `emailed_at`), with purchasing the seeded
simulation; the email port is a fake behind the real throttle, so nothing reaches
Azure. The clock is injected, never waited on (coding-style.md rule 23). Synthetic
data only (security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
import logging
import re
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from apps._pipeline_fakes import FakeReminders
from apps.test_story_4_2_overdue import NAMES, SUPPLIER_BETA
from conftest import PostgresServer
from contracts.purchasing_contract import CEMENT, SUPPLIER_ALPHA
from invoicing.adapters.email import DEV_LIMITS, SendThrottle, ThrottledEmail
from invoicing.adapters.postgres.analytics import PostgresAnalyticsStore
from invoicing.adapters.postgres.schema import analytics_metadata
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.pipeline.alert_emails import AlertMailConfig
from invoicing.apps.pipeline.analytics_refresh import AnalyticsRefresh
from invoicing.domain.roles import Role
from invoicing.ports.email import EmailThrottledError

BASE_URL = "https://babaloo-sea-lng-func-02.azurewebsites.net"
CEMENT_NAME = "Portland cement, 50 kg bag"
FINANCE = ("siti@finance.example.test",)
# Siti is also listed under procurement, in another case: she gets one copy.
PROCUREMENT = ("SITI@finance.example.test", "weiling@procurement.example.test")
MANAGEMENT = ("goh@management.example.test",)
# A supplier whose master name tries to add a line and markup.
SUPPLIER_GAMMA = UUID("0192f0c1-7a2b-7c3d-8e4f-a1b2c3d4e5f6")
GAMMA_NAME = "Synthetic\nGamma <b>&</b> Sons"
GAMMA_LINE = "Synthetic Gamma <b>&</b> Sons"


class FakeEmail:
    """`EmailPort` that records each email; `failures` makes the next sends raise,
    `throttled` makes them raise ACS's 429 (as the adapter maps it)."""

    def __init__(self) -> None:
        self.sent: list[tuple[list[str], str, str, str]] = []
        self.attempts = 0
        self.failures = 0
        self.throttled = 0

    async def send(self, to: Sequence[str], subject: str, text: str, html: str) -> None:
        self.attempts += 1
        if self.throttled:
            self.throttled -= 1
            raise EmailThrottledError(retry_after=None)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("ACS said no")
        self.sent.append((list(to), subject, text, html))


@pytest.fixture
def owner(postgres_server: PostgresServer, purchasing_seeded: str) -> Iterator[Engine]:
    """The deployer, which owns the schemas: empties `analytics` and names the
    suppliers in master (Gamma only for this test)."""
    engine = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(analytics_metadata.tables)}"))
        for supplier_id, supplier_name in {
            **NAMES,
            SUPPLIER_GAMMA: GAMMA_NAME,
        }.items():
            connection.execute(
                text(
                    "INSERT INTO master.supplier (id, name) VALUES (:id, :name)"
                    " ON CONFLICT (id) DO UPDATE SET name = :name"
                ),
                {"id": supplier_id, "name": supplier_name},
            )
    yield engine
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM master.supplier WHERE id = :id"), {"id": SUPPLIER_GAMMA}
        )
    engine.dispose()


def _rise_detail(pct: str) -> dict[str, Any]:
    """A price rise's detail as Story 5.3 stores it, dated long before the watchlist's
    12 months so it lists nobody."""

    def point(day: int, price: str) -> dict[str, str]:
        return {
            "invoice_id": str(uuid4()),
            "invoice_date": date(2024, 1, day).isoformat(),
            "unit_price": price,
        }

    return {
        "supplier_id": str(SUPPLIER_ALPHA),
        "material_id": str(CEMENT),
        "pct": pct,
        "previous": point(2, "10.00"),
        "current": point(9, "10.63"),
    }


def test_story_5_2_dispatch(
    owner: Engine,
    purchasing_seeded: str,
    pipeline_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each pending alert is emailed once, to its kind's roles (each address once),
    with its deep link; already emailed, backfilled or stale never; invalid ones are
    skipped; only kinds with recipients are read; a failed send keeps its alert and
    gives back its throttle slot, three in a row stop the run; a full minute waits,
    the hour or ACS's 429 stops; a failed mark stops (at least once); off sends
    nothing; the content is one-line, escaped and holds no invoice ids, digit runs
    or tokens; the run's result never changes."""
    caplog.set_level(logging.INFO)
    now = [datetime(2026, 10, 5, 1, 30, tzinfo=UTC)]
    clock = lambda: now[0]  # the one clock every part reads
    store = PostgresAnalyticsStore(pipeline_engine)
    purchasing = purchasing_port("sim", pipeline_engine)
    fake = FakeEmail()
    throttle = SendThrottle(DEV_LIMITS, clock=clock)
    details: list[Any] = []
    sleeps: list[tuple[float, int]] = []

    async def sleep(seconds: float) -> None:
        # Waits for the throttle's next window by moving the clock.
        sleeps.append((seconds, len(fake.sent)))
        now[0] += timedelta(seconds=seconds)

    def add_alert(
        kind: str,
        supplier_id: UUID,
        material_id: UUID | None,
        detail: Any,
        emailed: bool = False,
        age: timedelta = timedelta(minutes=30),
    ) -> UUID:
        alert_id = uuid4()
        details.append(detail)
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analytics.alert (alert_id, kind, dedupe_key,"
                    " supplier_id, material_id, detail, created_at, emailed_at)"
                    " VALUES (:id, :kind, :key, :supplier, :material,"
                    " CAST(:detail AS jsonb), :created, :emailed)"
                ),
                {
                    "id": alert_id,
                    "kind": kind,
                    "key": f"{kind}:{alert_id}",
                    "supplier": supplier_id,
                    "material": material_id,
                    "detail": json.dumps(detail),
                    "created": now[0] - age + timedelta(seconds=len(details)),
                    "emailed": now[0] - timedelta(days=1) if emailed else None,
                },
            )
        return alert_id

    def emailed_at(alert_id: UUID) -> datetime | None:
        with owner.connect() as connection:
            return connection.execute(
                text("SELECT emailed_at FROM analytics.alert WHERE alert_id = :id"),
                {"id": alert_id},
            ).scalar_one()

    def run(
        mail: AlertMailConfig | None = None, on: PostgresAnalyticsStore = store
    ) -> str:
        caplog.clear()
        job = AnalyticsRefresh(
            purchasing,
            on,
            FakeReminders(),
            clock=clock,
            **({"alert_mail": mail} if mail else {}),
        )
        return asyncio.run(job.run())

    def config(**roles: Sequence[str]) -> AlertMailConfig:
        return AlertMailConfig(
            email=ThrottledEmail(fake, throttle),
            recipients={Role(name): list(value) for name, value in roles.items()},
            staff_app_base_url=BASE_URL,
            sleep=sleep,
        )

    def events(name: str) -> list[logging.LogRecord]:
        return [r for r in caplog.records if r.getMessage().startswith(f"{name} ")]

    def field(name: str, key: str) -> list[Any]:
        return [r.__dict__[key] for r in events(name)]

    everyone = config(finance=FINANCE, procurement=PROCUREMENT, management=MANAGEMENT)

    # A priced cement line, so the job names the material from purchasing (Story 5.3).
    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO analytics.price_point (invoice_id, line_no, supplier_id,"
                " material_id, invoice_date, unit_price, posted_at)"
                " VALUES (:invoice, 1, :supplier, :material, '2024-01-09', 10.63,"
                " '2024-01-09T02:00:00Z')"
            ),
            {"invoice": uuid4(), "supplier": SUPPLIER_ALPHA, "material": CEMENT},
        )
    rise = add_alert("price_rise", SUPPLIER_ALPHA, CEMENT, _rise_detail("6.25"))
    backfilled = add_alert(
        "price_rise",
        SUPPLIER_ALPHA,
        CEMENT,
        {**_rise_detail("3.10"), "backfilled": True},
        emailed=True,
    )
    # Belt and braces: marked backfilled but never stamped, still never sent.
    unstamped = add_alert(
        "price_rise",
        SUPPLIER_ALPHA,
        CEMENT,
        {**_rise_detail("3.20"), "backfilled": True},
    )
    listing = add_alert(
        "watchlist",
        SUPPLIER_BETA,
        None,
        {
            "supplier_id": str(SUPPLIER_BETA),
            "rule": "price_rises",
            "evidence": [_rise_detail("4.00") for _ in range(3)],
        },
    )

    # --- Disabled: no endpoint or sender, so `email.disabled` once and nothing sent.
    assert run() == "refreshed"
    assert len(events("email.disabled")) == 1
    assert fake.attempts == 0 and emailed_at(rise) is None

    # Added after the day's summaries ran (they read every price rise's detail).
    late = add_alert(
        "watchlist",
        SUPPLIER_GAMMA,
        None,
        {"supplier_id": str(SUPPLIER_GAMMA), "rule": "late", "evidence": []},
    )
    gap = add_alert(
        "watchlist",
        SUPPLIER_ALPHA,
        None,
        {
            "supplier_id": str(SUPPLIER_ALPHA),
            "rule": "price_gap",
            "evidence": [{"material_id": str(CEMENT), "pct": "7.50"}],
        },
    )
    invalid = [
        add_alert("price_rise", SUPPLIER_ALPHA, None, _rise_detail("5.00")),
        add_alert("price_rise", SUPPLIER_ALPHA, CEMENT, _rise_detail("NaN")),
        add_alert("watchlist", SUPPLIER_BETA, None, ["not", "an", "object"]),
        add_alert(
            "watchlist", SUPPLIER_BETA, None, {"rule": "unheard_of", "evidence": []}
        ),
        add_alert("watchlist", SUPPLIER_BETA, None, {"rule": "late", "evidence": "x"}),
    ]
    stale = add_alert(
        "price_rise",
        SUPPLIER_ALPHA,
        CEMENT,
        _rise_detail("9.00"),
        age=timedelta(days=15),
    )

    # --- Stale: created over 14 days ago, marked emailed without a send.
    # --- No recipients: watchlist has no procurement or management list, so its
    #     alerts aren't even read (no `email.invalid` for them); they wait.
    # --- Invalid: skipped with `email.invalid`, the rest go on.
    # --- Send: the price rise goes to finance (procurement unset), `emailed_at` set.
    now[0] += timedelta(minutes=1)
    assert run(config(finance=FINANCE)) == "already_ran"
    assert field("email.stale", "count") == [1] and emailed_at(stale) == now[0]
    assert field("email.no_recipients", "kind") == ["watchlist"]
    assert field("email.invalid", "alert_id") == [str(a) for a in invalid[:2]]
    assert all(emailed_at(a) is None for a in [listing, late, gap, unstamped, *invalid])
    assert emailed_at(rise) == now[0]
    ((to, subject, body, html),) = fake.sent
    assert to == list(FINANCE)
    assert subject == f"Price rise: {NAMES[SUPPLIER_ALPHA]}, {CEMENT_NAME} +6.25%"
    link = f"{BASE_URL}/price-comparison?material_id={CEMENT}"
    assert link in body and f'href="{link}"' in html

    # --- Send fails: `email.failed`, the alert stays, the run's result is unchanged;
    #     the others go on. Already emailed (incl. backfilled): never sent again.
    now[0] += timedelta(minutes=1)
    fake.failures = 1
    assert run(everyone) == "already_ran"
    assert field("email.failed", "code") == ["RuntimeError"]
    assert field("email.failed", "alert_id") == [str(listing)]
    assert emailed_at(listing) is None and emailed_at(late) == emailed_at(gap) == now[0]
    assert emailed_at(backfilled) == now[0] - timedelta(minutes=2, days=1)
    assert len(field("email.invalid", "alert_id")) == 5
    late_mail, gap_mail = fake.sent[1:]
    # Watchlist: procurement and management, each address once.
    assert late_mail[0] == [*PROCUREMENT, *MANAGEMENT]
    assert (
        late_mail[1]
        == f"{GAMMA_LINE} added to the watchlist: deliveries on average 7 or more days late"
    )
    assert "\n" not in late_mail[1] and "<b>" not in late_mail[3]
    assert "Synthetic Gamma &lt;b&gt;&amp;&lt;/b&gt; Sons" in late_mail[3]
    assert f"{BASE_URL}/watchlist?supplier={SUPPLIER_GAMMA}" in late_mail[2]
    assert gap_mail[1] == (
        f"{NAMES[SUPPLIER_ALPHA]} added to the watchlist: {CEMENT_NAME} 7.5% above the cheapest supplier"
    )

    # --- Retried next run: the watchlist entry, its link a query (kept through sign-in).
    now[0] += timedelta(minutes=1)
    run(everyone)
    to, subject, body, html = fake.sent[-1]
    assert to == [*PROCUREMENT, *MANAGEMENT]
    assert subject == (
        f"{NAMES[SUPPLIER_BETA]} added to the watchlist: 3 price rises in the last 12 months"
    )
    assert f"{BASE_URL}/watchlist?supplier={SUPPLIER_BETA}" in body
    assert emailed_at(listing) == now[0] and len(fake.sent) == 4

    # --- Three failures in a row stop the run, and give their throttle slots back.
    now[0] += timedelta(minutes=5)
    burst = [
        add_alert("price_rise", SUPPLIER_ALPHA, CEMENT, _rise_detail(f"{3 + n}.00"))
        for n in range(7)
    ]
    fake.failures, attempts = 3, fake.attempts
    run(everyone)
    assert fake.attempts == attempts + 3 and len(events("email.stopped")) == 1
    assert not any(emailed_at(a) for a in burst)

    # --- Throttled: Dev, 7 pending in one minute: 5 go (the failed sends took no
    #     slot), the run waits for the next window, and the other 2 go.
    run(everyone)
    assert len(fake.sent) == 11 and all(emailed_at(a) for a in burst)
    ((waited, sent_before),) = sleeps
    assert sent_before == 4 + 5 and 0 < waited <= 60
    # Price rise: finance and procurement (Siti once), never management.
    assert fake.sent[4][0] == [*FINANCE, PROCUREMENT[1]]
    assert fake.sent[4][1].endswith(f"{CEMENT_NAME} +3%")
    run(everyone)
    assert len(fake.sent) == 11  # each once

    # --- ACS's 429: the run stops; the alert goes next run.
    now[0] += timedelta(minutes=2)
    capped = add_alert("price_rise", SUPPLIER_ALPHA, CEMENT, _rise_detail("2.50"))
    fake.throttled = 1
    run(everyone)
    assert len(events("email.throttled")) == 1 and emailed_at(capped) is None
    run(everyone)
    assert emailed_at(capped) == now[0] and len(fake.sent) == 12

    # --- `emailed_at` not set after a send: `email.mark_failed`, the run stops, and
    #     the alert is sent again next run (at least once).
    class Unmarkable(PostgresAnalyticsStore):
        async def mark_emailed(self, alert_id: UUID, at: datetime) -> None:
            raise RuntimeError("database said no")

    now[0] += timedelta(minutes=2)
    twice = add_alert("price_rise", SUPPLIER_ALPHA, CEMENT, _rise_detail("2.75"))
    run(everyone, on=Unmarkable(pipeline_engine))
    assert field("email.mark_failed", "alert_id") == [str(twice)]
    assert emailed_at(twice) is None and len(fake.sent) == 13
    run(everyone)
    assert emailed_at(twice) == now[0] and fake.sent[-1][1] == fake.sent[-2][1]

    # --- Content: no invoice ids, bank-like digit runs or tokens, anywhere.
    ids = {str(SUPPLIER_ALPHA), str(SUPPLIER_BETA), str(SUPPLIER_GAMMA), str(CEMENT)}
    invoice_ids = {
        value
        for detail in details
        for value in re.findall(r"[0-9a-f-]{36}", json.dumps(detail))
        if value not in ids
    }
    assert invoice_ids
    for _to, subject, body, html in fake.sent:
        assert "\n" not in subject
        for part in (subject, body, html):
            assert not any(invoice_id in part for invoice_id in invoice_ids)
            assert not re.search(r"\d{6,}", part)
            assert "token" not in part.lower()
    assert emailed_at(unstamped) is None and all(emailed_at(a) is None for a in invalid)
    # Addresses never reach the logs.
    for address in (*FINANCE, *PROCUREMENT, *MANAGEMENT):
        assert address not in caplog.text

    # --- Failures reading alerts never fail the refresh run.
    class Broken(PostgresAnalyticsStore):
        async def pending_alerts(self, kinds: Any, limit: int) -> Any:
            raise RuntimeError("database said no")

    assert run(everyone, on=Broken(pipeline_engine)) == "already_ran"
    assert field("analytics_refresh.emails_failed", "code") == ["RuntimeError"]
