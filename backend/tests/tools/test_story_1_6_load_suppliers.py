"""Story 1.6: the supplier load script against PostgreSQL 18 (as Dj's login), with an
in-memory `supplierlinks` table behind the real table adapter and a throwaway PGP key
pair. Nothing reaches Azure (coding-style.md rule 23). Covers every row of the plan's
I/O matrix, and that no token, hash, bank value or phone number leaks."""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from sqlalchemy import Engine, create_engine, text

from _pgp import PgpKeyPair, make_test_key_pair
from conftest import PostgresServer
from invoicing.adapters.postgres.suppliers import BankKeys
from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.domain.links import token_hash
from invoicing.domain.suppliers import bank_fingerprint, normalise_bank_value
from invoicing.ports.links import SupplierLinkRegistry, partition_key
from invoicing.tools.load_suppliers import Dependencies, main

# The purchasing seed's supplier ids (backend/seed/sim_purchasing.json).
ALPHA = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f5526")
BETA = UUID("01a0c450-6fe8-7cb7-9e60-74d841e2024a")
GAMMA = UUID("01a0c450-73d0-7ee3-94ca-ef9fef9d793d")
HOST = "babaloo-sea-lng-func-01.azurewebsites.net"
HMAC_KEY = "synthetic-hmac-key-for-tests"
NOW = datetime(2026, 9, 29, 9, 30, tzinfo=UTC)
HEADER = [
    "supplier_id",
    "name",
    "phone",
    "tax_id",
    "bank_account_number",
    "iban",
    "swift",
]
# Synthetic only (security.md rule 1): made-up names, phones and bank values.
ROWS = [
    [str(ALPHA), "Synthetic Alpha Building Supplies", "+65 6000 0001", "T26LL0001A",
     "072-123456-7", "SG12 DBSS 0000 0012 3456 7", "DBSSSGSG"],
    [str(BETA), "Synthetic Beta Hardware Trading", "+65 6000 0002", "",
     "033-765432-1", "", "OCBCSGSG"],
    [str(GAMMA), "Synthetic Gamma Construction Materials", "", "T26LL0003C",
     "", "", ""],
]  # fmt: skip
SENSITIVE = [
    value for row in ROWS for value in row[2:3] + row[4:] if value
]  # phones and bank values
LINK_LINE = re.compile(
    rf"^link for (?P<id>[0-9a-f-]{{36}}) \(.+\): https://{re.escape(HOST)}/u#(?P<token>[A-Za-z0-9_-]{{43}})$"
)


