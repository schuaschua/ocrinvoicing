"""staff-api settings."""

from invoicing.apps.common import AppSettings, HttpsUrl, StorageAccountName


class StaffApiSettings(AppSettings):
    """The environment's storage account and Key Vault (AD-11 private key)."""

    storage_account_name: StorageAccountName
    key_vault_uri: HttpsUrl
