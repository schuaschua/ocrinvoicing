"""supplier-api settings (AD-6: Table Storage, blob storage and q-quality only)."""

from invoicing.apps.common import AppSettings, StorageAccountName


class SupplierApiSettings(AppSettings):
    """The environment's storage account (tables, `images`, `q-quality`). The link
    registry's table name is fixed, not a setting: `SUPPLIER_LINKS_TABLE` in
    `ports/links.py`, shared with the load script (Story 1.6)."""

    storage_account_name: StorageAccountName