class MemoryTable:
    """`supplierlinks` in memory, behind the real `TableSupplierLinkRegistry`."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.fail_writes = False

    async def create_entity(self, entity: Mapping[str, Any], **kwargs: Any) -> Any:
        if self.fail_writes:
            raise ServiceRequestError("connection reset")
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise ResourceExistsError("EntityAlreadyExists")
        self.rows[key] = dict(entity)
        return {}

    def query_entities(
        self, query_filter: str, *, parameters: dict[str, Any], **kwargs: Any
    ) -> AsyncIterator[Mapping[str, Any]]:
        return self._query(query_filter, parameters)

    async def _query(
        self, query_filter: str, parameters: dict[str, Any]
    ) -> AsyncIterator[Mapping[str, Any]]:
        if query_filter == "PartitionKey eq @pk and RowKey eq @rk":
            row = self.rows.get((parameters["pk"], parameters["rk"]))
            matches = [row] if row else []
        else:
            assert query_filter == "supplier_id eq @sid"
            matches = [
                r for r in self.rows.values() if r["supplier_id"] == parameters["sid"]
            ]
        for row in matches:
            yield dict(row)

    async def submit_transaction(self, operations: Any, **kwargs: Any) -> Any:
        if self.fail_writes:
            raise ServiceRequestError("connection reset")
        for kind, entity, _options in operations:
            assert kind == "update"
            key = (entity["PartitionKey"], entity["RowKey"])
            if key not in self.rows:
                raise ResourceNotFoundError("ResourceNotFound")
            self.rows[key].update(
                {k: v for k, v in entity.items() if k not in ("PartitionKey", "RowKey")}
            )
        return [{}]

    async def close(self) -> None:
        return None

    def of(self, supplier_id: UUID) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if r["supplier_id"] == str(supplier_id)]


@dataclass
class Harness:
    server: PostgresServer
    database: str
    keys: PgpKeyPair
    table: MemoryTable
    tmp_path: Path
    capsys: pytest.CaptureFixture[str]
    vault_reads: list[str] = field(default_factory=list)

    def reset(self) -> None:
        """Empty `master`, `audit` and `supplierlinks`: each case starts clean."""
        engine = self.engine()
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("TRUNCATE master.supplier_bank, master.supplier, audit.event")
                )
        finally:
            engine.dispose()
        self.table = MemoryTable()
        self.vault_reads.clear()

    def deps(self) -> Dependencies:
        async def close(registry: SupplierLinkRegistry) -> None:
            return None

        def read_keys(vault_uri: str) -> BankKeys:
            self.vault_reads.append(vault_uri)
            return BankKeys(public_key=self.keys.public_key, hmac_key=HMAC_KEY)

        return Dependencies(
            read_keys=read_keys,
            open_registry=lambda account: TableSupplierLinkRegistry(self.table),
            close_registry=close,
            now=lambda: NOW,
        )

    def csv(self, rows: list[list[str]], header: list[str] = HEADER) -> Path:
        path = self.tmp_path / "suppliers.csv"
        lines = [",".join(header)] + [",".join(f'"{c}"' for c in row) for row in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def run(self, *extra: str, csv: Path | None = None) -> tuple[int, str, str]:
        argv = ["--account", "babaloosealngst01", *extra]
        if csv is not None:
            argv += ["--file", str(csv), "--host", HOST]
            argv += ["--vault-uri", "https://babaloo-sea-lng-kv-01.vault.azure.net/"]
        elif "--replace-link" in extra:
            argv += ["--host", HOST]
        code = main(argv, deps=self.deps())
        out, err = self.capsys.readouterr()
        return code, out, err

    def engine(self, user: str | None = None) -> Engine:
        return create_engine(
            self.server.url(user or self.server.superuser, self.database)
        )

    def query(self, sql: str, **params: Any) -> list[Any]:
        engine = self.engine()
        try:
            with engine.connect() as connection:
                return [tuple(r) for r in connection.execute(text(sql), params)]
        finally:
            engine.dispose()

    def snapshot(self) -> list[Any]:
        return [
            self.query("SELECT * FROM master.supplier ORDER BY id"),
            self.query("SELECT * FROM master.supplier_bank ORDER BY 1, 2"),
            self.query("SELECT count(*) FROM audit.event"),
            json.dumps(sorted(self.table.rows.items()), default=str, sort_keys=True),
        ]

    def audit(self) -> list[tuple[str, str, str, Any]]:
        return self.query(
            "SELECT actor, action, entity_id, detail FROM audit.event ORDER BY id"
        )


@pytest.fixture(scope="module")
def key_pair() -> PgpKeyPair:
    return make_test_key_pair()


@pytest.fixture
def harness(
    postgres_server: PostgresServer,
    intake_database: str,
    key_pair: PgpKeyPair,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Harness]:
    """Empty `master` and `audit`, and the PG* variables of Dj's login."""
    for name, value in postgres_server.libpq_env(
        postgres_server.dj, intake_database
    ).items():
        monkeypatch.setenv(name, value)
    harness = Harness(
        postgres_server, intake_database, key_pair, MemoryTable(), tmp_path, capsys
    )
    harness.reset()
    yield harness


def _links(out: str) -> dict[UUID, str]:
    found: dict[UUID, str] = {}
    for line in out.splitlines():
        match = LINK_LINE.match(line)
        if match:
            found[UUID(match["id"])] = match["token"]
    return found


def _resolve(table: MemoryTable, token: str) -> Any:
    return asyncio.run(TableSupplierLinkRegistry(table).resolve(token_hash(token)))


# --- New supplier ----------------------------------------------------------------------


