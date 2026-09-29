"""What the four Function apps share: the settings base with its fail-fast loader,
telemetry start-up and the health handler."""

import re
from typing import Annotated, Literal
from uuid import UUID

import azure.functions as func
from pydantic import (
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from invoicing import __version__
from invoicing.adapters.http import http_endpoint, json_response
from invoicing.adapters.telemetry import TelemetryConfig, configure_telemetry

# Setting types: an empty or malformed value fails at start-up like a missing one.
# A storage account name is 3-24 lowercase letters and digits (Azure's rule).
StorageAccountName = Annotated[
    str, StringConstraints(min_length=3, pattern=r"^[a-z0-9]{3,24}$")
]
# An https URL with a host, e.g. the Key Vault URI.
HttpsUrl = Annotated[
    str, StringConstraints(min_length=1, pattern=r"^https://[^\s/]+(/\S*)?$")
]
# A host name, e.g. the shared server's `<name>.postgres.database.azure.com`.
HostName = Annotated[
    str, StringConstraints(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9.-]+$")
]
# A PostgreSQL identifier: the database, or the login (the identity's name, AD-11).
PgName = Annotated[
    str, StringConstraints(min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_.@-]+$")
]
# An ISO 4217 code, e.g. SGD.
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class SettingsError(RuntimeError):
    """A required app setting is missing or invalid. Names the settings, never values."""


_CLIENT_ID = re.compile(r"(?:^|;)\s*ClientId=([^;]*?)\s*(?:;|$)")


def authentication_client_id(text: str) -> UUID:
    """The ClientId in an APPLICATIONINSIGHTS_AUTHENTICATION_STRING; ValueError when it
    has none or it is not a UUID (the message never echoes the value)."""
    match = _CLIENT_ID.search(text)
    if not match:
        raise ValueError("no ClientId")
    try:
        return UUID(match.group(1))
    except ValueError:
        raise ValueError("ClientId is not a UUID") from None


class AppSettings(BaseSettings):
    """Settings every app has. Each app extends this with one class (coding-style.md
    rule 12); nothing else reads the environment."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore", case_sensitive=False)

    app_environment: Literal["dev", "prod", "local"]
    # Client id of the app's user-assigned identity (AD-1), for every Azure SDK call.
    azure_client_id: UUID

    # Telemetry (Story 1.5, AD-17). Set by infra/modules/env-app; without a connection
    # string (local runs) the app starts with telemetry off. Not a credential (local
    # auth is off), but kept out of logs and reprs.
    applicationinsights_connection_string: SecretStr | None = None
    # "ClientId=<identity>;Authorization=AAD": the identity that signs in to ingestion.
    applicationinsights_authentication_string: str | None = None
    # Fraction of traces kept; below 1 so sampling is always on (azure.md rule 16).
    # [ASSUMPTION] The default mirrors the environments' 50% until calibrated.
    telemetry_sampling_ratio: float = Field(default=0.5, gt=0, lt=1)

    @field_validator("applicationinsights_authentication_string")
    @classmethod
    def _has_client_id(cls, value: str | None) -> str | None:
        # A malformed value fails start-up (load_settings names it) instead of
        # silently falling back to another identity.
        if not value:
            return None
        authentication_client_id(value)
        return value


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


def telemetry_config(settings: AppSettings, service_name: str) -> TelemetryConfig:
    """The telemetry settings of one app. Ingestion uses the identity named in
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING, else the app's own identity."""
    auth = settings.applicationinsights_authentication_string
    client_id = authentication_client_id(auth) if auth else settings.azure_client_id
    secret = settings.applicationinsights_connection_string
    return TelemetryConfig(
        service_name=service_name,
        connection_string=(secret.get_secret_value() or None) if secret else None,
        client_id=client_id,
        sampling_ratio=settings.telemetry_sampling_ratio,
    )


def start_telemetry(settings: AppSettings, service_name: str) -> bool:
    """Configure telemetry once for this app (AD-17); returns whether it is on."""
    return configure_telemetry(telemetry_config(settings, service_name))


async def _health(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
    return json_response(
        {"status": "ok", "version": __version__},
        status=200,
        correlation_id=correlation_id,
    )


# GET /api/health on supplier-api and staff-api: 200 with the app version.
health_endpoint = http_endpoint(_health)
# supplier-api is anonymous, so its callers never choose the correlation (trace) id.
anonymous_health_endpoint = http_endpoint(_health, trust_caller_correlation_id=False)
