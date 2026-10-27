from dataclasses import replace

import pytest

from tests.integration import conftest as fixtures
from tests.integration.conftest import DatabaseCase

api, client, database = fixtures.api, fixtures.client, fixtures.database


@pytest.fixture(autouse=True)
def enable_deferred_extension(database: DatabaseCase) -> None:
    """Only the retained extension tests opt in to its routes."""
    database.settings = replace(database.settings, ai_features_enabled=True)
