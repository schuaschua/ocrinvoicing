"""Reads secrets from an environment's Key Vault (AD-11): the supplier load script
(Story 1.6) reads `pgp-public-key` and `hmac-key`, signed in as the operator.

Secret values are never logged, printed or put in an error. A failure is reported by
its code only: the SDK's exception text may carry the request URL.
"""

from collections.abc import Sequence

from azure.core.credentials import TokenCredential
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
from azure.keyvault.secrets import SecretClient


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
