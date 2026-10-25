"""Explicit test entry point. Never used by app.main or a production setting."""

import os

from app.main import create_app
from tests.agent_cases.test_workflow import ScriptModel

if os.environ.get("BEFORE_OPEN_AGENT_TEST") != "1":
    raise RuntimeError("This server entry point is for isolated browser tests only")

app = create_app()
app.state.agent_model_factory = lambda actor: ScriptModel()
