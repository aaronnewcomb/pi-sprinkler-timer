"""SQLite persistence for schedules, delays, and station run history."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Self


@dataclass(frozen=True, slots=True)
class ScheduleStep:
    station_id: int
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class Schedule:
    id: int
    name: str
    enabled: bool
    start_time: time
    days_of_week: tuple[int, ...]
    steps: tuple[ScheduleStep, ...]
    last_started_local_date: date | None


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: int
    source: str
    schedule_id: int | None
    station_id: int
    duration_seconds: int
    started_at: datetime
    ended_at: datetime | None
    outcome: str | None


class ScheduleNotFoundError(ValueError):
    """Raised when a requested schedule does not exist."""


class SQLiteRepository:
    """Own the 3.0 SQLite database and its transactional operations."""

    SCHEMA_VERSION = 1

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path | str) -> Self:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        return cls(connection)

    def initialize(self, *, now: datetime | None = None) -> None:
        timestamp = _as_utc(now or datetime.now(UTC)).isoformat()
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    start_time TEXT NOT NULL,
                    days_of_week TEXT NOT NULL,
                    last_started_local_date TEXT,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schedule_steps (
                    schedule_id INTEGER NOT NULL REFERENCES schedules(id)
                        ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    station_id INTEGER NOT NULL,
                    duration_seconds INTEGER NOT NULL
                        CHECK (duration_seconds > 0),
                    PRIMARY KEY (schedule_id, position)
                );

                CREATE TABLE IF NOT EXISTS controller_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS run_history (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    schedule_id INTEGER,
                    station_id INTEGER NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    ended_at_utc TEXT,
                    outcome TEXT
                );

                CREATE INDEX IF NOT EXISTS run_history_started_at
                    ON run_history(started_at_utc DESC);
                """
            )
            version_row = self._connection.execute(
                "SELECT version FROM schema_version"
            ).fetchone()
            if version_row is None:
                self._connection.execute(
                    "INSERT INTO schema_version(version) VALUES (?)",
                    (self.SCHEMA_VERSION,),
                )
            elif version_row["version"] != self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported database schema version: {version_row['version']}"
                )
            self._connection.execute(
                """
                UPDATE run_history
                SET ended_at_utc = ?, outcome = 'interrupted'
                WHERE ended_at_utc IS NULL
                """,
                (timestamp,),
            )

    def close(self) -> None:
        self._connection.close()

    def create_schedule(
        self,
        *,
        name: str,
        enabled: bool,
        start_time: time,
        days_of_week: tuple[int, ...],
        steps: tuple[ScheduleStep, ...],
        now: datetime | None = None,
    ) -> Schedule:
        name, start_text, days_text, steps = _validate_schedule(
            name, start_time, days_of_week, steps
        )
        timestamp = _as_utc(now or datetime.now(UTC)).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO schedules(
                    name, enabled, start_time, days_of_week,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, int(enabled), start_text, days_text, timestamp, timestamp),
            )
            schedule_id = int(cursor.lastrowid)
            self._replace_steps(schedule_id, steps)
        return self.get_schedule(schedule_id)

    def update_schedule(
        self,
        schedule_id: int,
        *,
        name: str,
        enabled: bool,
        start_time: time,
        days_of_week: tuple[int, ...],
        steps: tuple[ScheduleStep, ...],
        now: datetime | None = None,
    ) -> Schedule:
        name, start_text, days_text, steps = _validate_schedule(
            name, start_time, days_of_week, steps
        )
        timestamp = _as_utc(now or datetime.now(UTC)).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE schedules
                SET name = ?, enabled = ?, start_time = ?, days_of_week = ?,
                    updated_at_utc = ?
                WHERE id = ?
                """,
                (
                    name,
                    int(enabled),
                    start_text,
                    days_text,
                    timestamp,
                    schedule_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ScheduleNotFoundError(f"Schedule {schedule_id} does not exist")
            self._connection.execute(
                "DELETE FROM schedule_steps WHERE schedule_id = ?",
                (schedule_id,),
            )
            self._replace_steps(schedule_id, steps)
        return self.get_schedule(schedule_id)

    def delete_schedule(self, schedule_id: int) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM schedules WHERE id = ?", (schedule_id,)
            )
            if cursor.rowcount != 1:
                raise ScheduleNotFoundError(f"Schedule {schedule_id} does not exist")

    def get_schedule(self, schedule_id: int) -> Schedule:
        row = self._connection.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if row is None:
            raise ScheduleNotFoundError(f"Schedule {schedule_id} does not exist")
        return self._schedule_from_row(row)

    def list_schedules(self) -> list[Schedule]:
        rows = self._connection.execute(
            "SELECT * FROM schedules ORDER BY id"
        ).fetchall()
        return [self._schedule_from_row(row) for row in rows]

    def claim_schedule(self, schedule_id: int, local_date: date) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE schedules
                SET last_started_local_date = ?
                WHERE id = ?
                  AND (
                    last_started_local_date IS NULL
                    OR last_started_local_date <> ?
                  )
                """,
                (local_date.isoformat(), schedule_id, local_date.isoformat()),
            )
        return cursor.rowcount == 1

    def set_controller_state(self, key: str, value: str | None) -> None:
        if not key.strip():
            raise ValueError("Controller state key must not be empty")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO controller_state(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_controller_state(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM controller_state WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else row["value"]

    def set_rain_delay(self, until: datetime | None) -> None:
        """Set the user-controlled rain delay retained by the v1 API."""
        self.set_manual_rain_delay(until)

    def set_manual_rain_delay(self, until: datetime | None) -> None:
        value = _as_utc(until).isoformat() if until is not None else None
        self.set_controller_state("rain_delay_until_utc", value)

    def set_weather_rain_delay(self, until: datetime | None) -> None:
        value = _as_utc(until).isoformat() if until is not None else None
        self.set_controller_state("weather_delay_until_utc", value)

    def get_manual_rain_delay(self) -> datetime | None:
        return self._datetime_controller_state("rain_delay_until_utc")

    def get_weather_rain_delay(self) -> datetime | None:
        return self._datetime_controller_state("weather_delay_until_utc")

    def get_rain_delay(self) -> datetime | None:
        delays = [
            delay
            for delay in (
                self.get_manual_rain_delay(),
                self.get_weather_rain_delay(),
            )
            if delay is not None
        ]
        return max(delays, default=None)

    def clear_expired_rain_delays(self, now: datetime) -> None:
        now_utc = _as_utc(now)
        if (manual := self.get_manual_rain_delay()) is not None and manual <= now_utc:
            self.set_manual_rain_delay(None)
        if (
            weather := self.get_weather_rain_delay()
        ) is not None and weather <= now_utc:
            self.set_weather_rain_delay(None)

    def _datetime_controller_state(self, key: str) -> datetime | None:
        value = self.get_controller_state(key)
        return datetime.fromisoformat(value) if value is not None else None

    def start_run(
        self,
        *,
        source: str,
        schedule_id: int | None,
        station_id: int,
        duration_seconds: int,
        started_at: datetime | None = None,
    ) -> int:
        timestamp = _as_utc(started_at or datetime.now(UTC)).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO run_history(
                    source, schedule_id, station_id, duration_seconds,
                    started_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (source, schedule_id, station_id, duration_seconds, timestamp),
            )
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        outcome: str,
        ended_at: datetime | None = None,
    ) -> None:
        timestamp = _as_utc(ended_at or datetime.now(UTC)).isoformat()
        with self._connection:
            self._connection.execute(
                """
                UPDATE run_history
                SET ended_at_utc = ?, outcome = ?
                WHERE id = ? AND ended_at_utc IS NULL
                """,
                (timestamp, outcome, run_id),
            )

    def list_runs(self, *, limit: int = 100) -> list[RunRecord]:
        if limit < 1 or limit > 1_000:
            raise ValueError("History limit must be between 1 and 1000")
        rows = self._connection.execute(
            """
            SELECT * FROM run_history
            ORDER BY started_at_utc DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            RunRecord(
                id=row["id"],
                source=row["source"],
                schedule_id=row["schedule_id"],
                station_id=row["station_id"],
                duration_seconds=row["duration_seconds"],
                started_at=datetime.fromisoformat(row["started_at_utc"]),
                ended_at=(
                    datetime.fromisoformat(row["ended_at_utc"])
                    if row["ended_at_utc"] is not None
                    else None
                ),
                outcome=row["outcome"],
            )
            for row in rows
        ]

    def _replace_steps(self, schedule_id: int, steps: tuple[ScheduleStep, ...]) -> None:
        self._connection.executemany(
            """
            INSERT INTO schedule_steps(
                schedule_id, position, station_id, duration_seconds
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (schedule_id, position, step.station_id, step.duration_seconds)
                for position, step in enumerate(steps, start=1)
            ],
        )

    def _schedule_from_row(self, row: sqlite3.Row) -> Schedule:
        step_rows = self._connection.execute(
            """
            SELECT station_id, duration_seconds
            FROM schedule_steps
            WHERE schedule_id = ?
            ORDER BY position
            """,
            (row["id"],),
        ).fetchall()
        return Schedule(
            id=row["id"],
            name=row["name"],
            enabled=bool(row["enabled"]),
            start_time=time.fromisoformat(row["start_time"]),
            days_of_week=tuple(int(day) for day in row["days_of_week"].split(",")),
            steps=tuple(
                ScheduleStep(
                    station_id=step_row["station_id"],
                    duration_seconds=step_row["duration_seconds"],
                )
                for step_row in step_rows
            ),
            last_started_local_date=(
                date.fromisoformat(row["last_started_local_date"])
                if row["last_started_local_date"] is not None
                else None
            ),
        )


def _validate_schedule(
    name: str,
    start_time: time,
    days_of_week: tuple[int, ...],
    steps: tuple[ScheduleStep, ...],
) -> tuple[str, str, str, tuple[ScheduleStep, ...]]:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Schedule name must not be empty")
    days = tuple(sorted(set(days_of_week)))
    if not days or any(day < 0 or day > 6 for day in days):
        raise ValueError("Schedule days must contain values from 0 through 6")
    if not steps:
        raise ValueError("A schedule must contain at least one station step")
    if any(step.station_id < 1 or step.duration_seconds < 1 for step in steps):
        raise ValueError("Schedule steps require positive station IDs and durations")
    start_text = start_time.replace(second=0, microsecond=0).isoformat(
        timespec="minutes"
    )
    return clean_name, start_text, ",".join(str(day) for day in days), steps


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Datetime values must include a timezone")
    return value.astimezone(UTC)
