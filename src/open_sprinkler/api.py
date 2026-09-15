"""FastAPI application for Open Sprinkler 3.0."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from . import __version__
from .controller import ControllerStatus, SprinklerController, UnknownStationError


class StationResponse(BaseModel):
    id: int
    name: str
    active: bool


class StatusResponse(BaseModel):
    stations: list[StationResponse]
    active_station_id: int | None
    active_until: datetime | None


class StartStationRequest(BaseModel):
    duration_seconds: int = Field(ge=1)


class HealthResponse(BaseModel):
    status: str
    version: str


def create_app(controller: SprinklerController, api_token: str) -> FastAPI:
    """Create an API app around one controller instance."""
    if not api_token:
        raise ValueError("API token must not be empty")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await controller.start()
        try:
            yield
        finally:
            await controller.close()

    app = FastAPI(
        title="Open Sprinkler API",
        version=__version__,
        lifespan=lifespan,
    )

    async def require_api_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        scheme, separator, supplied_token = (authorization or "").partition(" ")
        authenticated = (
            separator == " "
            and scheme.lower() == "bearer"
            and secrets.compare_digest(supplied_token, api_token)
        )
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    protected = [Depends(require_api_token)]

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok" if controller.is_running else "starting",
            version=__version__,
        )

    @app.get(
        "/api/v1/status",
        response_model=StatusResponse,
        dependencies=protected,
    )
    async def get_status() -> StatusResponse:
        return _status_response(await controller.status())

    @app.post(
        "/api/v1/stations/{station_id}/start",
        response_model=StatusResponse,
        dependencies=protected,
    )
    async def start_station(
        station_id: int, request: StartStationRequest
    ) -> StatusResponse:
        try:
            controller_status = await controller.start_station(
                station_id, request.duration_seconds
            )
        except UnknownStationError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _status_response(controller_status)

    @app.post(
        "/api/v1/stations/{station_id}/stop",
        response_model=StatusResponse,
        dependencies=protected,
    )
    async def stop_station(station_id: int) -> StatusResponse:
        try:
            controller_status = await controller.stop_station(station_id)
        except UnknownStationError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return _status_response(controller_status)

    @app.post(
        "/api/v1/actions/stop-all",
        response_model=StatusResponse,
        dependencies=protected,
    )
    async def stop_all() -> StatusResponse:
        return _status_response(await controller.stop_all())

    return app


def _status_response(controller_status: ControllerStatus) -> StatusResponse:
    return StatusResponse(
        stations=[
            StationResponse(id=station.id, name=station.name, active=station.active)
            for station in controller_status.stations
        ],
        active_station_id=controller_status.active_station_id,
        active_until=controller_status.active_until,
    )