def _case_a_new_supplier_is_stored_encrypted_and_gets_one_printed_link(
    harness: Harness,
) -> None:
    code, out, err = harness.run(csv=harness.csv(ROWS))
    assert (code, err) == (0, "")
    assert "suppliers: 3 created, 0 updated, 0 unchanged; bank fields: 5 added" in out
    assert harness.query("SELECT id, name, tax_id, phone FROM master.supplier ORDER BY id") == [
        (ALPHA, ROWS[0][1], "T26LL0001A", "+65 6000 0001"),
        (BETA, ROWS[1][1], None, "+65 6000 0002"),
        (GAMMA, ROWS[2][1], "T26LL0003C", None),
    ]  # fmt: skip

    # One supplier_bank row per non-empty AD-18 field id, fingerprinted over the
    # normalised value and encrypted so that the private key reads it back.
    bank = harness.query(
        "SELECT supplier_id, field_id, fingerprint,"
        " pgp_pub_decrypt(ciphertext, dearmor(:private_key))"
        " FROM master.supplier_bank ORDER BY 1, 2",
        private_key=harness.keys.private_key,
    )
    # The normalised value is what is encrypted (AD-11: "normalised first").
    expected = sorted(
        (
            UUID(row[0]),
            field_id,
            bank_fingerprint(HMAC_KEY, value),
            normalise_bank_value(value),
        )
        for row in ROWS
        for field_id, value in zip(HEADER[4:], row[4:], strict=True)
        if value
    )
    assert bank == expected
    # The ciphertext is not the value.
    for (ciphertext,) in harness.query("SELECT ciphertext FROM master.supplier_bank"):
        assert not any(value.encode() in bytes(ciphertext) for value in SENSITIVE)

    # A link per supplier, printed once; only the hash is stored (AD-6).
    links = _links(out)
    assert set(links) == {ALPHA, BETA, GAMMA}
    assert out.count("https://") == 3
    for supplier_id, token in links.items():
        (row,) = harness.table.of(supplier_id)
        assert row["RowKey"] == token_hash(token)
        assert row["PartitionKey"] == partition_key(token_hash(token))
        assert row["issued_at"] == NOW and "revoked_at" not in row
        assert token not in json.dumps(row, default=str)
    assert harness.vault_reads == ["https://babaloo-sea-lng-kv-01.vault.azure.net/"]


def _case_a_printed_link_resolves_to_its_supplier_active(harness: Harness) -> None:
    """Acceptance criterion: Story 1.7's reader resolves the printed token."""
    _, out, _ = harness.run(csv=harness.csv(ROWS))
    for supplier_id, token in _links(out).items():
        link = _resolve(harness.table, token)
        assert link is not None and link.supplier_id == supplier_id and link.is_active
        assert link.supplier_name == next(
            r[1] for r in ROWS if r[0] == str(supplier_id)
        )


def _case_the_audit_names_field_ids_and_the_login_never_values(
    harness: Harness,
) -> None:
    harness.run(csv=harness.csv(ROWS))
    events = harness.audit()
    assert {actor for actor, *_ in events} == {harness.server.dj}
    created = [e for e in events if e[1] == "supplier.created"]
    assert sorted(e[2] for e in created) == sorted(str(s) for s in (ALPHA, BETA, GAMMA))
    added = sorted(
        (e[2], e[3]["field_id"]) for e in events if e[1] == "supplier_bank.added"
    )
    assert added == sorted(
        (row[0], field_id)
        for row in ROWS
        for field_id, value in zip(HEADER[4:], row[4:], strict=True)
        if value
    )
    # Every issue is audited by supplier id only, never the token or its hash.
    issued = [e for e in events if e[1] == "supplier_link.issued"]
    assert sorted(e[2] for e in issued) == sorted(str(s) for s in (ALPHA, BETA, GAMMA))
    assert all(e[3] == {} for e in issued)
    assert len(events) == 3 + 5 + 3


# --- Re-run, changes and blanks ------------------------------------------------------


