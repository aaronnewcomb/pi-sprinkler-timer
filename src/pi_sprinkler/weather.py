"""Optional Open-Meteo weather status and precipitation hold automation."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .persistence import SQLiteRepository

LOGGER = logging.getLogger(__name__)
SETTINGS_KEY = "weather_settings_json"


class WeatherProviderError(RuntimeError):
    """Raised when location or forecast data cannot be retrieved or parsed."""


@dataclass(frozen=True, slots=True)
class WeatherSettings:
    enabled: bool = False
    postal_code: str = ""
    latitude: float | None = None
    longitude: float | None = None
    location_name: str = ""
    precipitation_threshold_inches: float = 0.25
    delay_hours_after_precipitation: int = 24

    def validate(self) -> None:
        if not 0.01 <= self.precipitation_threshold_inches <= 10:
            raise ValueError(
                "Precipitation threshold must be between 0.01 and 10 inches"
            )
        if not 1 <= self.delay_hours_after_precipitation <= 336:
            raise ValueError("Weather delay must be between 1 and 336 hours")
        if (
            self.enabled
            and (self.latitude is None or self.longitude is None)
            and not self.postal_code.strip()
        ):
            raise ValueError("Enable weather using a postal code or coordinates")
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180")


@dataclass(frozen=True, slots=True)
class ResolvedLocation:
    latitude: float
    longitude: float
    name: str


@dataclass(frozen=True, slots=True)
class HourlyPrecipitation:
    at: datetime
    inches: float


@dataclass(frozen=True, slots=True)
class DailyForecast:
    day: date
    weather_code: int
    temperature_max_f: float
    temperature_min_f: float
    precipitation_inches: float
    precipitation_probability: int


@dataclass(frozen=True, slots=True)
class WeatherSnapshot:
    observed_at: datetime
    temperature_f: float
    weather_code: int
    precipitation_inches: float
    hourly_precipitation: tuple[HourlyPrecipitation, ...]
    daily: tuple[DailyForecast, ...]


@dataclass(frozen=True, slots=True)
class WeatherStatus:
    settings: WeatherSettings
    snapshot: WeatherSnapshot | None
    automatic_hold_until: datetime | None
    evaluated_precipitation_inches: float | None
    last_checked_at: datetime | None
    error: str | None


class WeatherProvider(Protocol):
    async def resolve_location(self, postal_code: str) -> ResolvedLocation: ...

    async def forecast(self, latitude: float, longitude: float) -> WeatherSnapshot: ...


class OpenMeteoProvider:
    """Fetch Open-Meteo geocoding and best-match forecast data."""

    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, *, timeout_seconds: float = 10) -> None:
        self._timeout_seconds = timeout_seconds

    async def resolve_location(self, postal_code: str) -> ResolvedLocation:
        query = postal_code.strip()
        if not query:
            raise ValueError("Postal code must not be empty")
        payload = await asyncio.to_thread(
            self._get_json,
            self.GEOCODING_URL,
            {"name": query, "count": 1, "language": "en", "format": "json"},
        )
        results = payload.get("results") or []
        if not results:
            raise WeatherProviderError(f"No location found for {query}")
        result = results[0]
        name_parts = [
            result.get("name"),
            result.get("admin1"),
            result.get("country_code"),
        ]
        return ResolvedLocation(
            latitude=float(result["latitude"]),
            longitude=float(result["longitude"]),
            name=", ".join(str(part) for part in name_parts if part),
        )

    async def forecast(self, latitude: float, longitude: float) -> WeatherSnapshot:
        payload = await asyncio.to_thread(
            self._get_json,
            self.FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code,precipitation",
                "hourly": "precipitation,precipitation_probability,weather_code",
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_sum,precipitation_probability_max"
                ),
                "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
                "past_hours": 24,
                "forecast_hours": 48,
                "forecast_days": 4,
                "timezone": "auto",
            },
        )
        try:
            timezone = ZoneInfo(payload["timezone"])
            current = payload["current"]
            hourly = payload["hourly"]
            daily = payload["daily"]
            hourly_values = tuple(
                HourlyPrecipitation(
                    at=_local_datetime(at, timezone),
                    inches=float(inches),
                )
                for at, inches in zip(
                    hourly["time"], hourly["precipitation"], strict=True
                )
            )
            daily_values = tuple(
                DailyForecast(
                    day=date.fromisoformat(day),
                    weather_code=int(code),
                    temperature_max_f=float(high),
                    temperature_min_f=float(low),
                    precipitation_inches=float(precipitation),
                    precipitation_probability=int(probability or 0),
                )
                for day, code, high, low, precipitation, probability in zip(
                    daily["time"],
                    daily["weather_code"],
                    daily["temperature_2m_max"],
                    daily["temperature_2m_min"],
                    daily["precipitation_sum"],
                    daily["precipitation_probability_max"],
                    strict=True,
                )
            )
            if not daily_values:
                raise ValueError("Daily forecast is empty")
            return WeatherSnapshot(
                observed_at=_local_datetime(current["time"], timezone),
                temperature_f=float(current["temperature_2m"]),
                weather_code=int(current["weather_code"]),
                precipitation_inches=float(current["precipitation"]),
                hourly_precipitation=hourly_values,
                daily=daily_values,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise WeatherProviderError(
                "Open-Meteo returned incomplete weather data"
            ) from error

    def _get_json(self, base_url: str, parameters: dict[str, object]) -> dict[str, Any]:
        request = Request(
            f"{base_url}?{urlencode(parameters)}",
            headers={"User-Agent": "Pi-Sprinkler-Timer/3.0"},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.load(response)
        except Exception as error:
            raise WeatherProviderError("Unable to contact Open-Meteo") from error
        if not isinstance(payload, dict) or payload.get("error"):
            reason = (
                payload.get("reason", "Invalid weather response")
                if isinstance(payload, dict)
                else "Invalid weather response"
            )
            raise WeatherProviderError(str(reason))
        return payload


class WeatherAutomation:
    """Persist weather settings and maintain an independent automatic hold."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        provider: WeatherProvider | None = None,
        poll_seconds: int = 900,
    ) -> None:
        if poll_seconds < 60:
            raise ValueError("Weather poll interval must be at least 60 seconds")
        self._repository = repository
        self._provider = provider or OpenMeteoProvider()
        self._poll_seconds = poll_seconds
        self._settings = WeatherSettings()
        self._snapshot: WeatherSnapshot | None = None
        self._evaluated_precipitation_inches: float | None = None
        self._last_checked_at: datetime | None = None
        self._error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._settings = self._load_settings()
        if self._settings.enabled:
            await self.refresh()
        self._task = asyncio.create_task(
            self._run_loop(), name="pi-sprinkler-weather"
        )

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def configure(self, settings: WeatherSettings) -> WeatherStatus:
        settings.validate()
        if settings.enabled and settings.postal_code.strip():
            location = await self._provider.resolve_location(settings.postal_code)
            settings = WeatherSettings(
                enabled=True,
                postal_code=settings.postal_code.strip(),
                latitude=location.latitude,
                longitude=location.longitude,
                location_name=location.name,
                precipitation_threshold_inches=settings.precipitation_threshold_inches,
                delay_hours_after_precipitation=settings.delay_hours_after_precipitation,
            )
        elif settings.enabled:
            settings = WeatherSettings(
                enabled=True,
                postal_code="",
                latitude=settings.latitude,
                longitude=settings.longitude,
                location_name=settings.location_name.strip()
                or _coordinate_name(settings),
                precipitation_threshold_inches=settings.precipitation_threshold_inches,
                delay_hours_after_precipitation=settings.delay_hours_after_precipitation,
            )
        async with self._lock:
            self._settings = settings
            self._repository.set_controller_state(
                SETTINGS_KEY, json.dumps(asdict(settings), separators=(",", ":"))
            )
            self._repository.set_weather_rain_delay(None)
            self._snapshot = None
            self._evaluated_precipitation_inches = None
            self._error = None
        if settings.enabled:
            await self.refresh()
        return self.status()

    async def refresh(self) -> WeatherStatus:
        async with self._lock:
            if not self._settings.enabled:
                return self.status()
            assert self._settings.latitude is not None
            assert self._settings.longitude is not None
            checked_at = datetime.now(UTC)
            try:
                snapshot = await self._provider.forecast(
                    self._settings.latitude, self._settings.longitude
                )
                precipitation, hold_until = _evaluate_automatic_hold(
                    snapshot,
                    checked_at,
                    threshold_inches=self._settings.precipitation_threshold_inches,
                    delay_hours=self._settings.delay_hours_after_precipitation,
                )
                self._snapshot = snapshot
                self._evaluated_precipitation_inches = precipitation
                existing = self._repository.get_weather_rain_delay()
                if hold_until is not None and (
                    existing is None or hold_until > existing
                ):
                    self._repository.set_weather_rain_delay(hold_until)
                self._repository.clear_expired_rain_delays(checked_at)
                self._error = None
            except Exception as error:  # noqa: BLE001
                self._error = str(error)
                LOGGER.warning("Weather refresh failed: %s", error)
            self._last_checked_at = checked_at
            return self.status()

    def status(self) -> WeatherStatus:
        return WeatherStatus(
            settings=self._settings,
            snapshot=self._snapshot,
            automatic_hold_until=self._repository.get_weather_rain_delay(),
            evaluated_precipitation_inches=self._evaluated_precipitation_inches,
            last_checked_at=self._last_checked_at,
            error=self._error,
        )

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_seconds)
            if self._settings.enabled:
                await self.refresh()

    def _load_settings(self) -> WeatherSettings:
        raw = self._repository.get_controller_state(SETTINGS_KEY)
        if raw is None:
            return WeatherSettings()
        try:
            settings = WeatherSettings(**json.loads(raw))
            settings.validate()
            return settings
        except (TypeError, ValueError, json.JSONDecodeError):
            LOGGER.exception("Ignoring invalid persisted weather settings")
            return WeatherSettings()


def _evaluate_automatic_hold(
    snapshot: WeatherSnapshot,
    now: datetime,
    *,
    threshold_inches: float,
    delay_hours: int,
) -> tuple[float, datetime | None]:
    window_start = now - timedelta(hours=24)
    window_end = now + timedelta(hours=24)
    samples = [
        sample
        for sample in snapshot.hourly_precipitation
        if window_start <= sample.at <= window_end
    ]
    total = sum(sample.inches for sample in samples)
    wet_samples = [sample for sample in samples if sample.inches > 0]
    if total < threshold_inches or not wet_samples:
        return total, None
    hold_until = max(sample.at for sample in wet_samples) + timedelta(hours=delay_hours)
    return total, hold_until if hold_until > now else None


def _local_datetime(value: str, timezone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(UTC)


def _coordinate_name(settings: WeatherSettings) -> str:
    assert settings.latitude is not None
    assert settings.longitude is not None
    return f"{settings.latitude:.4f}, {settings.longitude:.4f}"
