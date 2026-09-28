"""Story 2.4: the operator seed command loads the synthetic purchasing data through
the PG* variables, is idempotent, and refuses an inconsistent file."""

import json
import secrets
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from conftest import PostgresServer
from invoicing.adapters.purchasing_sim.seed import DEFAULT_SEED_FILE, load_seed
from invoicing.tools.seed_purchasing import main

TABLES = (
    "material",
    "purchase_order",
    "po_line",
    "delivery",
    "goods_receipt",
    "goods_receipt_line",
)


def _counts(server: PostgresServer, database: str) -> dict[str, int]:
    engine = create_engine(server.url(server.deployer, database))
    try:
        with engine.connect() as connection:
            return {
                table: connection.execute(
                    text(f"SELECT count(*) FROM sim_purchasing.{table}")  # noqa: S608  # fixed names
                ).scalar_one()
                for table in TABLES
            }
    finally:
        engine.dispose()


def _snapshot(server: PostgresServer, database: str) -> list[Any]:
    engine = create_engine(server.url(server.deployer, database))
    try:
        with engine.connect() as connection:
            return [
                sorted(
                    tuple(row)
                    for row in connection.execute(
                        text(f"SELECT * FROM sim_purchasing.{table}")  # noqa: S608  # fixed names
                    )
                )
                for table in TABLES
            ]
    finally:
        engine.dispose()


@pytest.fixture
def seed_database(postgres_server: PostgresServer) -> str:
    """A fresh, migrated, empty database, so the counts are the seed's alone."""
    database = f"invoicing_seed_{secrets.token_hex(4)}"
    postgres_server.create_database(database)
    result = postgres_server.alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    return database