def _case_a_re_run_with_the_same_csv_changes_nothing(harness: Harness) -> None:
    csv = harness.csv(ROWS)
    harness.run(csv=csv)
    before = harness.snapshot()
    # Saved by a spreadsheet with a byte-order mark: the same file, the same result.
    csv.write_bytes(b"\xef\xbb\xbf" + csv.read_bytes())
    code, out, err = harness.run(csv=csv)
    assert (code, err) == (0, "")
    assert "0 created, 0 updated, 3 unchanged; bank fields: 0 added, 0 changed" in out
    assert "links: none issued" in out and "https://" not in out
    # The same ciphertext bytes too: an unchanged value is never re-encrypted.
    assert harness.snapshot() == before


def _case_a_changed_bank_value_replaces_that_row_only(harness: Harness) -> None:
    harness.run(csv=harness.csv(ROWS))
    before = {
        (s, f): (c, fp)
        for s, f, c, fp in harness.query("SELECT * FROM master.supplier_bank")
    }
    events = len(harness.audit())
    changed = [list(row) for row in ROWS]
    changed[0][5] = "SG99 DBSS 0000 0099 9999 9"
    # A formatting-only change (spaces, hyphens, case) is not a change (AD-11).
    changed[0][4] = "0721234567"
    changed[0][6] = "dbss-sgsg"
    code, out, _ = harness.run(csv=harness.csv(changed))
    assert code == 0
    assert "0 created, 1 updated, 2 unchanged; bank fields: 0 added, 1 changed" in out
    after = {
        (s, f): (c, fp)
        for s, f, c, fp in harness.query("SELECT * FROM master.supplier_bank")
    }
    iban = (ALPHA, "iban")
    assert after[iban][1] == bank_fingerprint(HMAC_KEY, changed[0][5])
    assert bytes(after[iban][0]) != bytes(before[iban][0])
    assert {k: v for k, v in after.items() if k != iban} == {
        k: v for k, v in before.items() if k != iban
    }
    new_events = harness.audit()[events:]
    assert [(e[1], e[2], e[3]) for e in new_events] == [
        ("supplier_bank.changed", str(ALPHA), {"field_id": "iban"})
    ]
    assert "https://" not in out


def _case_a_blank_bank_field_leaves_the_stored_value(harness: Harness) -> None:
    harness.run(csv=harness.csv(ROWS))
    before = harness.snapshot()
    blank = [list(row) for row in ROWS]
    blank[0][6] = ""  # swift blank, one on file
    blank[1][4] = "  "
    code, out, _ = harness.run(csv=harness.csv(blank))
    assert code == 0 and "3 unchanged" in out
    assert harness.snapshot() == before


def _case_a_changed_phone_is_audited_by_column_name_only(harness: Harness) -> None:
    harness.run(csv=harness.csv(ROWS))
    changed = [list(row) for row in ROWS]
    changed[1][2] = "+65 6000 0099"
    changed[1][3] = "T26LL0002B"
    # A blank phone or tax id leaves the stored one (Dj, 2026-09-29).
    changed[0][2], changed[0][3] = "", " "
    code, out, _ = harness.run(csv=harness.csv(changed))
    assert code == 0 and "1 updated, 2 unchanged" in out
    (event,) = [e for e in harness.audit() if e[1] == "supplier.updated"]
    assert event[2:] == (str(BETA), {"fields": ["phone", "tax_id"]})
    assert harness.query(
        "SELECT id, phone, tax_id FROM master.supplier WHERE id IN (:a, :b) ORDER BY id",
        a=ALPHA,
        b=BETA,
    ) == [(ALPHA, "+65 6000 0001", "T26LL0001A"), (BETA, "+65 6000 0099", "T26LL0002B")]


# --- Replace and revoke -----------------------------------------------------------------


