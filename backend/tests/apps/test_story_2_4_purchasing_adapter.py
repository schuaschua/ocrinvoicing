"""Story 2.4, AD-10: `PURCHASING_ADAPTER` picks the purchasing adapter in one factory;
`sim` (the default) is the simulation, any other value stops the app naming the
setting."""

from collections.abc import Callable
from types import ModuleType

import pytest
from sqlalchemy import create_engine

from invoicing.adapters.purchasing_factory import PURCHASING_ADAPTERS, purchasing_port
from invoicing.adapters.purchasing_sim.adapter import PurchasingSimAdapter
from invoicing.apps.common import SettingsError

PURCHASING_APPS = ["pipeline", "staff_api"]


@pytest.mark.parametrize("app", PURCHASING_APPS)
@pytest.mark.parametrize("value", [None, "sim"])
def test_story_2_4_the_simulation_is_the_default_and_sim_selects_it(
    app: str,
    value: str | None,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if value is None:
        monkeypatch.delenv("PURCHASING_ADAPTER", raising=False)
    else:
        monkeypatch.setenv("PURCHASING_ADAPTER", value)
    module = load_app(app)
    assert module.settings.purchasing_adapter == "sim"
    if app == "pipeline":
        # The pipeline reads through its own engine (AD-11: SELECT only).
        assert isinstance(module.purchasing, PurchasingSimAdapter)


@pytest.mark.parametrize("app", PURCHASING_APPS)
# The setting is case-sensitive: "SIM" is not "sim".
@pytest.mark.parametrize("value", ["real", "", "postgres", "SIM"])
def test_story_2_4_any_other_adapter_stops_the_app_naming_the_setting(
    app: str,
    value: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PURCHASING_ADAPTER", value)
    with pytest.raises(SettingsError, match="PURCHASING_ADAPTER") as raised:
        load_app(app)
    assert raised.value.__cause__ is None


def test_story_2_4_the_factory_builds_the_simulation_and_refuses_others() -> None:
    assert PURCHASING_ADAPTERS == ("sim",)
    engine = create_engine("postgresql+psycopg://")
    try:
        assert isinstance(purchasing_port("sim", engine), PurchasingSimAdapter)
        with pytest.raises(ValueError, match="PURCHASING_ADAPTER must be one of: sim"):
            purchasing_port("real", engine)
    finally:
        engine.dispose()
