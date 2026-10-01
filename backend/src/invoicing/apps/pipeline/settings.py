"""pipeline settings."""

import re
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from invoicing.adapters.purchasing_factory import PurchasingAdapterName
from invoicing.apps.common import (
    AccountsAudience,
    AppSettings,
    CurrencyCode,
    HostName,
    HttpsUrl,
    PgName,
    StorageAccountName,
)
from invoicing.domain.roles import Role

# Story 5.2: one email address, as ACS takes it (no display name, no comma).
_EMAIL = re.compile(r"^[^@\s,;<>\"]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
# A comma-separated list of addresses; empty means nobody.
Recipients = Annotated[tuple[str, ...], NoDecode]


def _blank_to_none(value: Any) -> Any:
    """Terraform sets the email settings to "" while the feature is off."""
    return None if isinstance(value, str) and not value.strip() else value


class PipelineSettings(AppSettings):
    """The environment's storage account (queues, blobs, tables), Key Vault, database
    (AD-11), Document Intelligence (AD-8) and the accounts system (AD-10). The database login is the pipeline
    identity, signing in with an Entra token: there is no password setting."""

    storage_account_name: StorageAccountName
    key_vault_uri: HttpsUrl
    postgres_host: HostName
    postgres_database: PgName
    postgres_user: PgName
    # AD-10: which purchasing adapter serves PO and goods-received data. The
    # simulation is the only one today; the real system replaces it by this setting.
    purchasing_adapter: PurchasingAdapterName = "sim"
    # Story 2.3 (AD-8): the shared Document Intelligence resource's custom-subdomain
    # endpoint (managed identity only, no key), this environment's monthly page cap
    # (Dev 100, Prod 400) and the invoice currency, which DI does not report for SGD.
    di_endpoint: HttpsUrl
    di_monthly_page_cap: int = Field(gt=0)
    invoice_currency: CurrencyCode = "SGD"
    # Story 3.2 (AD-10): the accounts system's base URL (this environment's
    # accounts-sim, `https://<host>/api`) and the audience its token is for
    # (`api://<accounts-sim client id>`). Switching to the real system changes only
    # these two settings.
    accounts_base_url: HttpsUrl
    accounts_audience: AccountsAudience
    # Story 5.2 (AD-16): staff alert emails, all optional. Without the ACS endpoint,
    # the sender address or the staff app's URL the feature is off and nothing is
    # sent. The recipients are comma-separated addresses per role, checked here at
    # start-up; their values are never logged (load_settings names settings only).
    email_acs_endpoint: HttpsUrl | None = None
    email_sender_address: str | None = None
    staff_app_base_url: HttpsUrl | None = None
    alert_recipients_finance: Recipients = ()
    alert_recipients_procurement: Recipients = ()
    alert_recipients_management: Recipients = ()

    @field_validator(
        "email_acs_endpoint",
        "email_sender_address",
        "staff_app_base_url",
        mode="before",
    )
    @classmethod
    def _optional(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("email_sender_address")
    @classmethod
    def _sender(cls, value: str | None) -> str | None:
        if value is not None and not _EMAIL.match(value):
            raise ValueError("not an email address")
        return value

    @field_validator(
        "alert_recipients_finance",
        "alert_recipients_procurement",
        "alert_recipients_management",
        mode="before",
    )
    @classmethod
    def _recipients(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        addresses = tuple(part.strip() for part in value.split(",") if part.strip())
        if not all(_EMAIL.match(address) for address in addresses):
            # Never echo the value: load_settings reports only the setting's name.
            raise ValueError("not a comma-separated list of email addresses")
        return addresses

    @property
    def email_enabled(self) -> bool:
        """Whether alert emails can go out: the endpoint, sender and link base set."""
        return bool(
            self.email_acs_endpoint
            and self.email_sender_address
            and self.staff_app_base_url
        )

    @property
    def alert_recipients(self) -> dict[Role, tuple[str, ...]]:
        """The configured addresses per recipient role (Story 5.2)."""
        return {
            Role.FINANCE: self.alert_recipients_finance,
            Role.PROCUREMENT: self.alert_recipients_procurement,
            Role.MANAGEMENT: self.alert_recipients_management,
        }
