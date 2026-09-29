"""Story 1.6: the Key Vault secret reader (AD-11) with a fake `SecretClient`, and the
load script's exit when the keys can't be read. No Azure is called."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
from sqlalchemy import create_engine, text

from conftest import PostgresServer
from invoicing.adapters import key_vault
from invoicing.adapters.key_vault import SecretReadError, read_secrets
from invoicing.adapters.postgres.suppliers import BankKeys
from invoicing.ports.links import SupplierLinkRegistry
from invoicing.tools.load_suppliers import Dependencies, main

VAULT = "https://babaloo-sea-lng-kv-01.vault.azure.net/"
SDK_TEXT = f"Operation returned an invalid status for {VAULT}secrets/hmac-key"


class FakeSecretClient:
    """Answers each secret name from `answers`: a value, None, or an exception."""

    answers: ClassVar[dict[str, Any]] = {}
    closed = 0

    def __init__(self, vault_url: str, credential: Any) -> None:
        assert vault_url == VAULT

    def get_secret(self, name: str) -> Any:
        answer = self.answers[name]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(value=answer)

    def close(self) -> None:
        FakeSecretClient.closed += 1


def _forbidden() -> HttpResponseError:
    error = HttpResponseError(message=SDK_TEXT)
    error.status_code = 403
    return error


def test_story_1_6_key_vault_reads_report_codes_only_and_stop_the_load(
    monkeypatch: pytest.MonkeyPatch,
    postgres_server: PostgresServer,
    intake_database: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(key_vault, "SecretClient", FakeSecretClient)
    names = ("pgp-public-key", "hmac-key")

    FakeSecretClient.answers = {"pgp-public-key": "PUBLIC", "hmac-key": "HMAC"}
    assert read_secrets(VAULT, names, credential=None) == {  # type: ignore[arg-type]
        "pgp-public-key": "PUBLIC",
        "hmac-key": "HMAC",
    }
    for answer, code in (
        ("", "EMPTY"),
        (None, "EMPTY"),
        (ClientAuthenticationError(SDK_TEXT), "AUTH_FAILED"),
        (ResourceNotFoundError(SDK_TEXT), "NOT_FOUND"),
        (_forbidden(), "FORBIDDEN"),
    ):
        FakeSecretClient.answers = {"pgp-public-key": "PUBLIC", "hmac-key": answer}
        closed = FakeSecretClient.closed
        with pytest.raises(SecretReadError) as raised:
            read_secrets(VAULT, names, credential=None)  # type: ignore[arg-type]
        assert (raised.value.name, raised.value.code) == ("hmac-key", code)
        message = str(raised.value)
        assert message == f"can't read the Key Vault secret hmac-key ({code})"
        assert VAULT not in message and "invalid status" not in message
        assert raised.value.__cause__ is None
        assert FakeSecretClient.closed == closed + 1

    # The load script exits 1 with one line, and nothing is written.
    for name, value in postgres_server.libpq_env(
        postgres_server.dj, intake_database
    ).items():
        monkeypatch.setenv(name, value)
    csv = tmp_path / "suppliers.csv"
    csv.write_text(
        "supplier_id,name,phone,tax_id,bank_account_number,iban,swift\n"
        "01a0c450-6c00-7b7b-8aa9-4ccade9f5526,Synthetic Alpha,,,0721234567,,\n"
    )

    def read_keys(vault_uri: str) -> BankKeys:
        raise SecretReadError("hmac-key", "FORBIDDEN")

    async def close(registry: SupplierLinkRegistry) -> None:
        return None

    deps = Dependencies(
        read_keys=read_keys,
        open_registry=lambda account: None,  # type: ignore[arg-type,return-value]
        close_registry=close,
        now=lambda: datetime(2026, 9, 29, tzinfo=UTC),
    )
    engine = create_engine(
        postgres_server.url(postgres_server.superuser, intake_database)
    )

    def counts() -> list[int]:
        with engine.connect() as connection:
            return [
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608  # fixed names
                for table in ("master.supplier", "master.supplier_bank", "audit.event")
            ]

    before = counts()
    code = main(
        [
            "--account", "babaloosealngst01", "--file", str(csv),
            "--host", "babaloo-sea-lng-func-01.azurewebsites.net", "--vault-uri", VAULT,
        ],
        deps=deps,
    )  # fmt: skip
    out, err = capsys.readouterr()
    assert code == 1
    assert err == "error: can't read the Key Vault secret hmac-key (FORBIDDEN)\n"
    assert "https://" not in out
    assert counts() == before
    engine.dispose()
