from collections.abc import Iterator
from sqlite3 import Connection as SQLiteConnection

from fastapi import Request
from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import DomainError


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "postgresql":
        parsed = parsed.update_query_dict(
            {
                "options": str(parsed.query.get("options", ""))
                + " -c statement_timeout=10000 -c lock_timeout=5000"
            }
        )
    engine = create_engine(
        parsed,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False}
        if url.startswith("sqlite")
        else {"connect_timeout": 5},
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection: SQLiteConnection, record: object) -> None:
            # Let SQLAlchemy own BEGIN; legacy sqlite3 savepoints can otherwise commit early.
            connection.isolation_level = None
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine, "begin")
        def sqlite_begin(connection: Connection) -> None:
            # Development-only SQLite serializes access; PostgreSQL has actual concurrent writes.
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] | None = request.app.state.session_factory
    if factory is None:
        raise DomainError(503, "DATABASE_UNAVAILABLE", "数据库尚未配置")
    with factory() as db:
        with db.begin():
            yield db
