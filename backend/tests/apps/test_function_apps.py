"""Story 1.3: the four Function app entry points, matrix rows "Health" and "Missing
setting", and the host.json values AD-2 fixes. Story 1.4: the SPA route."""

import asyncio
import json
from collections.abc import Callable
from types import ModuleType
from uuid import UUID

import azure.functions as func
import pytest

import invoicing
from invoicing.adapters.http import CORRELATION_HEADER
from invoicing.apps.common import SettingsError


def _functions(module: ModuleType) -> dict[str, func.decorators.function_app.Function]:
    return {fn.get_function_name(): fn for fn in module.app.get_functions()}


def _route(fn: func.decorators.function_app.Function) -> dict[str, object]:
    (trigger,) = [
        b.get_dict_repr()
        for b in fn.get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    return trigger


@pytest.mark.parametrize("app", ["supplier_api"])
def test_story_1_3_health_returns_200_with_the_package_version(
    app: str, app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    module = load_app(app)
    health = _functions(module)["health"]
    trigger = _route(health)
    # host.json's empty routePrefix (Story 1.4): the route spells out api/, the URL is unchanged.
    assert trigger["route"] == "api/health"
    assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here
    assert getattr(trigger["authLevel"], "value", None) == "anonymous"

    request = func.HttpRequest(method="GET", url="/api/health", headers={}, body=b"")
    response = asyncio.run(health.get_user_function()(request))
    assert response.status_code == 200
    assert json.loads(response.get_body()) == {
        "status": "ok",
        "version": invoicing.__version__,
    }
    assert UUID(response.headers[CORRELATION_HEADER]).version == 7


@pytest.mark.app("pipeline")
def test_story_2_2_pipeline_has_a_poison_trigger_per_stage_queue_and_the_sweeper(
    app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    functions = _functions(load_app("pipeline"))
    poison = {
        name: fn.get_bindings()[0].get_dict_repr()
        for name, fn in functions.items()
        if name.endswith("_poison")
    }
    assert {name: b["queueName"] for name, b in poison.items()} == {
        "quality_poison": "q-quality-poison",
        "extract_poison": "q-extract-poison",
        "validate_poison": "q-validate-poison",
        "post_poison": "q-post-poison",
    }
    assert {b["type"] for b in poison.values()} == {"queueTrigger"}
    assert {b["connection"] for b in poison.values()} == {"AzureWebJobsStorage"}
    # Story 2.3: the extract stage consumes q-extract.
    (extract,) = [b.get_dict_repr() for b in functions["extract"].get_bindings()]
    assert (extract["type"], extract["queueName"]) == ("queueTrigger", "q-extract")
    assert extract["connection"] == "AzureWebJobsStorage"
    (timer,) = [b.get_dict_repr() for b in functions["sweeper"].get_bindings()]
    assert timer["type"] == "timerTrigger"
    # AD-2: every 15 minutes, NCRONTAB in UTC; no run on a cold start.
    assert timer["schedule"] == "0 */15 * * * *"
    assert timer["runOnStartup"] is False and timer["useMonitor"] is True


@pytest.mark.parametrize(
    ("app", "missing"), [("staff_api", "PGP_PRIVATE_KEY_VAULT_URI")]
)
def test_story_1_3_missing_setting_stops_the_app_naming_the_setting_not_its_value(
    app: str,
    missing: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(missing)
    with pytest.raises(SettingsError) as raised:
        load_app(app)
    text = str(raised.value)
    assert missing in text
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    for name, value in app_settings.items():
        assert value not in text, f"{name}'s value leaked into the error"


@pytest.mark.parametrize(
    ("app", "name", "value"),
    [
        ("staff_api", "KEY_VAULT_URI", "http://plain-http-vault.example"),
        # Story 2.1: a host that could smuggle in libpq options.
        ("pipeline", "POSTGRES_HOST", "db.example host=evil"),
    ],
)
def test_story_1_3_empty_or_malformed_setting_stops_the_app_naming_only_the_setting(
    app: str,
    name: str,
    value: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(SettingsError) as raised:
        load_app(app)
    text = str(raised.value)
    assert name in text
    assert value not in text
