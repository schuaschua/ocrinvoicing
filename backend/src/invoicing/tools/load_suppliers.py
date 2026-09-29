"""Load the supplier master and issue upload links (Story 1.6, AD-6, AD-11).

    az login   # as Dj's user
    PG*=... uv run --directory backend python -m invoicing.tools.load_suppliers \\
        --file suppliers.csv --host <supplier-api host> \\
        --vault-uri https://<env vault>.vault.azure.net/ --account <storage account>
    ... --replace-link <supplier_id>   # revoke the supplier's link, issue a new one
    ... --revoke <supplier_id>         # revoke it without issuing another

The database connection comes from the libpq variables PGHOST, PGPORT, PGUSER (Dj's
UPN), PGPASSWORD (an Entra token), PGDATABASE and PGSSLMODE, as for the purchasing
seed. Key Vault and Table Storage are reached with the operator's Azure CLI sign-in:
Dj holds Key Vault Secrets User on `pgp-public-key` and `hmac-key` only, and Storage
Table Data Contributor (AD-17 step 5). Nothing here reads the private key or decrypts.

Order (plan Design Notes): the CSV is checked first; then one database transaction
writes suppliers, bank rows and their audit entries; only after its commit are links
planned and issued, replaced or revoked. Each link change is audited
(`supplier_link.issued`, `.replaced`, `.revoked`, supplier id only) before it is made,
so a failure leaves the attempt on record, and the error names the command that
finishes the work.

Every supplier in the CSV without an active link gets one (Dj, 2026-09-29), so a re-run
with the same CSV issues nothing, and a supplier revoked earlier gets a fresh link on
the next load while it is still in the CSV: to keep one revoked, remove it from the
CSV. A `--revoke` target in the same run is never re-issued a link.

Each new link is printed once, on its own stdout line, and never again: only its token
hash is stored (AD-6). No other output, log or audit entry holds a token, its hash, a
bank value or a phone number. It refuses `invoicing_prod` unless `--allow-prod` is
given. Errors are one line on stderr: exit 2 for a refused input, 1 for a failure.
"""

import argparse
import asyncio
import re
import sys
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from azure.core.exceptions import AzureError
from sqlalchemy import Engine, NullPool, create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError

from invoicing.adapters.key_vault import SecretReadError, read_secrets
from invoicing.adapters.postgres.suppliers import (
    LINK_ISSUED,
    LINK_REPLACED,
    LINK_REVOKED,
    BankKeys,
    LoadResult,
    load_suppliers,
    supplier_names,
    write_audit,
)
from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.links import new_token, token_hash, upload_link
from invoicing.domain.suppliers import (
    SupplierCsvError,
    SupplierRow,
    parse_supplier_csv,
)
from invoicing.ports.links import SupplierLink, SupplierLinkRegistry

PROD_DATABASE = "invoicing_prod"
PUBLIC_KEY_SECRET = "pgp-public-key"  # noqa: S105  # the secret's name, not a value
HMAC_KEY_SECRET = "hmac-key"  # noqa: S105  # the secret's name, not a value

# A bare host name (the supplier-api app's `<name>.azurewebsites.net`): no scheme or path.
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})+")
_VAULT_URI = re.compile(r"https://[a-z0-9-]{3,24}\.vault\.azure\.net/?")
_STORAGE_ACCOUNT = re.compile(r"[a-z0-9]{3,24}")


class _RefusedError(Exception):
    """An input or state the script refuses (exit 2), before anything changed."""


class _FailedError(Exception):
    """A failure (exit 1). The message is safe to print: codes and ids only."""


@dataclass(frozen=True)
class Dependencies:
    """What the script reaches outside the database; tests pass fakes (no Azure)."""

    read_keys: Callable[[str], BankKeys]
    open_registry: Callable[[str], SupplierLinkRegistry]
    close_registry: Callable[[SupplierLinkRegistry], Awaitable[None]]
    now: Callable[[], datetime]


def _read_keys_from_vault(vault_uri: str) -> BankKeys:
    from azure.identity import AzureCliCredential

    credential = AzureCliCredential()
    try:
        values = read_secrets(
            vault_uri, (PUBLIC_KEY_SECRET, HMAC_KEY_SECRET), credential
        )
    finally:
        credential.close()
    return BankKeys(
        public_key=values[PUBLIC_KEY_SECRET], hmac_key=values[HMAC_KEY_SECRET]
    )


def _open_table_registry(account: str) -> SupplierLinkRegistry:
    from azure.identity.aio import AzureCliCredential

    return TableSupplierLinkRegistry.with_credential(account, AzureCliCredential())


