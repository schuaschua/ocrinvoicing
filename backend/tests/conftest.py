"""Shared fixtures. Tests never call Azure (coding-style.md rule 23)."""

import importlib
import sys
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest

# Values the Terraform app stack sets (infra/modules/env-app), all synthetic.
APP_SETTINGS = {
    "APP_ENVIRONMENT": "local",
    "AZURE_CLIENT_ID": "00000000-0000-0000-0000-00000000c1d0",
    "STORAGE_ACCOUNT_NAME": "babaloosealngst01",
    "KEY_VAULT_URI": "https://babaloo-sea-lng-kv-01.vault.azure.net/",
}


@pytest.fixture
def app_settings(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Every app setting present in the environment."""
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
