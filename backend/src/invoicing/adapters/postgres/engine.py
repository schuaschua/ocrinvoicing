"""The PostgreSQL engine (AD-11, AD-12): Entra-only sign-in, so the password of every
new connection is a fresh access token for the app's user-assigned identity. TLS is
required; there is no database password anywhere (security.md rule 9)."""

import logging
from collections.abc import Callable
from typing import Any

from azure.core.exceptions import AzureError
from azure.identity import ManagedIdentityCredential
from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from invoicing.adapters.logging import log_event
from invoicing.domain.errors import DatabaseOfflineError

# The Entra resource of Azure Database for PostgreSQL.
ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

type PasswordProvider = Callable[[], str]

_logger = logging.getLogger("invoicing.postgres")

# One connection per `pipeline` function that can run at once on its single instance
# (AD-2: quality, extract, validate, the four poison triggers and the sweeper; each
# later stage adds one). Dev and Prod together stay far inside the B1ms connection
# limit (AD-12).
POOL_SIZE = 8


class DatabaseBusyError(RuntimeError):
    """Every pooled connection is in use: the database is up, the app is saturated.
    Unlike `DatabaseOfflineError` this is not waited out (AD-7); it is raised so the
    host retries the message."""


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
    pool_size: int = POOL_SIZE,
    pool_timeout: float = 30,
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
        # pipeline runs one message at a time per function (AD-2): one connection
        # per function (POOL_SIZE) stays well inside the B1ms connection limit.
        pool_size=pool_size,
        max_overflow=0,
        # A checkout that waits longer raises DatabaseBusyError (open_connection).
        pool_timeout=pool_timeout,
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


def open_connection(engine: Engine) -> Connection:
    """A connection from `engine`, or `DatabaseOfflineError` when none can be opened:
    the server refuses or times out (psycopg `OperationalError`, usually a stopped
    server, AD-12) or the Entra token can't be fetched. Only connecting is mapped; a
    query that fails later raises as it is (AD-7). The error text may name the host,
    so only a code is logged and nothing is chained. A pool with every connection in
    use raises `DatabaseBusyError` instead, retried by the host."""
    try:
        return engine.connect()
    except PoolTimeoutError:
        log_event(
            _logger, "postgres.pool_timeout", level=logging.WARNING, code="POOL_TIMEOUT"
        )
        raise DatabaseBusyError("every database connection is in use") from None
    except (OperationalError, InterfaceError):
        code = "CONNECT_FAILED"
    except AzureError:
        code = "TOKEN_FAILED"
    log_event(_logger, "postgres.unreachable", level=logging.WARNING, code=code)
    raise DatabaseOfflineError() from None
