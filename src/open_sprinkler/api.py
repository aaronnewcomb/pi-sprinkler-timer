"""FastAPI application for Pi Sprinkler Timer 3.0."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .auth import BrowserSessionManager
from .controller import ControllerStatus, SprinklerController, UnknownStationError
from .persistence import (
    Schedule,
    ScheduleNotFoundError,
    ScheduleStep,
    SQLiteRepository,
)
from .scheduler import ScheduleRunner

WEB_ROOT = Path(__file__).with_name("web")
SESSION_COOKIE = "open_sprinkler_session"
CSRF_COOKIE = "open_sprinkler_csrf"


class StationResponse(BaseModel):
    id: int
    name: str
    active: bool


class StatusResponse(BaseModel):
    stations: list[StationResponse]
    active_station_id: int | None
    active_run_id: int | None
    active_until: datetime | None


class StartStationRequest(BaseModel):
    duration_seconds: int = Field(ge=1)


class HealthResponse(BaseModel):
    status: str
    version: str


class ScheduleStepRequest(BaseModel):
    station_id: int = Field(ge=1)
    duration_seconds: int = Field(ge=1)


class ScheduleWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    start_time: time
    days_of_week: list[int] = Field(min_length=1, max_length=7)
    steps: list[ScheduleStepRequest] = Field(min_length=1)


class ScheduleResponse(BaseModel):
    id: int
    name: str
    enabled: bool
    start_time: time
    days_of_week: list[int]
    steps: list[ScheduleStepRequest]
    last_started_local_date: str | None


class RainDelayRequest(BaseModel):
    until: datetime


class RainDelayResponse(BaseModel):
    until: datetime | None
    active: bool


class RunRecordResponse(BaseModel):
    id: int
    source: str
    schedule_id: int | None
    station_id: int
    duration_seconds: int
    started_at: datetime
    ended_at: datetime | None
    outcome: str | None


class LoginRequest(BaseModel):
    token: str = Field(min_length=1)


class LoginResponse(BaseModel):
    authenticated: bool
    expires_at: datetime


def create_app(
    controller: SprinklerController,
    api_token: str,
    *,
    repository: SQLiteRepository | None = None,
    scheduler: ScheduleRunner | None = None,
    secure_cookies: bool = True,
) -> FastAPI:
    """Create an API app around one controller instance."""
    if not api_token:
        raise ValueError("API token must not be empty")
    session_manager = BrowserSessionManager(api_token)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            if repository is not None:
                repository.initialize()
            await controller.start()
            if scheduler is not None:
                await scheduler.start()
            yield
        finally:
            try:
                if scheduler is not None:
                    await scheduler.close()
                await controller.close()
            finally:
                if repository is not None:
                    repository.close()

    app = FastAPI(
        title="Pi Sprinkler Timer API",
        version=__version__,
        lifespan=lifespan,
    )
    app.mount(
        "/assets",
        StaticFiles(directory=WEB_ROOT / "assets"),
        name="assets",
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'; img-src 'self' data:; "
            "script-src 'self'; style-src 'self'; connect-src 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    async def require_authentication(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        csrf_header: Annotated[
            str | None, Header(alias="X-Open-Sprinkler-CSRF")
        ] = None,
    ) -> None:
        scheme, separator, supplied_token = (authorization or "").partition(" ")
        bearer_authenticated = (
            separator == " "
            and scheme.lower() == "bearer"
            and secrets.compare_digest(supplied_token, api_token)
        )
        if bearer_authenticated:
            return

        session_csrf = session_manager.verify(request.cookies.get(SESSION_COOKIE))
        if session_csrf is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid bearer token or browser session required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            csrf_header is None or not secrets.compare_digest(csrf_header, session_csrf)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Valid CSRF token required",
            )

    protected = [Depends(require_authentication)]

    @app.get("/", include_in_schema=False)
    async def web_interface() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(WEB_ROOT / "assets" / "favicon.svg")

    @app.post("/api/v1/auth/login", response_model=LoginResponse)
    async def login(request: LoginRequest, response: Response) -> LoginResponse:
        if not secrets.compare_digest(request.token, api_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API token",
            )
        browser_session = session_manager.issue()
        response.set_cookie(
            SESSION_COOKIE,
            browser_session.value,
            max_age=session_manager.lifetime_seconds,
            httponly=True,
            secure=secure_cookies,
            samesite="strict",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            browser_session.csrf_token,
            max_age=session_manager.lifetime_seconds,
            httponly=False,
            secure=secure_cookies,
            samesite="strict",
            path="/",
        )
        return LoginResponse(
            authenticated=True,
            expires_at=datetime.fromtimestamp(browser_session.expires_at_epoch, tz=UTC),
        )

    @app.post(
        "/api/v1/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=protected,
    )
    async def logout(response: Response) -> Response:
        response.delete_cookie(SESSION_COOKIE, path="/", secure=secure_cookies)
        response.delete_cookie(CSRF_COOKIE, path="/", secure=secure_cookies)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

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

    @app.get(
        "/api/v1/schedules",
        response_model=list[ScheduleResponse],
        dependencies=protected,
    )
    async def list_schedules() -> list[ScheduleResponse]:
        persistence = _require_repository(repository)
        return [_schedule_response(item) for item in persistence.list_schedules()]

    @app.post(
        "/api/v1/schedules",
        response_model=ScheduleResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=protected,
    )
    async def create_schedule(request: ScheduleWriteRequest) -> ScheduleResponse:
        persistence = _require_repository(repository)
        _validate_schedule_request(controller, request)
        try:
            schedule = persistence.create_schedule(
                name=request.name,
                enabled=request.enabled,
                start_time=request.start_time,
                days_of_week=tuple(request.days_of_week),
                steps=_schedule_steps(request),
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _schedule_response(schedule)

    @app.put(
        "/api/v1/schedules/{schedule_id}",
        response_model=ScheduleResponse,
        dependencies=protected,
    )
    async def update_schedule(
        schedule_id: int, request: ScheduleWriteRequest
    ) -> ScheduleResponse:
        persistence = _require_repository(repository)
        _validate_schedule_request(controller, request)
        try:
            schedule = persistence.update_schedule(
                schedule_id,
                name=request.name,
                enabled=request.enabled,
                start_time=request.start_time,
                days_of_week=tuple(request.days_of_week),
                steps=_schedule_steps(request),
            )
        except ScheduleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _schedule_response(schedule)

    @app.delete(
        "/api/v1/schedules/{schedule_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=protected,
    )
    async def delete_schedule(schedule_id: int) -> Response:
        persistence = _require_repository(repository)
        try:
            persistence.delete_schedule(schedule_id)
        except ScheduleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/rain-delay",
        response_model=RainDelayResponse,
        dependencies=protected,
    )
    async def get_rain_delay() -> RainDelayResponse:
        persistence = _require_repository(repository)
        until = persistence.get_rain_delay()
        return RainDelayResponse(
            until=until,
            active=until is not None and datetime.now(UTC) < until,
        )

    @app.put(
        "/api/v1/rain-delay",
        response_model=RainDelayResponse,
        dependencies=protected,
    )
    async def set_rain_delay(request: RainDelayRequest) -> RainDelayResponse:
        persistence = _require_repository(repository)
        if request.until.tzinfo is None:
            raise HTTPException(
                status_code=422, detail="Rain delay time must include a timezone"
            )
        until = request.until.astimezone(UTC)
        if until <= datetime.now(UTC):
            raise HTTPException(
                status_code=422, detail="Rain delay time must be in the future"
            )
        persistence.set_rain_delay(until)
        return RainDelayResponse(until=until, active=True)

    @app.delete(
        "/api/v1/rain-delay",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=protected,
    )
    async def clear_rain_delay() -> Response:
        _require_repository(repository).set_rain_delay(None)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/history",
        response_model=list[RunRecordResponse],
        dependencies=protected,
    )
    async def get_history(
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[RunRecordResponse]:
        persistence = _require_repository(repository)
        return [
            RunRecordResponse(
                id=item.id,
                source=item.source,
                schedule_id=item.schedule_id,
                station_id=item.station_id,
                duration_seconds=item.duration_seconds,
                started_at=item.started_at,
                ended_at=item.ended_at,
                outcome=item.outcome,
            )
            for item in persistence.list_runs(limit=limit)
        ]

    return app


def _status_response(controller_status: ControllerStatus) -> StatusResponse:
    return StatusResponse(
        stations=[
            StationResponse(id=station.id, name=station.name, active=station.active)
            for station in controller_status.stations
        ],
        active_station_id=controller_status.active_station_id,
        active_run_id=controller_status.active_run_id,
        active_until=controller_status.active_until,
    )


def _require_repository(
    repository: SQLiteRepository | None,
) -> SQLiteRepository:
    if repository is None:
        raise HTTPException(status_code=503, detail="Persistence is not configured")
    return repository


def _validate_schedule_request(
    controller: SprinklerController, request: ScheduleWriteRequest
) -> None:
    invalid_days = [day for day in request.days_of_week if day < 0 or day > 6]
    if invalid_days:
        raise HTTPException(
            status_code=422, detail="Schedule days must contain values from 0 through 6"
        )
    unknown_stations = sorted(
        {step.station_id for step in request.steps} - controller.station_ids
    )
    if unknown_stations:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown station IDs: {unknown_stations}",
        )
    too_long = [
        step.station_id
        for step in request.steps
        if step.duration_seconds > controller.max_duration_seconds
    ]
    if too_long:
        raise HTTPException(
            status_code=422,
            detail=(
                "Station duration exceeds the controller maximum for station IDs: "
                f"{too_long}"
            ),
        )


def _schedule_steps(
    request: ScheduleWriteRequest,
) -> tuple[ScheduleStep, ...]:
    return tuple(
        ScheduleStep(
            station_id=step.station_id,
            duration_seconds=step.duration_seconds,
        )
        for step in request.steps
    )


def _schedule_response(schedule: Schedule) -> ScheduleResponse:
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        enabled=schedule.enabled,
        start_time=schedule.start_time,
        days_of_week=list(schedule.days_of_week),
        steps=[
            ScheduleStepRequest(
                station_id=step.station_id,
                duration_seconds=step.duration_seconds,
            )
            for step in schedule.steps
        ],
        last_started_local_date=(
            schedule.last_started_local_date.isoformat()
            if schedule.last_started_local_date is not None
            else None
        ),
    )
