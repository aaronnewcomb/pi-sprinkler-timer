"""Signed browser sessions for the same-origin web application."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrowserSession:
    value: str
    csrf_token: str
    expires_at_epoch: int


class BrowserSessionManager:
    """Issue and verify HMAC-signed, short-lived browser sessions."""

    def __init__(self, signing_key: str, *, lifetime_seconds: int = 43_200) -> None:
        if not signing_key:
            raise ValueError("Session signing key must not be empty")
        if lifetime_seconds < 300:
            raise ValueError("Browser session lifetime must be at least five minutes")
        self._signing_key = signing_key.encode("utf-8")
        self._lifetime_seconds = lifetime_seconds

    @property
    def lifetime_seconds(self) -> int:
        return self._lifetime_seconds

    def issue(self, *, now_epoch: int | None = None) -> BrowserSession:
        issued_at = int(time.time()) if now_epoch is None else now_epoch
        expires_at = issued_at + self._lifetime_seconds
        csrf_token = secrets.token_urlsafe(24)
        payload = f"{expires_at}.{csrf_token}"
        signature = self._signature(payload)
        return BrowserSession(
            value=f"{payload}.{signature}",
            csrf_token=csrf_token,
            expires_at_epoch=expires_at,
        )

    def verify(self, value: str | None, *, now_epoch: int | None = None) -> str | None:
        if value is None:
            return None
        try:
            expires_text, csrf_token, supplied_signature = value.split(".", 2)
            expires_at = int(expires_text)
        except (TypeError, ValueError):
            return None
        payload = f"{expires_at}.{csrf_token}"
        if not hmac.compare_digest(supplied_signature, self._signature(payload)):
            return None
        current_time = int(time.time()) if now_epoch is None else now_epoch
        if current_time >= expires_at:
            return None
        return csrf_token

    def _signature(self, payload: str) -> str:
        return hmac.new(
            self._signing_key,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
