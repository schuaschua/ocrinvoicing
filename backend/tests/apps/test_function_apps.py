"""Story 1.3: the four Function app entry points, matrix rows "Health" and "Missing
setting", and the host.json values AD-2 fixes. Story 1.4: the SPA route."""

import asyncio
import importlib.util
import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from uuid import UUID

import azure.functions as func
import pytest

import invoicing
from invoicing.adapters import telemetry
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
        "POSTGRES_HOST",
        "POSTGRES_DATABASE",
        "POSTGRES_USER",
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


def test_story_1_3_accounts_sim_starts_with_no_routes(
    app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    # accounts-sim's XML route comes later.
    assert _functions(load_app("accounts_sim")) == {}


@pytest.mark.app("pipeline")
def test_story_1_3_pipeline_never_has_http_routes(
    app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    # AD-1: queue and timer triggers only.
    for fn in _functions(load_app("pipeline")).values():
        types = {b.get_dict_repr()["type"] for b in fn.get_bindings()}
        assert "httpTrigger" not in types
        assert types <= {"queueTrigger", "timerTrigger"}


@pytest.mark.app("pipeline")
def test_story_2_1_pipeline_runs_the_quality_stage_on_q_quality(
    app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    module = load_app("pipeline")
    (trigger,) = [
        b.get_dict_repr() for b in _functions(module)["quality"].get_bindings()
    ]
    assert trigger["type"] == "queueTrigger"
    assert trigger["queueName"] == "q-quality"
    # The host storage connection: identity-based, the environment's account.
    assert trigger["connection"] == "AzureWebJobsStorage"
    # The thresholds come from the one shared file (AD-6).
    assert module.thresholds.min_variance > 0
    # The engine signs in as the configured login; creating it opened no connection.
    assert module.engine.url.username == app_settings["POSTGRES_USER"]
    assert module.engine.url.host == app_settings["POSTGRES_HOST"]
    assert module.engine.url.database == app_settings["POSTGRES_DATABASE"]
    assert module.engine.url.password is None
    assert module.engine.url.query["sslmode"] == "require"


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
    (timer,) = [b.get_dict_repr() for b in functions["sweeper"].get_bindings()]
    assert timer["type"] == "timerTrigger"
    # AD-2: every 15 minutes, NCRONTAB in UTC; no run on a cold start.
    assert timer["schedule"] == "0 */15 * * * *"
    assert timer["runOnStartup"] is False and timer["useMonitor"] is True


@pytest.mark.app("pipeline")
def test_story_2_2_every_pipeline_trigger_waits_out_a_stopped_database(
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from invoicing.domain.errors import DatabaseOfflineError
    from invoicing.ports.messages import QueueMessage

    module = load_app("pipeline")
    sent: list[tuple[str, int]] = []

    async def offline(*args: object, **kwargs: object) -> None:
        raise DatabaseOfflineError()

    async def send(queue: object, message: object, *, delay_seconds: int = 0) -> None:
        sent.append((str(queue), delay_seconds))

    monkeypatch.setattr(module.invoices, "status", offline)
    monkeypatch.setattr(module.invoices, "state", offline)
    monkeypatch.setattr(module.queue, "send", send)
    body = QueueMessage.first(
        UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab"),
        UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000c0"),
        datetime(2026, 9, 29, tzinfo=UTC),
    ).to_json()
    functions = _functions(module)
    for name in [
        "quality",
        "quality_poison",
        "extract_poison",
        "validate_poison",
        "post_poison",
    ]:
        message = func.QueueMessage(body=body.encode())
        asyncio.run(functions[name].get_user_function()(message))
    assert sent == [
        ("q-quality", 900),
        ("q-quality-poison", 900),
        ("q-extract-poison", 900),
        ("q-validate-poison", 900),
        ("q-post-poison", 900),
    ]

    # The host's dequeue count reaches the poison handler: on the last delivery a
    # failure is abandoned and acknowledged, never raised to `-poison-poison`.
    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(module.invoices, "state", broken)
    # The concrete message the host passes, which carries the dequeue count.
    from azure.functions.queue import QueueMessage as HostQueueMessage

    last = HostQueueMessage(body=body.encode(), dequeue_count=5)
    asyncio.run(functions["quality_poison"].get_user_function()(last))
    early = HostQueueMessage(body=body.encode(), dequeue_count=4)
    with pytest.raises(Exception, match="poison handling failed: RuntimeError"):
        asyncio.run(functions["quality_poison"].get_user_function()(early))
    # The timer exits with a code and catches up at its next run (AD-7).
    monkeypatch.setattr(module.invoices, "stale", offline)
    asyncio.run(functions["sweeper"].get_user_function()(object()))
    assert len(sent) == 5


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
    # Story 2.1: a host, database or login that could smuggle in libpq options.
    "POSTGRES_HOST": "db.example host=evil",
    "POSTGRES_DATABASE": "invoicing dev",
    "POSTGRES_USER": "pipeline password=x",
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


# --- Story 1.4: each API app serves its SPA from the same origin (AD-14) ------------------


@pytest.mark.parametrize("app", HTTP_APPS)
def test_story_1_4_http_apps_drop_the_route_prefix_so_the_spa_owns_the_root(
    app: str,
) -> None:
    host = json.loads((APPS_DIR / app / "host.json").read_text())
    assert host["extensions"]["http"]["routePrefix"] == ""


@pytest.mark.parametrize("app", HTTP_APPS)
def test_story_1_4_the_spa_catch_all_is_anonymous_get_and_registered_after_the_api(
    app: str, app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    module = load_app(app)
    registered = _functions(module)  # get_functions() may run only once per app
    functions = list(registered)
    assert functions[-1] == "web_app"
    trigger = _route(registered["web_app"])
    assert trigger["route"] == "{*path}"
    assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here
    assert getattr(trigger["authLevel"], "value", None) == "anonymous"
    # Every other route is an API route under api/.
    for name in functions[:-1]:
        assert str(_route(registered[name])["route"]).startswith("api/")


def _load_packaged(app: str, package: Path) -> ModuleType:
    """Import function_app.py from a package laid out as ci/code-deploy.sh builds it."""
    shutil.copy2(APPS_DIR / app / "function_app.py", package / "function_app.py")
    spec = importlib.util.spec_from_file_location(
        f"packaged_{app}", package / "function_app.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("app", HTTP_APPS)
def test_story_1_4_the_packaged_app_serves_static_index_html(
    app: str, app_settings: dict[str, str], tmp_path: Path
) -> None:
    (tmp_path / "static" / "assets").mkdir(parents=True)
    (tmp_path / "static" / "index.html").write_text('<html lang="en"></html>')
    (tmp_path / "static" / "assets" / "index-abc.js").write_text("export {};")
    module = _load_packaged(app, tmp_path)
    web_app = _functions(module)["web_app"].get_user_function()

    def get(path: str) -> func.HttpResponse:
        request = func.HttpRequest(
            method="GET",
            url=f"/{path}",
            headers={},
            body=b"",
            route_params={"path": path},
        )
        return asyncio.run(web_app(request))

    shell = get("")
    assert shell.status_code == 200
    assert shell.get_body() == b'<html lang="en"></html>'
    assert "default-src 'self'" in shell.headers["Content-Security-Policy"]
    assert (
        get("assets/index-abc.js").headers["Content-Type"].startswith("text/javascript")
    )
    assert get("api/nothing-here").status_code == 404


# --- Story 1.5: every app configures telemetry once, from its settings (AD-17) ----------

AUTH_CLIENT_ID = "00000000-0000-0000-0000-0000000a0000"
CONNECTION_STRING = (
    "InstrumentationKey=00000000-0000-0000-0000-00000000abcd;"
    "IngestionEndpoint=https://southeastasia-0.in.applicationinsights.azure.com/"
)
SERVICE_NAMES = {
    "supplier_api": "supplier-api",
    "staff_api": "staff-api",
    "pipeline": "pipeline",
    "accounts_sim": "accounts-sim",
}


@pytest.mark.parametrize("app", ALL_APPS)
def test_story_1_5_app_starts_with_telemetry_off_and_one_warning_when_unset(
    app: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="invoicing.telemetry"):
        module = load_app(app)
    assert module.settings.applicationinsights_connection_string is None
    (record,) = caplog.records
    assert record.getMessage().startswith("telemetry.disabled ")


@pytest.mark.parametrize("app", ALL_APPS)
def test_story_1_5_app_configures_azure_monitor_with_its_identity_and_sampling(
    app: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    credentials: list[str] = []
    monkeypatch.setattr(
        telemetry, "_azure_monitor", lambda: lambda **kw: calls.append(kw)
    )
    monkeypatch.setattr(telemetry, "_managed_identity", credentials.append)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", CONNECTION_STRING)
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_AUTHENTICATION_STRING",
        f"ClientId={AUTH_CLIENT_ID};Authorization=AAD",
    )
    monkeypatch.setenv("TELEMETRY_SAMPLING_RATIO", "0.25")

    module = load_app(app)
    assert CONNECTION_STRING not in repr(module.settings)
    (options,) = calls
    assert credentials == [AUTH_CLIENT_ID]
    assert options["connection_string"] == CONNECTION_STRING
    assert options["sampling_ratio"] == 0.25
    assert options["resource"].attributes["service.name"] == SERVICE_NAMES[app]  # type: ignore[attr-defined]  # a Resource


@pytest.mark.app("pipeline")
def test_story_1_5_without_an_authentication_string_the_app_identity_signs_in(
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials: list[str] = []
    monkeypatch.setattr(telemetry, "_azure_monitor", lambda: lambda **kw: None)
    monkeypatch.setattr(telemetry, "_managed_identity", credentials.append)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", CONNECTION_STRING)
    load_app("pipeline")
    assert credentials == [app_settings["AZURE_CLIENT_ID"]]


@pytest.mark.parametrize("ratio", ["0", "1", "1.5", "-0.1", "half"])
def test_story_1_5_sampling_off_or_malformed_stops_the_app(
    ratio: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEMETRY_SAMPLING_RATIO", ratio)
    with pytest.raises(SettingsError, match="TELEMETRY_SAMPLING_RATIO"):
        load_app("staff_api")


@pytest.mark.parametrize("app", ALL_APPS)
def test_story_1_5_the_host_exports_through_opentelemetry(app: str) -> None:
    host = json.loads((APPS_DIR / app / "host.json").read_text())
    # The host exports no telemetry of its own beside the app's (no duplicates, no
    # records that bypass the log allow-list).
    assert host["telemetryMode"] == "OpenTelemetry"


@pytest.mark.parametrize(
    ("app", "trusted"), [("supplier_api", False), ("staff_api", True)]
)
def test_story_1_5_only_signed_in_apps_honour_the_callers_correlation_id(
    app: str,
    trusted: bool,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    caller = "0192f0c1-7a2b-7c3d-8e4f-0123456789ab"
    module = load_app(app)
    registered = _functions(module)
    request = func.HttpRequest(
        method="GET", url="/api/health", headers={CORRELATION_HEADER: caller}, body=b""
    )
    response = asyncio.run(registered["health"].get_user_function()(request))
    assert (response.headers[CORRELATION_HEADER] == caller) is trusted
    spa_request = func.HttpRequest(
        method="GET",
        url="/nothing.js",
        headers={CORRELATION_HEADER: caller},
        body=b"",
        route_params={"path": "nothing.js"},
    )
    spa_response = asyncio.run(registered["web_app"].get_user_function()(spa_request))
    assert (spa_response.headers[CORRELATION_HEADER] == caller) is trusted


@pytest.mark.parametrize(
    "value",
    [
        "Authorization=AAD",
        "ClientId=not-a-client-id;Authorization=AAD",
        "ClientId=zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz;Authorization=AAD",
        "ClientId=;Authorization=AAD",
    ],
)
@pytest.mark.app("pipeline")
def test_story_1_5_a_malformed_authentication_string_stops_the_app_naming_it(
    value: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPLICATIONINSIGHTS_AUTHENTICATION_STRING", value)
    with pytest.raises(
        SettingsError, match="APPLICATIONINSIGHTS_AUTHENTICATION_STRING"
    ) as raised:
        load_app("pipeline")
    assert value not in str(raised.value)
