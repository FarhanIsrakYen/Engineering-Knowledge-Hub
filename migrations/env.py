from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Model imports register their tables on Base.metadata for Alembic autogeneration.
import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base

configuration = context.config

if configuration.config_file_name is not None:
    fileConfig(configuration.config_file_name)

configuration.set_main_option(
    "sqlalchemy.url",
    get_settings().database_url.replace("%", "%%"),
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=configuration.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        configuration.get_section(configuration.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_migrations_online())