def _case_replace_link_revokes_the_old_one_and_prints_a_new_one(
    harness: Harness,
) -> None:
    _, out, _ = harness.run(csv=harness.csv(ROWS))
    old = _links(out)[ALPHA]
    code, out, err = harness.run("--replace-link", str(ALPHA))
    assert (code, err) == (0, "")
    new = _links(out)
    assert set(new) == {ALPHA} and new[ALPHA] != old
    assert out.count("https://") == 1
    old_link, new_link = (
        _resolve(harness.table, old),
        _resolve(harness.table, new[ALPHA]),
    )
    assert old_link is not None and not old_link.is_active
    assert old_link.revoked_at == NOW
    assert new_link is not None and new_link.is_active and new_link.supplier_id == ALPHA
    # Rows are never deleted: both links remain.
    assert len(harness.table.of(ALPHA)) == 2
    (event,) = [e for e in harness.audit() if e[1] == "supplier_link.replaced"]
    assert event == (
        harness.server.dj,
        "supplier_link.replaced",
        str(ALPHA),
        {"revoked": 1},
    )
    # Audited in order: the replace before the revoke, then the new link's issue.
    tail = [(e[1], e[2]) for e in harness.audit()][-2:]
    assert tail == [
        ("supplier_link.replaced", str(ALPHA)),
        ("supplier_link.issued", str(ALPHA)),
    ]


def _case_replace_link_with_file_for_a_supplier_without_an_active_link(
    harness: Harness,
) -> None:
    harness.run(csv=harness.csv(ROWS))
    harness.run("--revoke", str(GAMMA))
    # The target is skipped by the load's own issuing: exactly one link is printed.
    code, out, err = harness.run("--replace-link", str(GAMMA), csv=harness.csv(ROWS))
    assert (code, err) == (0, "")
    assert set(_links(out)) == {GAMMA} and out.count("https://") == 1
    active = [r for r in harness.table.of(GAMMA) if r.get("revoked_at") is None]
    assert len(active) == 1


def _case_replace_link_for_an_unknown_supplier_changes_nothing(
    harness: Harness,
) -> None:
    harness.run(csv=harness.csv(ROWS[:2]))
    before = harness.snapshot()
    # Even with a CSV that would add GAMMA: nothing is written when the target is unknown.
    unknown = "01a0c450-0000-7000-8000-00000000dead"
    code, out, err = harness.run("--replace-link", unknown, csv=harness.csv(ROWS))
    assert code == 2
    assert err == f"error: supplier {unknown} is not in master.supplier\n"
    assert "https://" not in out
    assert harness.snapshot() == before


def _case_revoke_revokes_and_a_later_load_issues_afresh(
    harness: Harness,
) -> None:
    csv = harness.csv(ROWS)
    _, out, _ = harness.run(csv=csv)
    token = _links(out)[BETA]
    code, out, err = harness.run("--revoke", str(BETA))
    assert (code, err) == (0, "")
    assert "https://" not in out
    link = _resolve(harness.table, token)
    # Story 1.7 shows "Link not working" for a revoked link.
    assert link is not None and not link.is_active
    (event,) = [e for e in harness.audit() if e[1] == "supplier_link.revoked"]
    assert event[2:] == (str(BETA), {"revoked": 1})
    issued = len([e for e in harness.audit() if e[1] == "supplier_link.issued"])
    # A later load issues the revoked supplier, still in the CSV, a fresh link
    # (Dj, 2026-09-29); the revoked one stays revoked.
    code, out, _ = harness.run(csv=csv)
    assert code == 0 and set(_links(out)) == {BETA}
    fresh = _resolve(harness.table, _links(out)[BETA])
    assert fresh is not None and fresh.is_active and fresh.supplier_id == BETA
    old = _resolve(harness.table, token)
    assert old is not None and not old.is_active
    assert len(harness.table.of(BETA)) == 2
    reissued = [e for e in harness.audit() if e[1] == "supplier_link.issued"]
    assert len(reissued) == issued + 1 and reissued[-1][2] == str(BETA)


def _case_revoke_without_an_active_link_is_refused(harness: Harness) -> None:
    harness.run(csv=harness.csv(ROWS))
    harness.run("--revoke", str(BETA))
    before = harness.snapshot()
    code, _, err = harness.run("--revoke", str(BETA))
    assert code == 2
    assert err == f"error: supplier {BETA} has no active link to revoke\n"
    assert harness.snapshot() == before


