"""FastAPI application for Pi Sprinkler Timer 3.0."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

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
from .controller_settings import ControllerSettingsManager
from .persistence import (
    Schedule,
    ScheduleNotFoundError,
    ScheduleStep,
    SQLiteRepository,
)
from .scheduler import (
    TEST_STEP_SECONDS,
    ScheduleRunner,
    ScheduleTestBusyError,
    ScheduleTestStatus,
)
from .weather import (
    WeatherAutomation,
    WeatherProviderError,
    WeatherSettings,
    WeatherStatus,
)

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
    active_source: str | None
    active_schedule_id: int | None


class ControllerStationSettings(BaseModel):
    id: int
    name: str = Field(min_length=1, max_length=100)
    gpio_pin: int = Field(ge=0, le=27)


class ControllerSettingsRequest(BaseModel):
    stations: list[ControllerStationSettings] = Field(min_length=1)
    timezone: str = Field(min_length=1, max_length=100)
    max_duration_minutes: int = Field(ge=1, le=1440)
    stop_action: str


class ControllerSettingsResponse(ControllerSettingsRequest):
    restart_required: bool


class ConfiguredStopResponse(BaseModel):
    action: str
    hold_until: datetime | None
    status: StatusResponse


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


class ScheduleTestRequest(BaseModel):
    schedule_ids: list[int] = Field(min_length=1)


class ScheduleTestResponse(BaseModel):
    running: bool
    schedule_ids: list[int]
    current_schedule_id: int | None
    current_station_id: int | None
    completed_steps: int
    total_steps: int
    step_duration_seconds: int
    outcome: str | None
    error: str | None


class RainDelayRequest(BaseModel):
    until: datetime


class RainDelayResponse(BaseModel):
    until: datetime | None
    active: bool
    manual_until: datetime | None
    weather_until: datetime | None
    sources: list[str]


class WeatherSettingsRequest(BaseModel):
    enabled: bool
    postal_code: str = Field(default="", max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    precipitation_threshold_inches: float = Field(default=0.25, ge=0.01, le=10)
    delay_hours_after_precipitation: int = Field(default=24, ge=1, le=336)


class WeatherSettingsResponse(BaseModel):
    enabled: bool
    postal_code: str
    latitude: float | None
    longitude: float | None
    location_name: str
    precipitation_threshold_inches: float
    delay_hours_after_precipitation: int


class DailyWeatherResponse(BaseModel):
    date: str
    weather_code: int
    temperature_max_f: float
    temperature_min_f: float
    precipitation_inches: float
    precipitation_probability: int


class WeatherResponse(BaseModel):
    settings: WeatherSettingsResponse
    available: bool
    observed_at: datetime | None
    temperature_f: float | None
    weather_code: int | None
    precipitation_inches: float | None
    daily: list[DailyWeatherResponse]
    evaluated_precipitation_inches: float | None
    automatic_hold_until: datetime | None
    last_checked_at: datetime | None
    error: str | None


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
    weather: WeatherAutomation | None = None,
    settings_manager: ControllerSettingsManager | None = None,
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
            if weather is not None:
                await weather.start()
            if scheduler is not None:
                await scheduler.start()
            yield
        finally:
            try:
                if scheduler is not None:
                    await scheduler.close()
                if weather is not None:
                    await weather.close()
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

    @app.post(
        "/api/v1/actions/configured-stop",
        response_model=ConfiguredStopResponse,
        dependencies=protected,
    )
    async def configured_stop() -> ConfiguredStopResponse:
        manager = _require_settings_manager(settings_manager)
        persistence = _require_repository(repository)
        current = await controller.status()
        action = manager.settings.stop_action
        hold_until = None
        if current.active_source == "schedule-test" and scheduler is not None:
            action = "schedule-test"
            await scheduler.stop_test()
            current = await controller.status()
        elif action == "station" and current.active_station_id is not None:
            current = await controller.stop_station(
                current.active_station_id, outcome="skipped"
            )
        else:
            current = await controller.stop_all()
        if action == "day":
            local_now = datetime.now(UTC).astimezone(
                ZoneInfo(manager.settings.timezone)
            )
            hold_until = datetime.combine(
                local_now.date() + timedelta(days=1),
                time.min,
                tzinfo=local_now.tzinfo,
            ).astimezone(UTC)
            existing = persistence.get_manual_rain_delay()
            hold_until = max(
                item for item in (existing, hold_until) if item is not None
            )
            persistence.set_manual_rain_delay(hold_until)
        return ConfiguredStopResponse(
            action=action,
            hold_until=hold_until,
            status=_status_response(current),
        )

    @app.get(
        "/api/v1/controller-settings",
        response_model=ControllerSettingsResponse,
        dependencies=protected,
    )
    async def get_controller_settings() -> ControllerSettingsResponse:
        return _controller_settings_response(
            _require_settings_manager(settings_manager)
        )

    @app.put(
        "/api/v1/controller-settings",
        response_model=ControllerSettingsResponse,
        dependencies=protected,
    )
    async def update_controller_settings(
        request: ControllerSettingsRequest,
    ) -> ControllerSettingsResponse:
        manager = _require_settings_manager(settings_manager)
        if [station.id for station in request.stations] != list(
            range(1, len(request.stations) + 1)
        ):
            raise HTTPException(
                status_code=422, detail="Station IDs must be consecutive from 1"
            )
        try:
            await manager.configure(
                station_names=[station.name for station in request.stations],
                gpio_pins=[station.gpio_pin for station in request.stations],
                timezone=request.timezone,
                max_duration_seconds=request.max_duration_minutes * 60,
                stop_action=request.stop_action,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _controller_settings_response(manager)

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
        "/api/v1/schedule-test",
        response_model=ScheduleTestResponse,
        dependencies=protected,
    )
    async def get_schedule_test() -> ScheduleTestResponse:
        return _schedule_test_response(_require_scheduler(scheduler).test_status)

    @app.post(
        "/api/v1/schedule-test",
        response_model=ScheduleTestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=protected,
    )
    async def start_schedule_test(
        request: ScheduleTestRequest,
    ) -> ScheduleTestResponse:
        runner = _require_scheduler(scheduler)
        try:
            test_status = await runner.start_test(request.schedule_ids)
        except ScheduleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ScheduleTestBusyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _schedule_test_response(test_status)

    @app.delete(
        "/api/v1/schedule-test",
        response_model=ScheduleTestResponse,
        dependencies=protected,
    )
    async def stop_schedule_test() -> ScheduleTestResponse:
        return _schedule_test_response(await _require_scheduler(scheduler).stop_test())

    @app.get(
        "/api/v1/rain-delay",
        response_model=RainDelayResponse,
        dependencies=protected,
    )
    async def get_rain_delay() -> RainDelayResponse:
        persistence = _require_repository(repository)
        return _rain_delay_response(persistence)

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
        return _rain_delay_response(persistence)

    @app.delete(
        "/api/v1/rain-delay",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=protected,
    )
    async def clear_rain_delay() -> Response:
        _require_repository(repository).set_manual_rain_delay(None)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/weather",
        response_model=WeatherResponse,
        dependencies=protected,
    )
    async def get_weather() -> WeatherResponse:
        return _weather_response(_require_weather(weather).status())

    @app.put(
        "/api/v1/weather/settings",
        response_model=WeatherResponse,
        dependencies=protected,
    )
    async def update_weather_settings(
        request: WeatherSettingsRequest,
    ) -> WeatherResponse:
        service = _require_weather(weather)
        try:
            weather_status = await service.configure(
                WeatherSettings(
                    enabled=request.enabled,
                    postal_code=request.postal_code,
                    latitude=request.latitude,
                    longitude=request.longitude,
                    precipitation_threshold_inches=(
                        request.precipitation_threshold_inches
                    ),
                    delay_hours_after_precipitation=(
                        request.delay_hours_after_precipitation
                    ),
                )
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except WeatherProviderError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return _weather_response(weather_status)

    @app.post(
        "/api/v1/weather/refresh",
        response_model=WeatherResponse,
        dependencies=protected,
    )
    async def refresh_weather() -> WeatherResponse:
        return _weather_response(await _require_weather(weather).refresh())

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
        active_source=controller_status.active_source,
        active_schedule_id=controller_status.active_schedule_id,
    )


def _require_repository(
    repository: SQLiteRepository | None,
) -> SQLiteRepository:
    if repository is None:
        raise HTTPException(status_code=503, detail="Persistence is not configured")
    return repository


def _require_weather(weather: WeatherAutomation | None) -> WeatherAutomation:
    if weather is None:
        raise HTTPException(
            status_code=503, detail="Weather automation is not configured"
        )
    return weather


def _require_scheduler(scheduler: ScheduleRunner | None) -> ScheduleRunner:
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler is not configured")
    return scheduler


def _require_settings_manager(
    manager: ControllerSettingsManager | None,
) -> ControllerSettingsManager:
    if manager is None:
        raise HTTPException(
            status_code=503, detail="Controller settings are not configured"
        )
    return manager


def _controller_settings_response(
    manager: ControllerSettingsManager,
) -> ControllerSettingsResponse:
    settings = manager.settings
    return ControllerSettingsResponse(
        stations=[
            ControllerStationSettings(
                id=station.id, name=station.name, gpio_pin=station.pin
            )
            for station in settings.stations
        ],
        timezone=settings.timezone,
        max_duration_minutes=settings.max_duration_seconds // 60,
        stop_action=settings.stop_action,
        restart_required=manager.restart_required,
    )


def _rain_delay_response(repository: SQLiteRepository) -> RainDelayResponse:
    now = datetime.now(UTC)
    repository.clear_expired_rain_delays(now)
    manual_until = repository.get_manual_rain_delay()
    weather_until = repository.get_weather_rain_delay()
    sources = []
    if manual_until is not None and manual_until > now:
        sources.append("manual")
    if weather_until is not None and weather_until > now:
        sources.append("weather")
    until = max(
        (item for item in (manual_until, weather_until) if item is not None),
        default=None,
    )
    return RainDelayResponse(
        until=until,
        active=bool(sources),
        manual_until=manual_until,
        weather_until=weather_until,
        sources=sources,
    )


def _weather_response(weather_status: WeatherStatus) -> WeatherResponse:
    settings = weather_status.settings
    snapshot = weather_status.snapshot
    return WeatherResponse(
        settings=WeatherSettingsResponse(
            enabled=settings.enabled,
            postal_code=settings.postal_code,
            latitude=settings.latitude,
            longitude=settings.longitude,
            location_name=settings.location_name,
            precipitation_threshold_inches=(settings.precipitation_threshold_inches),
            delay_hours_after_precipitation=(settings.delay_hours_after_precipitation),
        ),
        available=snapshot is not None,
        observed_at=snapshot.observed_at if snapshot is not None else None,
        temperature_f=snapshot.temperature_f if snapshot is not None else None,
        weather_code=snapshot.weather_code if snapshot is not None else None,
        precipitation_inches=(
            snapshot.precipitation_inches if snapshot is not None else None
        ),
        daily=[
            DailyWeatherResponse(
                date=item.day.isoformat(),
                weather_code=item.weather_code,
                temperature_max_f=item.temperature_max_f,
                temperature_min_f=item.temperature_min_f,
                precipitation_inches=item.precipitation_inches,
                precipitation_probability=item.precipitation_probability,
            )
            for item in (snapshot.daily if snapshot is not None else ())
        ],
        evaluated_precipitation_inches=(weather_status.evaluated_precipitation_inches),
        automatic_hold_until=weather_status.automatic_hold_until,
        last_checked_at=weather_status.last_checked_at,
        error=weather_status.error,
    )


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


def _schedule_test_response(test_status: ScheduleTestStatus) -> ScheduleTestResponse:
    return ScheduleTestResponse(
        running=test_status.running,
        schedule_ids=list(test_status.schedule_ids),
        current_schedule_id=test_status.current_schedule_id,
        current_station_id=test_status.current_station_id,
        completed_steps=test_status.completed_steps,
        total_steps=test_status.total_steps,
        step_duration_seconds=TEST_STEP_SECONDS,
        outcome=test_status.outcome,
        error=test_status.error,
    )
