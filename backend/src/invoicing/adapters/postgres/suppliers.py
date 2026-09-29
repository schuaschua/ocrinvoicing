"""The supplier master (`master`) and the audit log (`audit`), as migration
0004_master_audit creates them, and the supplier load (Story 1.6, AD-11).

Bank values are encrypted in SQL with `pgp_pub_encrypt` and the environment's public
key, and fingerprinted in Python (`domain/suppliers.py`); nothing here decrypts. A
value is compared by its fingerprint only, so re-loading the same CSV writes nothing
(pgp ciphertext differs on every call, the fingerprint never does).

`audit.event.detail` holds field ids and counts, never a value (AD-11).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    Column,
    Connection,
    ForeignKey,
    LargeBinary,
    MetaData,
    Table,
    Text,
    Uuid,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB

from invoicing.domain.ids import new_uuid7
from invoicing.domain.suppliers import (
    SupplierRow,
    bank_fingerprint,
    normalise_bank_value,
)

MASTER = "master"
AUDIT = "audit"

metadata = MetaData()

supplier = Table(
    "supplier",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("tax_id", Text),
    Column("phone", Text),
    schema=MASTER,
)

# One row per AD-18 bank field id. The pipeline login may read every column but
# `ciphertext` (AD-11).
supplier_bank = Table(
    "supplier_bank",
    metadata,
    Column("supplier_id", Uuid, ForeignKey(f"{MASTER}.supplier.id"), primary_key=True),
    Column("field_id", Text, primary_key=True),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("fingerprint", Text, nullable=False),
    schema=MASTER,
)

# Append-only (security.md rule 32): every writer may INSERT, nobody UPDATEs or DELETEs.
event = Table(
    "event",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("at", TIMESTAMP(timezone=True), nullable=False),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("entity", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("detail", JSONB, nullable=False),
    schema=AUDIT,
)

# audit.event actions this module writes.
SUPPLIER_CREATED = "supplier.created"
SUPPLIER_UPDATED = "supplier.updated"
BANK_FIELD_ADDED = "supplier_bank.added"
BANK_FIELD_CHANGED = "supplier_bank.changed"
LINK_ISSUED = "supplier_link.issued"
LINK_REPLACED = "supplier_link.replaced"
LINK_REVOKED = "supplier_link.revoked"


@dataclass(frozen=True)
class BankKeys:
    """The environment's `pgp-public-key` (ASCII-armoured) and `hmac-key` secrets."""

    public_key: str
    hmac_key: str

    def __repr__(self) -> str:
        # Never print key material, even the public key, by accident.
        return "BankKeys(...)"


@dataclass
class LoadResult:
    """What a load changed: supplier ids by outcome, and bank field counts."""

    created: list[UUID] = field(default_factory=list)
    updated: list[UUID] = field(default_factory=list)
    unchanged: list[UUID] = field(default_factory=list)
    bank_added: int = 0
    bank_changed: int = 0


def write_audit(
    connection: Connection,
    action: str,
    entity: str,
    entity_id: UUID,
    detail: Mapping[str, Any] | None = None,
) -> None:
    """Append one `audit.event` row. `at` and `actor` (`current_user`, the database
    login) are always the column defaults: no writer may set them (migration 0004)."""
    connection.execute(
        insert(event).values(
            id=new_uuid7(),
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            detail=dict(detail or {}),
        )
    )


def supplier_names(connection: Connection, ids: Iterable[UUID]) -> dict[UUID, str]:
    """The stored name of each supplier in `ids` that exists."""
    wanted = list(ids)
    if not wanted:
        return {}
    rows = connection.execute(
        select(supplier.c.id, supplier.c.name).where(supplier.c.id.in_(wanted))
    )
    return {row.id: row.name for row in rows}


def _upsert_supplier(
    connection: Connection, row: SupplierRow, result: LoadResult
) -> None:
    # A blank phone or tax id (None) leaves the stored value unchanged, as a blank
    # bank field does (Dj, 2026-09-29); a new supplier stores it as NULL.
    values = {"name": row.name, "tax_id": row.tax_id, "phone": row.phone}
    stored = connection.execute(
        select(supplier.c.name, supplier.c.tax_id, supplier.c.phone)
        .where(supplier.c.id == row.supplier_id)
        .with_for_update()
    ).one_or_none()
    if stored is None:
        connection.execute(insert(supplier).values(id=row.supplier_id, **values))
        write_audit(connection, SUPPLIER_CREATED, "supplier", row.supplier_id)
        result.created.append(row.supplier_id)
        return
    changed = sorted(
        name
        for name, value in values.items()
        if value is not None and stored._mapping[name] != value
    )
    if not changed:
        result.unchanged.append(row.supplier_id)
        return
    connection.execute(
        update(supplier)
        .where(supplier.c.id == row.supplier_id)
        .values({name: values[name] for name in changed})
    )
    # Column names only, never their values (the phone is personal data).
    write_audit(
        connection, SUPPLIER_UPDATED, "supplier", row.supplier_id, {"fields": changed}
    )
    result.updated.append(row.supplier_id)


def _upsert_bank(
    connection: Connection, row: SupplierRow, keys: BankKeys, result: LoadResult
) -> bool:
    """Write each non-empty bank field whose fingerprint differs; True if any did."""
    stored: dict[str, str] = {
        r.field_id: r.fingerprint
        for r in connection.execute(
            select(supplier_bank.c.field_id, supplier_bank.c.fingerprint)
            .where(supplier_bank.c.supplier_id == row.supplier_id)
            .with_for_update()
        )
    }
    wrote = False
    for field_id, value in sorted(row.bank.items()):
        fingerprint = bank_fingerprint(keys.hmac_key, value)
        if stored.get(field_id) == fingerprint:
            continue
        # The normalised value, the same string the fingerprint covers (AD-11:
        # "normalised first"), encrypted in SQL with bound parameters (rule 21).
        ciphertext = func.pgp_pub_encrypt(
            normalise_bank_value(value), func.dearmor(keys.public_key)
        )
        if field_id in stored:
            connection.execute(
                update(supplier_bank)
                .where(
                    supplier_bank.c.supplier_id == row.supplier_id,
                    supplier_bank.c.field_id == field_id,
                )
                .values(ciphertext=ciphertext, fingerprint=fingerprint)
            )
            action = BANK_FIELD_CHANGED
            result.bank_changed += 1
        else:
            connection.execute(
                insert(supplier_bank).values(
                    supplier_id=row.supplier_id,
                    field_id=field_id,
                    ciphertext=ciphertext,
                    fingerprint=fingerprint,
                )
            )
            action = BANK_FIELD_ADDED
            result.bank_added += 1
        write_audit(
            connection, action, "supplier_bank", row.supplier_id, {"field_id": field_id}
        )
        wrote = True
    return wrote


def load_suppliers(
    connection: Connection, rows: Iterable[SupplierRow], keys: BankKeys
) -> LoadResult:
    """Create or update each supplier and its non-empty bank fields in the caller's
    transaction, with one audit entry per change. A blank bank field, phone or tax id
    leaves the stored value alone, and a row identical to the stored one writes nothing."""
    result = LoadResult()
    for row in rows:
        _upsert_supplier(connection, row, result)
        bank_changed = _upsert_bank(connection, row, keys, result)
        if bank_changed and row.supplier_id in result.unchanged:
            # Only its bank details changed: still an updated supplier in the summary.
            result.unchanged.remove(row.supplier_id)
            result.updated.append(row.supplier_id)
    return result
