"""Reads secrets from an environment's Key Vault (AD-11): the supplier load script
(Story 1.6) reads `pgp-public-key` and `hmac-key`, signed in as the operator, and the
pipeline's `extract` stage (Story 2.3) reads the same two once, as its identity.

Secret values are never logged, printed or put in an error. A failure is reported by
its code only: the SDK's exception text may carry the request URL.
"""

import asyncio
from collections.abc import Callable, Sequence

from azure.core.credentials import TokenCredential
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
from azure.keyvault.secrets import SecretClient

from invoicing.adapters.postgres.suppliers import BankKeys

PUBLIC_KEY_SECRET = "pgp-public-key"  # noqa: S105  # the secret's name, not a value
HMAC_KEY_SECRET = "hmac-key"  # noqa: S105  # the secret's name, not a value


class SecretReadError(Exception):
    """A secret could not be read. The message names the secret and a code only."""

    def __init__(self, name: str, code: str) -> None:
        super().__init__(f"can't read the Key Vault secret {name} ({code})")
        self.name = name
        self.code = code


def _code(error: AzureError) -> str:
    if isinstance(error, ClientAuthenticationError):
        return "AUTH_FAILED"
    if isinstance(error, ResourceNotFoundError):
        return "NOT_FOUND"
    if isinstance(error, HttpResponseError) and error.status_code == 403:
        return "FORBIDDEN"
    return type(error).__name__


def read_secrets(
    vault_uri: str, names: Sequence[str], credential: TokenCredential
) -> dict[str, str]:
    """The current value of each secret in `names`; `SecretReadError` for the first
    one that is missing, empty or unreadable."""
    client = SecretClient(vault_url=vault_uri, credential=credential)
    values: dict[str, str] = {}
    try:
        for name in names:
            try:
                value = client.get_secret(name).value
            except AzureError as error:
                raise SecretReadError(name, _code(error)) from None
            if not value:
                raise SecretReadError(name, "EMPTY")
            values[name] = value
    finally:
        client.close()
    return values


class BankKeysLoader:
    """The environment's `BankKeys`, read from Key Vault on first use and then kept
    for the life of the app (Story 2.3): only a run with a bank value needs them."""

    def __init__(
        self, vault_uri: str, credential: Callable[[], TokenCredential]
    ) -> None:
        self._vault_uri = vault_uri
        self._credential = credential
        self._keys: BankKeys | None = None
        self._lock = asyncio.Lock()

    async def __call__(self) -> BankKeys:
        async with self._lock:
            if self._keys is None:
                self._keys = await asyncio.to_thread(self._read)
        return self._keys

    def _read(self) -> BankKeys:
        values = read_secrets(
            self._vault_uri, (PUBLIC_KEY_SECRET, HMAC_KEY_SECRET), self._credential()
        )
        return BankKeys(
            public_key=values[PUBLIC_KEY_SECRET], hmac_key=values[HMAC_KEY_SECRET]
        )
