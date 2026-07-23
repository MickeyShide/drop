from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

from tests.integration.conftest import to_async_url


def test_alembic_migrations_run_successfully(postgres_container: PostgresContainer) -> None:
    async_url = to_async_url(postgres_container.get_connection_url())

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", async_url)

    command.upgrade(alembic_cfg, "head")
