"""staff-api settings."""

from pydantic import Field

from invoicing.adapters.purchasing_factory import PurchasingAdapterName
from invoicing.apps.common import (
    CurrencyCode,
    HostName,
    HttpsUrl,
    PgName,
    PlatformAuthSettings,
    StorageAccountName,
)


class StaffApiSettings(PlatformAuthSettings):
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
    # Built-in auth (AD-14): WEBSITE_SITE_NAME and WEBSITE_AUTH_ENABLED come from
    # PlatformAuthSettings, and every staff route fails closed without it in Azure.
