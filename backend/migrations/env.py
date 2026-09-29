"""Alembic environment (Story 2.1, AD-11, AD-17 step 6).

Connection: the libpq variables PGHOST, PGPORT, PGUSER, PGPASSWORD (an Entra token),
PGDATABASE and PGSSLMODE, which ci/migrate.sh sets; psycopg reads them itself, so no
URL or credential is written anywhere. Tests may pass an open connection as
`config.attributes["connection"]` instead.

Role names: every schema grant is a migration (AD-11), and the logins differ per
environment, so they come from `-x` arguments and are never literals in a migration:

    alembic -x pipeline_role=<login> -x staff_api_role=<login> -x dj_role=<login> \
        upgrade head

`dj_role` is Dj's user (a UPN), the supplier load script's login (Story 1.6).

Migrations run in the deploy pipeline only, never at app start (AD-17).
"""

import re

from alembic import context
from sqlalchemy import Connection, create_engine, pool

# The logins a migration may grant to (AD-11), by `-x` argument name.
ROLE_ARGUMENTS = ("pipeline_role", "staff_api_role", "dj_role")
# Entra principal names: managed identity names (letters, digits, - and _) or a UPN.
_ROLE_NAME = re.compile(r"[A-Za-z0-9_.@-]{1,63}")

config = context.config


def _roles() -> dict[str, str]:
    given = context.get_x_argument(as_dictionary=True)
    missing = [name for name in ROLE_ARGUMENTS if not given.get(name)]
    if missing:
        needed = " ".join(f"-x {name}=<login>" for name in missing)
        raise SystemExit(f"alembic needs the database logins to grant to: {needed}")
    roles = {name: str(given[name]) for name in ROLE_ARGUMENTS}
    for name, value in roles.items():
        if _ROLE_NAME.fullmatch(value) is None:
            raise SystemExit(f"-x {name} is not a valid login name")
    return roles


def _run(connection: Connection) -> None:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Read by the revisions through `context.config.attributes["roles"]`.
    config.attributes["roles"] = _roles()
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    # An empty URL: libpq takes every connection parameter from the PG* variables.
    engine = create_engine("postgresql+psycopg://", poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise SystemExit(
        "offline (--sql) migrations are not used; run against the database"
    )
run_migrations_online()
