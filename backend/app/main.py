"""Application factory: health stays available even without database configuration."""

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from app.api.routes import router
from app.core.config import Settings
from app.core.database import make_engine
from app.core.errors import DomainError
from app.schemas.api import ErrorEnvelope


class HealthResponse(BaseModel):
    status: Literal["ok"]
    request_id: UUID


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "request_id": request.state.request_id,
            "error": {"code": code, "message": message},
        },
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    app = FastAPI(
        title="未开张 Before Open",
        version="0.3.0",
        responses={
            status: {"model": ErrorEnvelope}
            for status in (400, 401, 403, 404, 408, 409, 413, 422, 429, 500, 503)
        },
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url) if settings.database_url else None
    app.state.session_factory = (
        sessionmaker(app.state.engine, expire_on_commit=False)
        if (app.state.engine is not None)
        else None
    )
    buckets: OrderedDict[str, tuple[float, int]] = OrderedDict()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        return error_response(request, error.status, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(
            request, 422, "INVALID_INPUT", "输入格式不符合接口契约，请检查字段与类型"
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(request, error.status_code, "HTTP_ERROR", "请求路径或方法不受支持")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "数据库操作失败，事务已回滚")

    @app.middleware("http")
    async def guard(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        response: Response
        try:
            key = request.client.host if request.client else "local"
            timestamp = time.monotonic()
            start, count = buckets.get(key, (timestamp, 0))
            if timestamp - start >= 60:
                start, count = timestamp, 0
            buckets[key] = (start, count + 1)
            buckets.move_to_end(key)
            if len(buckets) > 10000:
                buckets.popitem(last=False)
            if count >= settings.rate_limit:
                response = error_response(request, 429, "RATE_LIMITED", "请求过于频繁，请稍后再试")
            elif request.method not in {"GET", "HEAD", "OPTIONS"} and (
                request.headers.get("origin") is not None
                and request.headers["origin"]
                not in (*settings.allowed_origins, str(request.base_url).rstrip("/"))
            ):
                response = error_response(
                    request, 403, "ORIGIN_FORBIDDEN", "不允许这个来源的写请求"
                )
            else:
                body = bytearray()
                oversized = False
                async with asyncio.timeout(settings.body_timeout):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > settings.body_limit:
                            oversized = True
                            break
                        body.extend(chunk)
                if oversized:
                    response = error_response(request, 413, "BODY_TOO_LARGE", "请求内容过大")
                else:
                    request._body = bytes(body)
                    response = await call_next(request)
        except TimeoutError:
            response = error_response(request, 408, "REQUEST_TIMEOUT", "读取请求超时，请重新提交")
        except Exception as error:
            # Do not expose SQL, bound values, credentials or user text in errors.
            logging.getLogger("before_open").warning(
                "request_failed request_id=%s error_type=%s",
                request.state.request_id,
                type(error).__name__,
            )
            response = error_response(request, 500, "INTERNAL_ERROR", "请求未完成，请稍后再试")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        return HealthResponse(status="ok", request_id=UUID(request.state.request_id))

    app.include_router(router)
    return app


app = create_app()
