"""staff-api settings."""

from invoicing.adapters.purchasing_factory import PurchasingAdapterName
from invoicing.apps.common import AppSettings, HttpsUrl, StorageAccountName


class StaffApiSettings(AppSettings):
    """The environment's storage account and Key Vault (AD-11 private key)."""

    storage_account_name: StorageAccountName
    key_vault_uri: HttpsUrl
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