async def _close_table_registry(registry: SupplierLinkRegistry) -> None:
    if isinstance(registry, TableSupplierLinkRegistry):
        await registry.close()


AZURE = Dependencies(
    read_keys=_read_keys_from_vault,
    open_registry=_open_table_registry,
    close_registry=_close_table_registry,
    now=lambda: datetime.now(UTC),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m invoicing.tools.load_suppliers",
        description="Load synthetic suppliers into `master` and issue upload links.",
    )
    parser.add_argument(
        "--file", type=Path, help="supplier CSV (see infra/bootstrap/README.md)"
    )
    parser.add_argument(
        "--host", help="supplier-api host name, e.g. <app>.azurewebsites.net"
    )
    parser.add_argument("--vault-uri", help="the environment's Key Vault URI")
    parser.add_argument(
        "--account", required=True, help="the environment's storage account"
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--replace-link",
        metavar="ID",
        type=UUID,
        help="revoke this supplier's link and issue a new one",
    )
    action.add_argument(
        "--revoke",
        metavar="ID",
        type=UUID,
        help="revoke this supplier's link, issue none",
    )
    parser.add_argument(
        "--allow-prod",
        action="store_true",
        help=f"also run against {PROD_DATABASE} (synthetic data, on purpose)",
    )
    return parser


def _check_arguments(args: argparse.Namespace) -> None:
    if args.file is None and args.replace_link is None and args.revoke is None:
        raise _RefusedError("nothing to do: give --file, --replace-link or --revoke")
    if _STORAGE_ACCOUNT.fullmatch(args.account) is None:
        raise _RefusedError("--account is not a storage account name")
    issues_links = args.file is not None or args.replace_link is not None
    if issues_links and (args.host is None or _HOST.fullmatch(args.host) is None):
        raise _RefusedError(
            "--host must be the supplier-api host name, without https://"
        )
    if args.file is not None and (
        args.vault_uri is None or _VAULT_URI.fullmatch(args.vault_uri) is None
    ):
        raise _RefusedError("--vault-uri must be https://<vault>.vault.azure.net/")


def _read_csv(path: Path) -> tuple[SupplierRow, ...]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        reason = error.strerror or type(error).__name__
        raise _RefusedError(f"can't read the CSV: {reason}") from None
    except UnicodeDecodeError:
        raise _RefusedError("the CSV is not UTF-8") from None
    try:
        return parse_supplier_csv(text)
    except SupplierCsvError as error:
        raise _RefusedError(f"the CSV is invalid: {error}") from None


