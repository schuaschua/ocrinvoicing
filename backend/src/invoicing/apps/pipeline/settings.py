"""pipeline settings."""

from invoicing.apps.common import AppSettings, HttpsUrl, StorageAccountName


class PipelineSettings(AppSettings):
    """The environment's storage account (queues, blobs, tables) and Key Vault (AD-11)."""

    storage_account_name: StorageAccountName
    key_vault_uri: HttpsUrl
