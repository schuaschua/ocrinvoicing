"""accounts-sim settings."""

from uuid import UUID

from invoicing.apps.common import HostName, PgName, PlatformAuthSettings


class AccountsSimSettings(PlatformAuthSettings):
    """Its database login (AD-11: the identity's name, signing in with an Entra token,
    no password setting) and the one caller it serves (AD-10): this environment's
    `pipeline` identity, by principal (object) id. Built-in auth allows only that
    principal too; the app checks again, and fails closed in Azure when built-in auth
    is off (PlatformAuthSettings)."""

    postgres_host: HostName
    postgres_database: PgName
    postgres_user: PgName
    pipeline_principal_id: UUID
