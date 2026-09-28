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