def test_story_1_6_a_failed_link_write_is_finished_by_the_next_run(
    harness: Harness,
) -> None:
    csv = harness.csv(ROWS)
    harness.table.fail_writes = True
    code, out, err = harness.run(csv=csv)
    assert code == 1
    assert err.count("\n") == 1 and "run the same command again" in err
    # A lost response may hide a stored link: the exact recovery is named.
    assert f"if that prints no link for {ALPHA}, run --replace-link {ALPHA}" in err
    assert "3 created" in out and "https://" not in out
    # The database was committed first; no supplier has a link yet.
    assert len(harness.query("SELECT id FROM master.supplier")) == 3
    assert harness.table.rows == {}
    harness.table.fail_writes = False
    code, out, _ = harness.run(csv=csv)
    assert code == 0 and set(_links(out)) == {ALPHA, BETA, GAMMA}


# --- Refused inputs -------------------------------------------------------------------


BAD_CSVS = [
    (HEADER[:-1], [r[:-1] for r in ROWS], "row 1, column swift: missing column"),
    (HEADER, [ROWS[0], ["nope", *ROWS[1][1:]]], "row 3, column supplier_id: not a UUID"),
    (HEADER + ["notes"], [[*r, ""] for r in ROWS], "row 1, column notes: unknown column"),
    (HEADER, [ROWS[0], ROWS[1], ROWS[0]], "row 4, column supplier_id: repeats an earlier row"),
    (HEADER, [[*ROWS[0][:4], "- -", *ROWS[0][5:]]], "row 2, column bank_account_number: only spaces and hyphens"),
    (HEADER, [[ROWS[0][0], " ", *ROWS[0][2:]]], "row 2, column name: blank"),
    (HEADER, [[ROWS[0][0], "Alpha\nPte", *ROWS[0][2:]]], "row 2, column name: holds a line break or control character"),
    (HEADER, [ROWS[0][:5]], "row 2: 5 cells, the header has 7"),
    ([*HEADER, "iban"], [[*ROWS[0], ""]], "row 1, column iban: repeated column"),
    (HEADER, [], "row 1: no supplier rows"),
]  # fmt: skip


def _case_bad_csv_writes_nothing_and_names_row_and_column(harness: Harness) -> None:
    for header, rows, message in BAD_CSVS:
        code, out, err = harness.run(csv=harness.csv(rows, header))
        assert code == 2
        assert err == f"error: the CSV is invalid: {message}\n"
        assert out == ""
        assert harness.snapshot() == [[], [], [(0,)], "[]"]
        assert harness.vault_reads == []


