"""staff-api settings."""

from pydantic import Field

from invoicing.adapters.purchasing_factory import PurchasingAdapterName
from invoicing.apps.common import (
    AppSettings,
    CurrencyCode,
    HostName,
    HttpsUrl,
    PgName,
    StorageAccountName,
)


class StaffApiSettings(AppSettings):
    """The environment's storage account, its Key Vault (pgp-public-key, hmac-key) and
    the private-key vault that holds pgp-private-key, which only staff-api may read
    (AD-11, OCR-129), and its database login (AD-11: the identity's name, signing in
    with an Entra token, no password setting)."""

    storage_account_name: StorageAccountName
    key_vault_uri: HttpsUrl
    pgp_private_key_vault_uri: HttpsUrl
    postgres_host: HostName
    postgres_database: PgName
    postgres_user: PgName
    # Story 2.8 (AD-8): the admin queue warns at 80 % of this environment's monthly DI
    # page cap (Dev 100, Prod 400); amounts are shown in the invoice currency.
    di_monthly_page_cap: int = Field(gt=0)
    invoice_currency: CurrencyCode = "SGD"
    # AD-10: which purchasing adapter serves PO and goods-received data. The
    # simulation is the only one today; the real system replaces it by this setting.
    purchasing_adapter: PurchasingAdapterName = "sim"
    # Set by App Service itself (Story 2.7): WEBSITE_SITE_NAME exists only in Azure, and
    # WEBSITE_AUTH_ENABLED is "True" when built-in auth is on. In Azure without it, the
    # principal header could be spoofed, so every staff route fails closed.
    website_site_name: str | None = None
    website_auth_enabled: str | None = None

    @property
    def platform_auth_trusted(self) -> bool:
        """True locally (no platform), or in Azure with built-in auth on."""
        if not self.website_site_name:
            return True
        return (self.website_auth_enabled or "").strip().lower() == "true"
