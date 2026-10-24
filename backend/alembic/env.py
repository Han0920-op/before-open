from sqlalchemy import Connection

from alembic import context
from app.core.config import Settings
from app.core.database import make_engine
from app.models.entities import Base

config = context.config
target_metadata = Base.metadata


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Use an authenticated database connection for migrations")
elif config.attributes.get("connection") is not None:
    migrate(config.attributes["connection"])
else:
    url = Settings.load().database_url
    if not url:
        raise RuntimeError("Configure DATABASE_URL or start the documented local database")
    engine = make_engine(url)
    with engine.connect() as connection:
        migrate(connection)
    engine.dispose()
