import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def scene_data() -> Callable[[str], dict[str, Any]]:
    def load(kind: str) -> dict[str, Any]:
        path = Path(__file__).resolve().parents[2] / "fixtures" / f"{kind}.json"
        result: dict[str, Any] = json.loads(path.read_text())
        return result

    return load
