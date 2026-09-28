"""Shared fixtures. Tests never call Azure (coding-style.md rule 23)."""

import importlib
import sys
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Values the Terraform app stack sets (infra/modules/env-app), all synthetic.
APP_SETTINGS = {
    "APP_ENVIRONMENT": "local",
    "AZURE_CLIENT_ID": "00000000-0000-0000-0000-00000000c1d0",
    "STORAGE_ACCOUNT_NAME": "babaloosealngst01",
    "KEY_VAULT_URI": "https://babaloo-sea-lng-kv-01.vault.azure.net/",
}


TELEMETRY_SETTINGS = (
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "APPLICATIONINSIGHTS_AUTHENTICATION_STRING",
    "TELEMETRY_SAMPLING_RATIO",
)


@pytest.fixture
def app_settings(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Every app setting present in the environment, and no telemetry settings from the
    developer's shell (tests must never reach a real exporter)."""
    for name in TELEMETRY_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    for name, value in APP_SETTINGS.items():
        monkeypatch.setenv(name, value)
    return dict(APP_SETTINGS)


@pytest.fixture
def load_app() -> Iterator[Callable[[str], ModuleType]]:
    """Import `invoicing.apps.<app>.function_app` fresh, as the host does at start-up."""
    loaded: list[str] = []

    def _load(app: str) -> ModuleType:
        name = f"invoicing.apps.{app}.function_app"
        sys.modules.pop(name, None)
        loaded.append(name)
        return importlib.import_module(name)

    yield _load
    for name in loaded:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _telemetry_not_configured() -> Iterator[None]:
    """Each test starts, and ends, with telemetry not yet configured (Story 1.5)."""
    from invoicing.adapters import telemetry

    telemetry.reset_for_tests()
    yield
    telemetry.reset_for_tests()


_SPAN_EXPORTER: InMemorySpanExporter | None = None


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """Finished spans, from an in-memory exporter on the global tracer provider.

    The global provider can be set once per process, so the first use installs it
    (always sampling) and later uses only clear it."""
    global _SPAN_EXPORTER
    if _SPAN_EXPORTER is None:
        _SPAN_EXPORTER = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_SPAN_EXPORTER))
        trace.set_tracer_provider(provider)
    _SPAN_EXPORTER.clear()
    yield _SPAN_EXPORTER
    _SPAN_EXPORTER.clear()
