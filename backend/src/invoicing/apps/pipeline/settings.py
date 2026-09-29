"""pipeline settings."""

from typing import Annotated

from pydantic import Field, StringConstraints

from invoicing.adapters.purchasing_factory import PurchasingAdapterName
from invoicing.apps.common import AppSettings, HttpsUrl, StorageAccountName

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


class PipelineSettings(AppSettings):
    """The environment's storage account (queues, blobs, tables), Key Vault, database
    (AD-11) and Document Intelligence (AD-8). The database login is the pipeline
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
