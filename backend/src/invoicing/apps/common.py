"""What the four Function apps share: the settings base with its fail-fast loader, and
the health handler."""

from typing import Annotated, Literal
from uuid import UUID

import azure.functions as func
from pydantic import StringConstraints, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from invoicing import __version__
from invoicing.adapters.http import http_endpoint, json_response

# Setting types: an empty or malformed value fails at start-up like a missing one.
# A storage account name is 3-24 lowercase letters and digits (Azure's rule).
StorageAccountName = Annotated[
    str, StringConstraints(min_length=3, pattern=r"^[a-z0-9]{3,24}$")
]
# An https URL with a host, e.g. the Key Vault URI.
HttpsUrl = Annotated[
    str, StringConstraints(min_length=1, pattern=r"^https://[^\s/]+(/\S*)?$")
]


class SettingsError(RuntimeError):
    """A required app setting is missing or invalid. Names the settings, never values."""


class AppSettings(BaseSettings):
    """Settings every app has. Each app extends this with one class (coding-style.md
    rule 12); nothing else reads the environment."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore", case_sensitive=False)

    app_environment: Literal["dev", "prod", "local"]
    # Client id of the app's user-assigned identity (AD-1), for every Azure SDK call.
    azure_client_id: UUID


def load_settings[S: AppSettings](settings_class: type[S]) -> S:
    """Build `settings_class` from the environment, or fail fast naming the bad settings."""
    try:
        return settings_class()
    except ValidationError as error:
        names = sorted(
            {
                str(detail["loc"][0]).upper()
                for detail in error.errors()
                if detail["loc"]
            }
        )
        # `from None`: pydantic's error text echoes the input values, which may be secret.
        raise SettingsError(
            f"missing or invalid app settings: {', '.join(names)}"
        ) from None


async def _health(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
    return json_response(
        {"status": "ok", "version": __version__},
        status=200,
        correlation_id=correlation_id,
    )


# GET /api/health on supplier-api and staff-api: 200 with the app version.
health_endpoint = http_endpoint(_health)
