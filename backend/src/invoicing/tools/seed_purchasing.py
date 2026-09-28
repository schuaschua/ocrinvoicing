"""Seed the purchasing simulation (Story 2.4, CAP-20) with its synthetic data.

    PG*=... uv run --directory backend python -m invoicing.tools.seed_purchasing [--file F]

The connection comes from the libpq variables PGHOST, PGPORT, PGUSER, PGPASSWORD (an
Entra token), PGDATABASE and PGSSLMODE, as for `ci/migrate.sh`; psycopg reads them
itself. Run it as the environment's deploy identity, which owns the schema: the app
logins can only read it (AD-11). Idempotent: rows are upserted by natural key.

It refuses `invoicing_prod` unless `--allow-prod` is given: seeding Prod with the
synthetic data is a deliberate PoC choice (infra/bootstrap/README.md).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import NullPool, create_engine, func, select

from invoicing.adapters.purchasing_sim.seed import (
    DEFAULT_SEED_FILE,
    PurchasingSeed,
    load_seed,
    seed,
)

PROD_DATABASE = "invoicing_prod"


def main(argv: Sequence[str] | None = None) -> int:
    """Load the seed file into the database the PG* variables name; print the counts."""
    parser = argparse.ArgumentParser(
        prog="python -m invoicing.tools.seed_purchasing",
        description="Upsert the synthetic PO and goods-received data.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_SEED_FILE,
        help="seed JSON (default: backend/seed/, the synthetic data set)",
    )
    parser.add_argument(
        "--allow-prod",
        action="store_true",
        help=f"also seed {PROD_DATABASE} (synthetic data; a deliberate PoC choice)",
    )
    args = parser.parse_args(argv)
    try:
        data: PurchasingSeed = load_seed(args.file)
    except OSError as error:
        print(f"error: can't read the seed file: {error.strerror}", file=sys.stderr)
        return 2
    except ValidationError as error:
        print(
            f"error: the seed file is invalid ({error.error_count()} problem(s)):"
            f" {error.errors()[0]['msg']}",
            file=sys.stderr,
        )
        return 2
    # An empty URL: libpq takes every connection parameter from the PG* variables.
    engine = create_engine("postgresql+psycopg://", poolclass=NullPool)
    try:
        with engine.begin() as connection:
            database = connection.execute(select(func.current_database())).scalar()
            if database == PROD_DATABASE and not args.allow_prod:
                print(
                    f"error: refusing to seed {PROD_DATABASE} without --allow-prod",
                    file=sys.stderr,
                )
                return 2
            try:
                result = seed(connection, data)
            except ValueError as error:
                print(f"error: {error}", file=sys.stderr)
                return 2
    finally:
        engine.dispose()
    for table, count in result.written.items():
        print(f"{table}: {count} row(s) upserted")
    extra = {table: n for table, n in result.not_in_file.items() if n}
    if extra:
        listed = ", ".join(f"{table} {n}" for table, n in extra.items())
        print(
            f"warning: rows in the database that are not in the file (kept): {listed}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
