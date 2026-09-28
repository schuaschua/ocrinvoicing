"""The PostgreSQL engine (AD-11, AD-12): Entra-only sign-in, so the password of every
new connection is a fresh access token for the app's user-assigned identity. TLS is
required; there is no database password anywhere (security.md rule 9)."""

from collections.abc import Callable
from typing import Any

from azure.identity import ManagedIdentityCredential
from sqlalchemy import URL, Engine, create_engine, event

# The Entra resource of Azure Database for PostgreSQL.
ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

type PasswordProvider = Callable[[], str]


def entra_token_provider(client_id: str) -> PasswordProvider:
    """Access tokens for the user-assigned identity `client_id`. The credential caches
    a token until shortly before it expires, so most connections reuse one."""
    credential = ManagedIdentityCredential(client_id=client_id)

    def token() -> str:
        return credential.get_token(ENTRA_SCOPE).token

    return token


def postgres_engine(
    *,
    host: str,
    database: str,
    user: str,
    password: PasswordProvider,
    port: int = 5432,
    sslmode: str = "require",
    pool_size: int = 2,
) -> Engine:
    """An engine for `database` as `user`. `password` is called for each new
    connection, so an expired token is never reused. Creating it opens no
    connection."""
    url = URL.create(
        "postgresql+psycopg",
        username=user,
        host=host,
        port=port,
        database=database,
        query={"sslmode": sslmode, "connect_timeout": "10"},
    )
    engine = create_engine(
        url,
        # pipeline runs one message at a time per function (AD-2); a small pool stays
        # well inside the B1ms connection limit.
        pool_size=pool_size,
        max_overflow=0,
        # A stopped server (AD-12) or a recycled connection is noticed before use.
        pool_pre_ping=True,
        # Well inside a token's lifetime; a new connection signs in again.
        pool_recycle=1800,
        # The URL is never logged with a password (there is none in it anyway).
        hide_parameters=True,
    )

    @event.listens_for(engine, "do_connect")
    def _sign_in(
        dialect: Any, connection_record: Any, cargs: Any, cparams: dict[str, Any]
    ) -> None:
        cparams["password"] = password()

    return engine
