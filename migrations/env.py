"""Run migrations with an explicit URL or caller-owned transaction."""
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
import models
from models.base import Base
from migrations.autogenerate import migration_options

config = context.config
target_metadata = Base.metadata
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def configure_url():
    url = config.attributes.get('database_url') or os.environ.get('DATABASE_URL')
    if not url:
        raise ValueError('DATABASE_URL or an explicit migration database_url is required')
    config.set_main_option('sqlalchemy.url', url.replace('%', '%%'))


def run_on_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata,
                      **migration_options(connection))
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    configure_url()
    context.configure(url=config.get_main_option('sqlalchemy.url'), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'},
                      **migration_options())
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get('connection') is not None:
    run_on_connection(config.attributes['connection'])
else:
    configure_url()
    engine = engine_from_config(config.get_section(config.config_ini_section, {}),
                                prefix='sqlalchemy.', poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            run_on_connection(connection)
    finally:
        engine.dispose()