def _case_prod_is_refused_without_allow_prod(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = harness.server
    engine = create_engine(server.url(server.superuser, "postgres"))
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'invoicing_prod'")
        ).scalar()
    engine.dispose()
    if not exists:
        server.create_database("invoicing_prod")
    else:
        grant = create_engine(
            server.url(server.superuser, "invoicing_prod"), isolation_level="AUTOCOMMIT"
        )
        with grant.connect() as connection:
            connection.execute(
                text(f'GRANT CONNECT ON DATABASE invoicing_prod TO "{server.dj}"')
            )
        grant.dispose()
    result = server.alembic("invoicing_prod", "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    monkeypatch.setenv("PGDATABASE", "invoicing_prod")
    harness.database = "invoicing_prod"
    code, out, err = harness.run(csv=harness.csv(ROWS))
    assert code == 2
    assert err == "error: refusing invoicing_prod without --allow-prod\n"
    assert harness.query("SELECT count(*) FROM master.supplier") == [(0,)]
    assert harness.table.rows == {}
    code, out, _ = harness.run("--allow-prod", csv=harness.csv(ROWS))
    assert code == 0 and "3 created" in out


BAD_ARGUMENTS = [
    ([], "nothing to do"),
    (["--file", "x.csv", "--host", "https://" + HOST], "--host must be"),
    (["--file", "x.csv", "--host", HOST, "--vault-uri", "https://evil.example/"], "--vault-uri must be"),
    (["--revoke", str(ALPHA), "--account", "Not_An_Account"], "--account is not"),
]  # fmt: skip


def _case_bad_arguments_are_refused_before_any_call(harness: Harness) -> None:
    for argv, message in BAD_ARGUMENTS:
        if "--account" not in argv:
            argv = [*argv, "--account", "babaloosealngst01"]
        code = main(argv, deps=harness.deps())
        err = harness.capsys.readouterr().err
        assert code == 2 and message in err and err.count("\n") == 1


# --- Nothing sensitive leaks ----------------------------------------------------------


def test_story_1_6_logs_output_and_audit_hold_no_token_hash_bank_value_or_phone(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    csv = harness.csv(ROWS)
    changed = [list(row) for row in ROWS]
    changed[0][5], changed[1][2] = "SG55 DBSS 5555", "+65 6555 5555"
    with caplog.at_level(logging.DEBUG):
        outputs = [harness.run(csv=csv)]
        outputs.append(harness.run(csv=harness.csv(changed)))
        outputs.append(harness.run("--replace-link", str(ALPHA)))
        outputs.append(harness.run("--revoke", str(BETA)))
        harness.table.fail_writes = True
        outputs.append(harness.run("--replace-link", str(GAMMA)))
    tokens = [t for _, out, _ in outputs for t in _links(out).values()]
    assert len(tokens) == 4
    secrets = [
        *SENSITIVE, "SG55 DBSS 5555", "+65 6555 5555", "SG55DBSS5555",
        *tokens, *(token_hash(t) for t in tokens), HMAC_KEY,
        harness.keys.public_key.splitlines()[2],
    ]  # fmt: skip
    audit = json.dumps([e[3] for e in harness.audit()])
    logged = caplog.text + " ".join(str(vars(r)) for r in caplog.records)
    for _, out, err in outputs:
        # Stdout holds a token only on its own link line.
        rest = "\n".join(line for line in out.splitlines() if not LINK_LINE.match(line))
        for secret in secrets:
            assert secret not in rest and secret not in err
    for secret in secrets:
        assert secret not in logged
        assert secret not in audit


def test_story_1_6_new_suppliers_are_encrypted_fingerprinted_audited_and_linked(
    harness: Harness,
) -> None:
    """New supplier: encryption round-trip, one row per field id, audit, and printed links
    that Story 1.7's reader resolves as active (acceptance criterion)."""
    harness.reset()
    _case_a_new_supplier_is_stored_encrypted_and_gets_one_printed_link(harness)
    harness.reset()
    _case_a_printed_link_resolves_to_its_supplier_active(harness)
    harness.reset()
    _case_the_audit_names_field_ids_and_the_login_never_values(harness)


def test_story_1_6_a_re_run_changes_nothing_and_only_real_changes_are_written(
    harness: Harness,
) -> None:
    """Re-run, bank value changed, bank value blank, other fields changed."""
    harness.reset()
    _case_a_re_run_with_the_same_csv_changes_nothing(harness)
    harness.reset()
    _case_a_changed_bank_value_replaces_that_row_only(harness)
    harness.reset()
    _case_a_blank_bank_field_leaves_the_stored_value(harness)
    harness.reset()
    _case_a_changed_phone_is_audited_by_column_name_only(harness)


def test_story_1_6_replace_and_revoke_links(harness: Harness) -> None:
    """--replace-link and --revoke, including an unknown supplier and no active link."""
    harness.reset()
    _case_replace_link_revokes_the_old_one_and_prints_a_new_one(harness)
    harness.reset()
    _case_replace_link_for_an_unknown_supplier_changes_nothing(harness)
    harness.reset()
    _case_replace_link_with_file_for_a_supplier_without_an_active_link(harness)
    harness.reset()
    _case_revoke_revokes_and_a_later_load_issues_afresh(harness)
    harness.reset()
    _case_revoke_without_an_active_link_is_refused(harness)


def test_story_1_6_refused_inputs_change_nothing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bad CSV, bad arguments, and Prod without --allow-prod: exit 2, nothing written."""
    _case_bad_csv_writes_nothing_and_names_row_and_column(harness)
    _case_bad_arguments_are_refused_before_any_call(harness)
    _case_prod_is_refused_without_allow_prod(harness, monkeypatch)
