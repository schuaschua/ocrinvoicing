"""Story 1.3: the four Function app entry points, matrix rows "Health" and "Missing
setting", and the host.json values AD-2 fixes."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from uuid import UUID

import azure.functions as func
import pytest

import invoicing
from invoicing.adapters.http import CORRELATION_HEADER
from invoicing.apps.common import SettingsError

APPS_DIR = Path(invoicing.__file__).parent / "apps"
ALL_APPS = ["supplier_api", "staff_api", "pipeline", "accounts_sim"]
HTTP_APPS = ["supplier_api", "staff_api"]

# Settings each app needs; a missing one must stop it at start-up.
REQUIRED = {
    "supplier_api": ["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "STORAGE_ACCOUNT_NAME"],
    "staff_api": [
        "APP_ENVIRONMENT",
        "AZURE_CLIENT_ID",
        "STORAGE_ACCOUNT_NAME",
        "KEY_VAULT_URI",
    ],
    "pipeline": [
        "APP_ENVIRONMENT",
        "AZURE_CLIENT_ID",
        "STORAGE_ACCOUNT_NAME",
        "KEY_VAULT_URI",
    ],
    "accounts_sim": ["APP_ENVIRONMENT", "AZURE_CLIENT_ID"],
}


def _functions(module: ModuleType) -> dict[str, func.decorators.function_app.Function]:
    return {fn.get_function_name(): fn for fn in module.app.get_functions()}


def _route(fn: func.decorators.function_app.Function) -> dict[str, object]:
    (trigger,) = [
        b.get_dict_repr()
        for b in fn.get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    return trigger


@pytest.mark.parametrize("app", HTTP_APPS)
def test_story_1_3_health_returns_200_with_the_package_version(
    app: str, app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    module = load_app(app)
    health = _functions(module)["health"]
    trigger = _route(health)
    assert trigger["route"] == "health"
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


@pytest.mark.parametrize("app", ["pipeline", "accounts_sim"])
def test_story_1_3_non_http_apps_start_with_no_routes(
    app: str, app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    module = load_app(app)
    # AD-1: pipeline never has HTTP routes; accounts-sim's XML route comes later.
    assert _functions(module) == {}


@pytest.mark.parametrize(
    ("app", "missing"), [(app, name) for app in ALL_APPS for name in REQUIRED[app]]
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


def test_story_1_3_invalid_setting_is_named(
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "staging-secret-value")
    with pytest.raises(SettingsError, match="APP_ENVIRONMENT") as raised:
        load_app("supplier_api")
    assert "staging-secret-value" not in str(raised.value)


@pytest.mark.parametrize("app", ALL_APPS)
def test_story_1_3_settings_come_from_the_environment(
    app: str, app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    settings = load_app(app).settings
    assert settings.app_environment == "local"
    assert settings.azure_client_id == UUID(app_settings["AZURE_CLIENT_ID"])


BAD_VALUES = {
    "AZURE_CLIENT_ID": "not-a-client-id",
    "STORAGE_ACCOUNT_NAME": "Bad_Account-Name",
    "KEY_VAULT_URI": "http://plain-http-vault.example",
}


@pytest.mark.parametrize(
    ("app", "name"),
    [
        (app, name)
        for app in ALL_APPS
        for name in REQUIRED[app]
        if name != "APP_ENVIRONMENT"
    ],
)
@pytest.mark.parametrize("kind", ["empty", "bad"])
def test_story_1_3_empty_or_malformed_setting_stops_the_app_naming_only_the_setting(
    app: str,
    name: str,
    kind: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = "" if kind == "empty" else BAD_VALUES[name]
    monkeypatch.setenv(name, value)
    with pytest.raises(SettingsError) as raised:
        load_app(app)
    text = str(raised.value)
    assert name in text
    if value:
        assert value not in text


@pytest.mark.parametrize("app", ALL_APPS)
def test_story_1_3_every_app_has_a_v2_host_json_with_the_extension_bundle(
    app: str,
) -> None:
    host = json.loads((APPS_DIR / app / "host.json").read_text())
    assert host["version"] == "2.0"
    assert host["extensionBundle"] == {
        "id": "Microsoft.Azure.Functions.ExtensionBundle",
        "version": "[4.*, 5.0.0)",
    }


def test_story_1_3_pipeline_host_json_handles_one_plain_json_message_at_a_time() -> (
    None
):
    queues = json.loads((APPS_DIR / "pipeline" / "host.json").read_text())[
        "extensions"
    ]["queues"]
    # AD-2: one message at a time per stage, 5 tries before the poison queue, plain JSON.
    assert queues == {
        "batchSize": 1,
        "newBatchThreshold": 0,
        "maxDequeueCount": 5,
        "messageEncoding": "none",
    }
