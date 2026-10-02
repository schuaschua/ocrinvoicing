"""Staff alert emails (Story 5.2, AD-16, UX-DR23): who gets each alert kind and what
the email says. Pure: the refresh job reads the alert and the names, and sends what
this returns through `EmailPort`.

EXPERIENCE.md "Email entry points": a price rise goes to finance and procurement, a
watchlist listing to procurement and management. The email is a subject, a few plain
sentences and a deep link to the evidence. It never carries bank details, link
tokens, invoice images or invoice ids (AD-16): only the supplier's and the
material's names, the percentage and the rule, because the evidence is on the page.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any
from uuid import UUID

from invoicing.domain.analytics import (
    PRICE_RISE,
    RULE_LATE,
    RULE_PRICE_GAP,
    RULE_PRICE_RISES,
    WATCHLIST,
)
from invoicing.domain.roles import Role

# AD-16 / EXPERIENCE.md: the roles each alert kind is emailed to.
ALERT_RECIPIENT_ROLES: Mapping[str, tuple[Role, ...]] = {
    PRICE_RISE: (Role.FINANCE, Role.PROCUREMENT),
    WATCHLIST: (Role.PROCUREMENT, Role.MANAGEMENT),
}

# The staff app's own words for a name it doesn't have (web/staff strings).
UNKNOWN_SUPPLIER = "Unknown supplier"
UNKNOWN_MATERIAL = "Unknown material"


class InvalidAlertError(ValueError):
    """An alert whose stored detail can't make a correct email (an unknown kind or
    rule, a missing material or percentage): it is skipped, never sent."""


@dataclass(frozen=True)
class PendingAlert:
    """An `analytics.alert` not yet emailed, with the names its email needs: the
    supplier's from master and the materials' from `analytics.material` (None or
    missing when there is none)."""

    alert_id: UUID
    kind: str
    supplier_id: UUID
    supplier_name: str | None
    material_id: UUID | None
    detail: Mapping[str, Any]
    material_names: Mapping[UUID, str]


@dataclass(frozen=True)
class AlertEmail:
    """One alert's email: subject, plain text and HTML bodies."""

    subject: str
    text: str
    html: str


def alert_recipients(kind: str, by_role: Mapping[Role, Sequence[str]]) -> list[str]:
    """The union of the addresses of `kind`'s recipient roles, each once, in role
    order; empty for a kind with no recipients configured (or an unknown kind)."""
    found: list[str] = []
    for role in ALERT_RECIPIENT_ROLES.get(kind, ()):
        for address in by_role.get(role, ()):
            if address.lower() not in {a.lower() for a in found}:
                found.append(address)
    return found


def _plain(name: str | None, fallback: str) -> str:
    """One line of printable text: a name can't add a line or a header."""
    cleaned = " ".join(
        "".join(c if c.isprintable() else " " for c in name or "").split()
    )
    return cleaned or fallback


def _percent(value: Any) -> str:
    """A percentage as the page shows it: up to 2 decimals, no trailing zeros.
    `InvalidAlertError` when it is missing or not a finite number."""
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise InvalidAlertError("pct") from None
    if value is None or isinstance(value, bool) or not number.is_finite():
        raise InvalidAlertError("pct")
    text = f"{number.quantize(Decimal('0.01')):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _material(alert: PendingAlert, material_id: Any) -> str:
    try:
        key = UUID(str(material_id))
    except ValueError:
        return UNKNOWN_MATERIAL
    return _plain(alert.material_names.get(key), UNKNOWN_MATERIAL)


def watchlist_rule_words(alert: PendingAlert) -> str:
    """The words for a watchlist alert's AD-20 rule, as the Watchlist page puts them
    (Story 5.4). `InvalidAlertError` for an unknown rule or malformed evidence."""
    rule = alert.detail.get("rule")
    raw = alert.detail.get("evidence")
    if not isinstance(raw, list) or not all(isinstance(e, Mapping) for e in raw):
        raise InvalidAlertError("evidence")
    evidence: list[Mapping[str, Any]] = raw
    if rule == RULE_PRICE_RISES:
        count = len(evidence)
        return (
            f"{count} price {'rise' if count == 1 else 'rises'} in the last 12 months"
        )
    if rule == RULE_LATE:
        return "deliveries on average 7 or more days late"
    if rule == RULE_PRICE_GAP:
        if len(evidence) == 1:
            gap = evidence[0]
            return (
                f"{_material(alert, gap.get('material_id'))} "
                f"{_percent(gap.get('pct'))}% above the cheapest supplier"
            )
        return f"{len(evidence)} materials 5% or more above the cheapest supplier"
    raise InvalidAlertError("rule")


def _email(subject: str, sentence: str, link_words: str, link: str) -> AlertEmail:
    text = f"{sentence}\n\n{link_words}: {link}\n"
    html = (
        f"<p>{escape(sentence)}</p>"
        f'<p><a href="{escape(link, quote=True)}">{escape(link_words)}</a></p>'
    )
    return AlertEmail(subject=subject, text=text, html=html)


def alert_email(alert: PendingAlert, staff_app_base_url: str) -> AlertEmail:
    """UX-DR23: the email for one alert, with its deep link into the staff app at
    `staff_app_base_url` (Price comparison for the material, or the supplier's
    Watchlist entry). `InvalidAlertError` when the alert can't make a correct one."""
    base = staff_app_base_url.rstrip("/")
    supplier = _plain(alert.supplier_name, UNKNOWN_SUPPLIER)
    if alert.kind == PRICE_RISE:
        if alert.material_id is None:
            raise InvalidAlertError("material_id")
        material = _material(alert, alert.material_id)
        pct = _percent(alert.detail.get("pct"))
        return _email(
            subject=f"Price rise: {supplier}, {material} +{pct}%",
            sentence=(
                f"{supplier}'s latest unit price for {material} is {pct}% above "
                "their previous one."
            ),
            link_words="Compare the suppliers' prices",
            link=f"{base}/price-comparison?material_id={alert.material_id}",
        )
    if alert.kind != WATCHLIST:
        raise InvalidAlertError("kind")
    words = watchlist_rule_words(alert)
    return _email(
        subject=f"{supplier} added to the watchlist: {words}",
        sentence=f"{supplier} is on the watchlist: {words}.",
        link_words="See the evidence and the alternatives",
        # A query, not a #fragment: it survives the built-in auth sign-in redirect.
        link=f"{base}/watchlist?supplier={alert.supplier_id}",
    )
