"""Shared fixtures. Tests never call Azure (coding-style.md rule 23); the Story 2.1
integration tests use a throwaway PostgreSQL in Docker."""

import importlib
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import URL, Engine, NullPool, create_engine, text
from sqlalchemy.exc import OperationalError

from invoicing.adapters.postgres.engine import postgres_engine

# Values the Terraform app stack sets (infra/modules/env-app), all synthetic.
APP_SETTINGS = {
    "APP_ENVIRONMENT": "local",
    "AZURE_CLIENT_ID": "00000000-0000-0000-0000-00000000c1d0",
    "STORAGE_ACCOUNT_NAME": "babaloosealngst01",
    "KEY_VAULT_URI": "https://babaloo-sea-lng-kv-01.vault.azure.net/",
}

# Settings only one app gets (infra/modules/env-app app_specific_settings). Story 2.1:
# the pipeline's database and login (no password: Entra token); supplier-api has no
# database setting at all (AD-6, AD-11).
APP_ONLY_SETTINGS = {
    "pipeline": {
        "POSTGRES_HOST": "babaloo-sea-lng-psql-21.postgres.database.azure.com",
        "POSTGRES_DATABASE": "invoicing_dev",
        "POSTGRES_USER": "babaloo-sea-lng-id-03",
    },
}


TELEMETRY_SETTINGS = (
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "APPLICATIONINSIGHTS_AUTHENTICATION_STRING",
    "TELEMETRY_SAMPLING_RATIO",
)


def _app_under_test(request: pytest.FixtureRequest) -> str | None:
    """The app a test is about: its `app` parameter, else `@pytest.mark.app(<app>)`."""
    callspec = getattr(request.node, "callspec", None)
    if callspec is not None and "app" in callspec.params:
        return str(callspec.params["app"])
    marker = request.node.get_closest_marker("app")
    return str(marker.args[0]) if marker is not None else None


@pytest.fixture
def app_settings(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> dict[str, str]:
    """The settings of the app under test present in the environment, as its
    Terraform stack sets them, and nothing else: no other app's settings and no
    telemetry settings from the developer's shell (tests must never reach a real
    exporter)."""
    only = APP_ONLY_SETTINGS.get(_app_under_test(request) or "", {})
    for name in TELEMETRY_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    for settings in APP_ONLY_SETTINGS.values():
        for name in settings:
            monkeypatch.delenv(name, raising=False)
    settings = {**APP_SETTINGS, **only}
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    return settings


@pytest.fixture
def load_app() -> Iterator[Callable[[str], ModuleType]]:
    """Import `invoicing.apps.<app>.function_app` fresh, as the host does at start-up."""
    loaded: list[str] = []

    def _load(app: str) -> ModuleType:
        name = f"invoicing.apps.{app}.function_app"
        sys.modules.pop(name, None)
        loaded.append(name)
        return importlib.import_module(name)

    yield _load
    for name in loaded:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _telemetry_not_configured() -> Iterator[None]:
    """Each test starts, and ends, with telemetry not yet configured (Story 1.5)."""
    from invoicing.adapters import telemetry

    telemetry.reset_for_tests()
    yield
    telemetry.reset_for_tests()


_SPAN_EXPORTER: InMemorySpanExporter | None = None


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """Finished spans, from an in-memory exporter on the global tracer provider.

    The global provider can be set once per process, so the first use installs it
    (always sampling) and later uses only clear it."""
    global _SPAN_EXPORTER
    if _SPAN_EXPORTER is None:
        _SPAN_EXPORTER = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_SPAN_EXPORTER))
        trace.set_tracer_provider(provider)
    _SPAN_EXPORTER.clear()
    yield _SPAN_EXPORTER
    _SPAN_EXPORTER.clear()


# --- Story 2.1: a throwaway PostgreSQL 18 for the integration tests ----------------------
#
# One container per test session, started only when a test asks for it (coding-style.md
# rule 23: integration tests use a real database in a container). Without Docker the
# tests are skipped locally; under Azure Pipelines (TF_BUILD) that is a failure instead,
# so the PR build can never pass without them.

