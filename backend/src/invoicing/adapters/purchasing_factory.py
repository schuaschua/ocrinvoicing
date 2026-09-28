"""The one place a `PurchasingPort` adapter is chosen (AD-10): by the
`PURCHASING_ADAPTER` setting, so switching to the real purchasing system changes that
setting only. Apps call `purchasing_port`; nothing else imports an adapter of the
port (import-linter contract in backend/pyproject.toml)."""

from typing import Literal, get_args

from sqlalchemy import Engine

from invoicing.adapters.purchasing_sim.adapter import PurchasingSimAdapter
from invoicing.ports.purchasing import PurchasingPort

# The values `PURCHASING_ADAPTER` may take; the app settings validate against it.
PurchasingAdapterName = Literal["sim"]
PURCHASING_ADAPTERS: tuple[str, ...] = get_args(PurchasingAdapterName)


def purchasing_port(name: str, engine: Engine) -> PurchasingPort:
    """The adapter `PURCHASING_ADAPTER` names. `engine` is the app's database engine,
    which the simulation reads through. ValueError, naming the setting, for any other
    value."""
    if name == "sim":
        return PurchasingSimAdapter(engine)
    raise ValueError(
        f"PURCHASING_ADAPTER must be one of: {', '.join(PURCHASING_ADAPTERS)}"
    )
