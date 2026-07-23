from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer


def test_alembic_migrations_run_successfully(postgres_container: PostgresContainer) -> None:
    sync_url = postgres_container.get_connection_url()
    if sync_url.startswith("postgresql://"):
        sync_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

    command.upgrade(alembic_cfg, "head")