POSTGRES_IMAGE = "postgres:18"
BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PostgresServer:
    """A running test server: the superuser, plus the AD-11 roles as plain logins."""

    host: str
    port: int
    password: str
    superuser: str = "postgres"
    # The environment's deploy identity: owns the database and runs the migrations.
    deployer: str = "deployer"
    # The app logins the migrations grant to (-x pipeline_role / staff_api_role).
    pipeline: str = "pipeline-login"
    staff_api: str = "staff-api-login"
    # A login with CONNECT but no schema grant (e.g. accounts-sim).
    outsider: str = "accounts-sim-login"

    def url(self, user: str, database: str) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=database,
        )

    def libpq_env(self, user: str, database: str) -> dict[str, str]:
        """The PG* variables ci/migrate.sh sets."""
        return {
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGUSER": user,
            "PGPASSWORD": self.password,
            "PGDATABASE": database,
            "PGSSLMODE": "disable",
        }

    def create_database(self, name: str) -> None:
        """A database set up as AD-17 step 5 does: owned by the deployer, CONNECT only
        for the environment's logins."""
        engine = create_engine(
            self.url(self.superuser, "postgres"), isolation_level="AUTOCOMMIT"
        )
        try:
            with engine.connect() as connection:
                quote = connection.dialect.identifier_preparer.quote_identifier
                db, owner = quote(name), quote(self.deployer)
                logins = ", ".join(
                    quote(r) for r in (self.pipeline, self.staff_api, self.outsider)
                )
                connection.execute(text(f"CREATE DATABASE {db} OWNER {owner}"))
                connection.execute(
                    text(f"REVOKE CONNECT, TEMPORARY ON DATABASE {db} FROM PUBLIC")
                )
                connection.execute(
                    text(f"GRANT CONNECT ON DATABASE {db} TO {owner}, {logins}")
                )
        finally:
            engine.dispose()

    def alembic(self, database: str, *args: str) -> subprocess.CompletedProcess[str]:
        """`alembic -x pipeline_role=... -x staff_api_role=... <args>` from backend/,
        connected through the PG* variables only, as ci/migrate.sh runs it."""
        env = {
            key: value for key, value in os.environ.items() if not key.startswith("PG")
        }
        env.update(self.libpq_env(self.deployer, database))
        return subprocess.run(  # noqa: S603  # our own interpreter and alembic
            [
                sys.executable,
                "-m",
                "alembic",
                "-x",
                f"pipeline_role={self.pipeline}",
                "-x",
                f"staff_api_role={self.staff_api}",
                *args,
            ],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )


def _docker_ready() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    result = subprocess.run(  # noqa: S603  # a fixed docker command
        [docker, "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        check=False,
        timeout=30,
    )
    return result.returncode == 0


def _docker(*args: str) -> str:
    docker = shutil.which("docker") or "docker"
    result = subprocess.run(  # noqa: S603  # fixed docker commands
        [docker, *args], capture_output=True, text=True, check=True, timeout=600
    )
    return result.stdout.strip()


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[PostgresServer]:
    """PostgreSQL 18 in Docker for this session, with the AD-11 logins."""
    if not _docker_ready():
        if os.environ.get("TF_BUILD"):
            pytest.fail("Docker is required for the PostgreSQL integration tests in CI")
        pytest.skip("Docker is not available; the PostgreSQL integration tests need it")
    password = secrets.token_hex(16)
    name = f"invoicing-test-{secrets.token_hex(4)}"
    _docker(
        "run", "-d", "--rm", "--name", name,
        "-e", f"POSTGRES_PASSWORD={password}",
        "-p", "127.0.0.1::5432",
        POSTGRES_IMAGE,
    )  # fmt: skip
    try:
        port = int(_docker("port", name, "5432/tcp").splitlines()[0].rsplit(":", 1)[1])
        server = PostgresServer(host="127.0.0.1", port=port, password=password)
        _wait_until_ready(server)
        engine = create_engine(
            server.url(server.superuser, "postgres"), isolation_level="AUTOCOMMIT"
        )
        with engine.connect() as connection:
            quote = connection.dialect.identifier_preparer.quote_identifier
            for role in (
                server.deployer,
                server.pipeline,
                server.staff_api,
                server.outsider,
            ):
                # DDL takes no bound parameters; the password is hex from secrets.
                connection.execute(
                    text(f"CREATE ROLE {quote(role)} LOGIN PASSWORD '{password}'")
                )
        engine.dispose()
        yield server
    finally:
        _docker("rm", "-f", name)


def _wait_until_ready(server: PostgresServer, timeout_s: float = 90) -> None:
    # Readiness of a container we just started, not time-based behaviour under test.
    engine = create_engine(server.url(server.superuser, "postgres"), poolclass=NullPool)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                return
            except OperationalError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
    finally:
        engine.dispose()


INTAKE_DATABASE = "invoicing_test"


@pytest.fixture(scope="session")
def intake_database(postgres_server: PostgresServer) -> str:
    """A database migrated to head through the Alembic CLI, as the deployer."""
    postgres_server.create_database(INTAKE_DATABASE)
    result = postgres_server.alembic(INTAKE_DATABASE, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    return INTAKE_DATABASE


@pytest.fixture
def pipeline_engine(
    postgres_server: PostgresServer, intake_database: str
) -> Iterator[Engine]:
    """An engine as the pipeline login (so every test also proves its grants), on an
    empty `intake` schema."""
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    with owner.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE intake.admin_item, intake.image_hash, intake.status_history,"
                " intake.invoice"
            )
        )
    owner.dispose()
    engine = postgres_engine(
        host=postgres_server.host,
        port=postgres_server.port,
        database=intake_database,
        user=postgres_server.pipeline,
        password=lambda: postgres_server.password,
        sslmode="disable",
        pool_size=4,
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def purchasing_seeded(postgres_server: PostgresServer, intake_database: str) -> str:
    """The migrated test database with the purchasing simulation's synthetic seed
    loaded, as the operator does it: as the deployer, which owns the schema (Story
    2.4). Returns the database name."""
    from invoicing.adapters.purchasing_sim.seed import load_seed, seed

    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    try:
        with owner.begin() as connection:
            seed(connection, load_seed())
    finally:
        owner.dispose()
    return intake_database


def login_engine(server: PostgresServer, user: str, database: str) -> Engine:
    """The app's own engine (adapters/postgres/engine.py) signed in as `user`."""
    return postgres_engine(
        host=server.host,
        port=server.port,
        database=database,
        user=user,
        password=lambda: server.password,
        sslmode="disable",
        pool_size=2,
    )
