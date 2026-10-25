from collections.abc import Callable
from threading import RLock
from time import perf_counter
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.agent.model import AgentFailure, ScenarioModel
from app.core.config import Settings
from app.models.entities import AgentRun
from app.schemas.provenance import FrozenModel


class NoArguments(FrozenModel):
    pass


class Runtime:
    def __init__(
        self,
        db: Session,
        run: AgentRun,
        model: ScenarioModel,
        settings: Settings,
        request_id: str,
        key: str,
    ) -> None:
        self.db, self.run, self.model, self.settings = db, run, model, settings
        self.request_id, self.key = request_id, key
        self.nodes = self.calls = 0
        self.lock = RLock()
        self.logs: list[dict[str, Any]] = []
        self.model_calls: list[dict[str, Any]] = []

    def charge(self) -> None:
        if self.calls >= self.settings.agent_max_calls:
            raise AgentFailure("AGENT_CALL_LIMIT")
        self.calls += 1

    def node(
        self, function: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def wrapped(state: dict[str, Any]) -> dict[str, Any]:
            with self.lock:
                if self.nodes >= self.settings.agent_max_nodes:
                    raise AgentFailure("AGENT_NODE_LIMIT")
                self.nodes += 1
                return function(state)

        return wrapped

    def call_model[T: BaseModel](self, operation: str, function: Callable[[], T]) -> T:
        for attempt in range(2):
            self.charge()
            start = perf_counter()
            entry: dict[str, Any] = {
                "operation": operation,
                "model": self.model.identity,
                "request_id": self.request_id,
                "status": "failed",
            }
            try:
                result = function()
                entry["status"] = "completed"
                return result
            except Exception as error:
                retryable = (
                    isinstance(error, (ValidationError, AgentFailure))
                    or "Timeout" in type(error).__name__
                )
                if not retryable or attempt == 1:
                    code = (
                        "LLM_INVALID_OUTPUT"
                        if isinstance(error, (ValidationError, AgentFailure))
                        else "LLM_UNAVAILABLE"
                    )
                    name = type(error).__name__
                    if "Authentication" in name:
                        code = "LLM_AUTHENTICATION_FAILED"
                    elif "PermissionDenied" in name:
                        code = "LLM_ACCESS_DENIED"
                    elif "RateLimit" in name:
                        code = "LLM_RATE_LIMITED"
                    elif "Timeout" in name:
                        code = "LLM_TIMEOUT"
                    raise AgentFailure(code) from None
            finally:
                entry["duration_ms"] = max(0, int((perf_counter() - start) * 1000))
                self.model_calls.append(entry)
        raise AgentFailure("LLM_UNAVAILABLE")

    def tool(
        self,
        name: str,
        function: Callable[[], dict[str, Any]],
        summary: dict[str, Any],
        version_id: str | None,
    ) -> dict[str, Any]:
        self.charge()
        start = perf_counter()
        log: dict[str, Any] = {
            "tool_name": name,
            "input_summary": summary,
            "scene_version_id": version_id,
            "status": "failed",
            "output_summary": {},
        }
        try:
            tool = StructuredTool.from_function(
                function,
                name=name,
                description=f"Before Open allowlisted tool: {name}",
                args_schema=NoArguments,
            )
            output: dict[str, Any] = tool.invoke({})
            log.update(status="completed", output_summary=output)
            return output
        finally:
            log["duration_ms"] = max(0, int((perf_counter() - start) * 1000))
            self.logs.append(log)
