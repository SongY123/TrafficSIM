"""FastAPI application factory for the Core Run gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from trafficverse.api.dependencies import ApiDependencies
from trafficverse.api.models import ErrorBody, ErrorDetail, ErrorResponse
from trafficverse.api.rest import build_router as build_rest_router
from trafficverse.api.websocket import build_router as build_websocket_router
from trafficverse.domain.enums import ErrorCode
from trafficverse.domain.errors import TrafficVerseError

_STATUS_BY_CODE = {
    ErrorCode.RESOURCE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.INVALID_STATE_TRANSITION: status.HTTP_409_CONFLICT,
    ErrorCode.RESOURCE_CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.MAP_ASSET_INVALID: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.SCENARIO_VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.COMPONENT_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _error_response(
    *,
    code: str,
    message: str,
    details: tuple[ErrorDetail, ...],
    status_code: int,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
            trace_id=str(uuid4()),
        )
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code)


def create_app(dependencies: ApiDependencies) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        yield
        if dependencies.shutdown is not None:
            await dependencies.shutdown()
        await dependencies.commands.close()
        await dependencies.maps.close()

    app = FastAPI(
        title="TrafficVerse API",
        version="2.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(TrafficVerseError)
    async def trafficverse_error(request: Request, error: TrafficVerseError) -> JSONResponse:
        del request
        details = tuple(
            ErrorDetail(path=path, reason=reason) for path, reason in error.details.items()
        )
        return _error_response(
            code=error.code.value,
            message=error.message,
            details=details,
            status_code=_STATUS_BY_CODE.get(error.code, status.HTTP_400_BAD_REQUEST),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, error: RequestValidationError) -> JSONResponse:
        del request
        details = tuple(
            ErrorDetail(
                path=".".join(str(part) for part in item["loc"]),
                reason=str(item["msg"]),
            )
            for item in error.errors()
        )
        return _error_response(
            code=ErrorCode.SCENARIO_VALIDATION_FAILED.value,
            message="request validation failed",
            details=details,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    app.include_router(build_rest_router(dependencies))
    app.include_router(build_websocket_router(dependencies))
    return app
