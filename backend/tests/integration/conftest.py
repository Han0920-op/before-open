from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command
from app.core.config import Settings
from app.core.database import make_engine
from app.main import create_app


@dataclass
class DatabaseCase:
    engine: Engine
    settings: Settings

    def migrate(self, revision: str, downgrade: bool = False) -> None:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            if downgrade:
                command.downgrade(config, revision)
            else:
                command.upgrade(config, revision)


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[DatabaseCase]:
    admin: Engine | None = None
    schema = "test_" + uuid4().hex
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 'test.db'}"
    else:
        base_url = Settings.load().database_url
        if not base_url or not base_url.startswith("postgresql"):
            pytest.fail("PostgreSQL integration tests require the documented local database")
        admin = make_engine(base_url)
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        url = (
            make_url(base_url)
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )
    settings = Settings(
        database_url=url,
        cookie_secure=False,
        rate_limit=1000,
        allowed_origins=("https://frontend.example",),
    )
    case = DatabaseCase(make_engine(url), settings)
    try:
        case.migrate("head")
        yield case
    finally:
        case.engine.dispose()
        if admin:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
            admin.dispose()


@pytest.fixture
def api(database: DatabaseCase) -> Iterator[FastAPI]:
    app = create_app(database.settings)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(api: FastAPI) -> Iterator[TestClient]:
    with TestClient(api) as client:
        session = client.get("/api/v1/session")
        assert session.status_code == 200
        client.headers["X-CSRF-Token"] = session.json()["data"]["csrf_token"]
        yield client
