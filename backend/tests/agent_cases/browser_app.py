"""Explicit test entry point. Never used by app.main or a production setting."""

import os
from dataclasses import replace

from app.core.config import Settings
from app.main import create_app

if os.environ.get("BEFORE_OPEN_AGENT_TEST") != "1":
    raise RuntimeError("This server entry point is for isolated browser tests only")

app = create_app(
    replace(
        Settings.load(),
        llm_enabled=True,
        llm_key="scripted-only-not-a-key",
        llm_model="scripted-test",
    )
)


def forbidden_model(actor: str) -> None:
    raise AssertionError("Deferred browser flow must not request a model")


app.state.agent_model_factory = forbidden_model
