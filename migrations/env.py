"""Run migrations with an explicit URL or caller-owned transaction."""
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
import models
from models.base import Base

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
    context.configure(connection=connection, target_metadata=target_metadata)
    migration = context.get_context()
    operation = migration.opts.get('fn')
    if operation and operation.__name__ == 'downgrade':
        # Historical revisions assume tables predating Alembic. Replaying those
        # downgrades cannot safely undo a fully initialized application schema.
        forbidden = {'f837b871ec81', '7382d258d28d', 'c00a640ed5c7'}
        steps = operation(migration.get_current_heads(), migration)
        if any(not step.to_revisions or forbidden.intersection(step.to_revisions) for step in steps):
            raise ValueError('Downgrade below the frozen baseline 0a029e480f8f is unsupported')
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    configure_url()
    context.configure(url=config.get_main_option('sqlalchemy.url'), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get('connection') is not None:
    run_on_connection(config.attributes['connection'])
else:
    configure_url()
    engine = engine_from_config(config.get_section(config.config_ini_section, {}),
                                prefix='sqlalchemy.', poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            run_on_connection(connection)
    finally:
        engine.dispose()