def test_story_2_4_seed_twice_gives_the_same_rows(
    postgres_server: PostgresServer,
    seed_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The command connects through the PG* variables only, as ci/migrate.sh does.
    for name, value in postgres_server.libpq_env(
        postgres_server.deployer, seed_database
    ).items():
        monkeypatch.setenv(name, value)
    assert main([]) == 0
    first = _counts(postgres_server, seed_database)
    assert first == {
        "material": 3,
        "purchase_order": 6,
        "po_line": 8,
        "delivery": 5,
        "goods_receipt": 4,
        "goods_receipt_line": 4,
    }
    output = capsys.readouterr()
    assert "po_line: 8 row(s) upserted" in output.out
    assert "warning" not in output.err
    before = _snapshot(postgres_server, seed_database)
    assert main(["--file", str(DEFAULT_SEED_FILE)]) == 0
    assert _counts(postgres_server, seed_database) == first
    assert _snapshot(postgres_server, seed_database) == before


def test_story_2_4_seed_updates_rows_by_natural_key(
    postgres_server: PostgresServer,
    seed_database: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name, value in postgres_server.libpq_env(
        postgres_server.deployer, seed_database
    ).items():
        monkeypatch.setenv(name, value)
    assert main([]) == 0
    data = json.loads(DEFAULT_SEED_FILE.read_text())
    data["purchase_orders"][0]["lines"][0]["unit_price"] = "7.90"
    changed = tmp_path / "seed.json"
    changed.write_text(json.dumps(data))
    assert main(["--file", str(changed)]) == 0
    capsys.readouterr()
    # A PO dropped from the file stays in the database, with a warning (counts only).
    del data["purchase_orders"][-1]
    changed.write_text(json.dumps(data))
    assert main(["--file", str(changed)]) == 0
    warning = capsys.readouterr().err
    assert "not in the file (kept): purchase_order 1, po_line 1, delivery 1" in warning
    assert "PO-45017" not in warning
    engine = create_engine(postgres_server.url(postgres_server.deployer, seed_database))
    try:
        with engine.connect() as connection:
            prices = (
                connection.execute(
                    text(
                        "SELECT unit_price FROM sim_purchasing.po_line"
                        " WHERE po_number = 'PO-45012' AND line_no = 1"
                    )
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()
    assert [str(p) for p in prices] == ["7.90"]


def test_story_2_4_the_seed_holds_the_required_cases() -> None:
    data = load_seed()
    by_po = {po.po_number: po for po in data.purchase_orders}
    # The same material from 3 or more suppliers, at different prices.
    cement = [
        (po.supplier_id, line.unit_price)
        for po in data.purchase_orders
        for line in po.lines
        if line.material_code == "MAT-CEMENT-50KG"
    ]
    assert len({supplier for supplier, _ in cement}) >= 3
    assert len({price for _, price in cement}) == len(cement)
    # A PO delivered in 2 parts, one with no receipt, one overdue, a goods-in delivery.
    assert len([d for d in by_po["PO-45012"].deliveries if d.receipt]) == 2
    assert by_po["PO-45014"].deliveries == ()
    # PO-45012's second part receives only line 2, which is due later than line 1.
    second = by_po["PO-45012"].deliveries[1].receipt
    assert second is not None and set(second.lines) == {2}
    # A delivery that has arrived but has no goods receipt yet.
    assert [d.receipt for d in by_po["PO-45017"].deliveries] == [None]
    assert by_po["PO-45015"].deliveries == ()
    assert by_po["PO-45016"].deliveries[0].receipt is not None
    # Every supplier id is one of the fixed ids listed in the file.
    assert {po.supplier_id for po in data.purchase_orders} <= {
        s.supplier_id for s in data.suppliers
    }


def _broken(tmp_path: Path, change: Any) -> Path:
    data = json.loads(DEFAULT_SEED_FILE.read_text())
    change(data)
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(data))
    return path


def _set(path: list[Any], value: Any) -> Any:
    def change(data: Any) -> None:
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_set(["purchase_orders", 0, "supplier_id"], "01a0c450-0000-7000-8000-00000000000f"), "supplier"),
        (_set(["purchase_orders", 0, "lines", 0, "material_code"], "MAT-NOPE"), "material code"),
        (_set(["purchase_orders", 0, "lines", 1, "line_no"], 1), "line numbers repeat"),
        (_set(["purchase_orders", 0, "deliveries", 1, "delivery_no"], 1), "delivery numbers repeat"),
        (_set(["purchase_orders", 0, "deliveries", 0, "receipt", "lines"], {"9": "1"}), "line the PO does not have"),
        (_set(["purchase_orders", 1, "po_number"], "PO-45012"), "PO numbers repeat"),
        (_set(["materials", 1, "code"], "MAT-CEMENT-50KG"), "material codes repeat"),
        (_set(["purchase_orders", 1, "lines", 0, "po_line_id"], "01a0c450-8370-7ad0-8b7e-e79b9256c746"), "ids repeat"),
        (_set(["purchase_orders", 0, "lines", 0, "unit_price"], "7.805"), "decimal"),
        (_set(["purchase_orders", 0, "lines", 0, "quantity"], "0"), "greater than 0"),
        (_set(["purchase_orders", 0, "surprise"], 1), "Extra inputs"),
        (_set(["purchase_orders", 0, "lines", 0, "expected_date"], "2026-08-19"), "expected before the order"),
        (_set(["purchase_orders", 0, "deliveries", 0, "delivery_date"], "2026-08-19"), "delivery is before the order"),
        (_set(["purchase_orders", 0, "deliveries", 0, "receipt", "received_date"], "2026-09-01"), "receipt is before its delivery"),
        (_set(["purchase_orders", 0, "deliveries", 0, "receipt", "lines"], {"1": "100.001"}), "more received than ordered"),
    ],
)  # fmt: skip
def test_story_2_4_an_inconsistent_seed_is_refused(
    tmp_path: Path, change: Any, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        load_seed(_broken(tmp_path, change))


def _connect_as_deployer(
    server: PostgresServer, database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in server.libpq_env(server.deployer, database).items():
        monkeypatch.setenv(name, value)


def test_story_2_4_an_id_stored_under_another_key_is_refused_before_writing(
    postgres_server: PostgresServer,
    seed_database: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _connect_as_deployer(postgres_server, seed_database, monkeypatch)
    assert main([]) == 0
    before = _snapshot(postgres_server, seed_database)
    data = json.loads(DEFAULT_SEED_FILE.read_text())
    # PO-45012 line 1's id, reused for a new line 3 of PO-45013.
    reused = data["purchase_orders"][0]["lines"][0]["po_line_id"]
    data["purchase_orders"][0]["lines"][0]["po_line_id"] = (
        "01a0c450-0000-7000-8000-0000000000a1"
    )
    line = dict(data["purchase_orders"][1]["lines"][0], line_no=3, po_line_id=reused)
    data["purchase_orders"][1]["lines"].append(line)
    changed = tmp_path / "seed.json"
    changed.write_text(json.dumps(data))
    assert main(["--file", str(changed)]) == 2
    assert f"PO line id {reused} is already stored under another natural key" in (
        capsys.readouterr().err
    )
    assert _snapshot(postgres_server, seed_database) == before


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "error: can't read the seed file"),
        ("{not json", "error: the seed file is invalid"),
        ('{"suppliers": []}', "error: the seed file is invalid"),
    ],
)
def test_story_2_4_a_missing_or_invalid_file_exits_2_with_one_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: str | None,
    message: str,
) -> None:
    path = tmp_path / "seed.json"
    if content is not None:
        path.write_text(content)
    assert main(["--file", str(path)]) == 2
    err = capsys.readouterr().err
    assert err.startswith(message)
    assert err.count("\n") == 1


def test_story_2_4_prod_is_refused_unless_allowed(
    postgres_server: PostgresServer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    postgres_server.create_database("invoicing_prod")
    result = postgres_server.alembic("invoicing_prod", "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    _connect_as_deployer(postgres_server, "invoicing_prod", monkeypatch)
    assert main([]) == 2
    assert "refusing to seed invoicing_prod without --allow-prod" in (
        capsys.readouterr().err
    )
    assert _counts(postgres_server, "invoicing_prod")["purchase_order"] == 0
    assert main(["--allow-prod"]) == 0
    assert _counts(postgres_server, "invoicing_prod")["purchase_order"] == 6