async def _links_call[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except ServiceUnavailableError:
        raise _FailedError("Table Storage (supplierlinks) can't be reached") from None


@contextmanager
def _recover(recovery: str) -> Iterator[None]:
    """A link step that fails is reported with the exact way to finish it."""
    try:
        yield
    except _FailedError as error:
        raise _FailedError(f"{error}; {recovery}") from None
    except SQLAlchemyError as error:
        raise _FailedError(f"{_database(error)}; {recovery}") from None


async def _active_links(registry: SupplierLinkRegistry, supplier_id: UUID) -> list[str]:
    """The token hashes of the supplier's active links (never printed or logged)."""
    links = await _links_call(registry.find_by_supplier(supplier_id))
    return [item.token_hash for item in links if item.link.is_active]


def _summary(result: LoadResult) -> str:
    return (
        f"suppliers: {len(result.created)} created, {len(result.updated)} updated,"
        f" {len(result.unchanged)} unchanged; bank fields: {result.bank_added} added,"
        f" {result.bank_changed} changed"
    )


def _audit(
    engine: Engine, action: str, supplier_id: UUID, detail: dict[str, int]
) -> None:
    # Its own transaction, committed before the link changes, so a failure after it
    # still leaves the attempt in the audit log (security.md rule 32).
    with engine.begin() as connection:
        write_audit(connection, action, "supplier_link", supplier_id, detail)


async def _issue(
    engine: Engine,
    registry: SupplierLinkRegistry,
    supplier_id: UUID,
    name: str,
    args: argparse.Namespace,
    now: datetime,
    retry: str,
) -> None:
    """Audit, store and print one new link. `retry` is the command that finishes the
    work when storing fails."""
    with _recover(f"no link was issued for {supplier_id}; {retry}"):
        _audit(engine, LINK_ISSUED, supplier_id, {})
    token = new_token()
    link = SupplierLink(
        supplier_id=supplier_id, supplier_name=name, issued_at=now, revoked_at=None
    )
    # A lost response may hide a stored link whose token nobody saw (a 409 on retry).
    with _recover(
        f"the link for {supplier_id} may or may not be stored; {retry}, and if that"
        f" prints no link for {supplier_id}, run --replace-link {supplier_id}"
    ):
        await _links_call(registry.issue(token_hash(token), link))
    # The one place a token is ever shown (AD-6): printed once, never stored.
    print(f"link for {supplier_id} ({name}): {upload_link(args.host, token)}")


async def _change_links(
    engine: Engine,
    registry: SupplierLinkRegistry,
    args: argparse.Namespace,
    rows: tuple[SupplierRow, ...],
    target: UUID | None,
    target_name: str,
    target_links: list[str],
    now: datetime,
) -> None:
    # Planned after the commit, so no Table call runs while rows are locked.
    issue: list[tuple[UUID, str]] = []
    for row in rows:
        if row.supplier_id == target:
            continue
        # A supplier without an active link gets one (Dj, 2026-09-29): a re-run
        # issues nothing, and a revoked supplier still in the CSV is issued afresh.
        if not await _active_links(registry, row.supplier_id):
            issue.append((row.supplier_id, row.name))
    for supplier_id, name in issue:
        await _issue(
            engine, registry, supplier_id, name, args, now, "run the same command again"
        )
    if target is None:
        if not issue:
            print("links: none issued")
        return
    replacing = args.replace_link is not None
    retry = (
        f"run --replace-link {target} again"
        if replacing
        else (
            f"run --revoke {target} again (if it answers that there is no active link,"
            " the revoke is complete)"
        )
    )
    # Audited before the change: a failure leaves the attempt on record.
    with _recover(f"nothing was changed for {target}; run the same command again"):
        _audit(
            engine,
            LINK_REPLACED if replacing else LINK_REVOKED,
            target,
            {"revoked": len(target_links)},
        )
    with _recover(retry):
        for hashed in target_links:
            await _links_call(registry.revoke(hashed, now))
    if replacing:
        await _issue(engine, registry, target, target_name, args, now, retry)
    verb = "replaced" if replacing else "revoked"
    print(f"link {verb} for {target} ({len(target_links)} revoked)")


async def _run(args: argparse.Namespace, deps: Dependencies) -> None:
    rows = _read_csv(args.file) if args.file is not None else ()
    target: UUID | None = args.replace_link or args.revoke
    # hide_parameters: a database error never echoes a bank value, key or phone.
    engine = create_engine(
        "postgresql+psycopg://", poolclass=NullPool, hide_parameters=True
    )
    registry = deps.open_registry(args.account)
    try:
        # Read before the transaction, so a refused --revoke changes nothing.
        target_links = await _active_links(registry, target) if target else []
        target_name = ""
        with engine.begin() as connection:
            database = connection.execute(select(func.current_database())).scalar()
            if database == PROD_DATABASE and not args.allow_prod:
                raise _RefusedError(f"refusing {PROD_DATABASE} without --allow-prod")
            result = LoadResult()
            if rows:
                keys = deps.read_keys(args.vault_uri)
                result = load_suppliers(connection, rows, keys)
            if target is not None:
                names = supplier_names(connection, [target])
                if target not in names:
                    raise _RefusedError(f"supplier {target} is not in master.supplier")
                if args.revoke is not None and not target_links:
                    raise _RefusedError(
                        f"supplier {target} has no active link to revoke"
                    )
                target_name = names[target]
        if rows:
            print(_summary(result))
        # Links change only after the commit (plan Design Notes).
        try:
            await _change_links(
                engine,
                registry,
                args,
                rows,
                target,
                target_name,
                target_links,
                deps.now(),
            )
        except _FailedError as error:
            saved = "the supplier data is saved; " if rows else ""
            raise _FailedError(f"{saved}{error}") from None
    finally:
        await deps.close_registry(registry)
        engine.dispose()


def _database(error: SQLAlchemyError) -> str:
    # The statement's parameters (values, keys) never reach the message.
    code = getattr(getattr(error, "orig", None), "sqlstate", None)
    return f"database: {type(error).__name__}" + (f" (SQLSTATE {code})" if code else "")


def main(argv: Sequence[str] | None = None, *, deps: Dependencies = AZURE) -> int:
    """Run the load; 0 on success, 2 when refused (nothing changed), 1 on a failure."""
    args = _parser().parse_args(argv)
    try:
        _check_arguments(args)
        asyncio.run(_run(args, deps))
    except _RefusedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except _FailedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except SecretReadError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except AzureError as error:
        # The SDK's message may carry a URL: the class name only.
        print(f"error: Azure: {type(error).__name__}", file=sys.stderr)
        return 1
    except SQLAlchemyError as error:
        print(f"error: {_database(error)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
