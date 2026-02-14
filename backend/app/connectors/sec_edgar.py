from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.settings import settings


class SecEdgarError(RuntimeError):
    pass


def _extract_email(user_agent: str) -> Optional[str]:
    # Best-effort: find something that looks like an email.
    for token in user_agent.replace("(", " ").replace(")", " ").replace("<", " ").replace(">", " ").split():
        if "@" in token and "." in token:
            return token.strip().strip(",;")
    return None


@dataclass
class SecEdgarClient:
    """
    Minimal SEC EDGAR client.

    Notes:
    - SEC requires a descriptive User-Agent (include a contact email).
    - Rate limiting is conservative by default (settings.sec_rps).
    """

    user_agent: str
    rps: float = 5.0
    timeout_s: float = 45.0
    retries: int = 3
    backoff_s: float = 1.0
    _last_request_at: float = 0.0

    def _sleep_for_rate_limit(self) -> None:
        if self.rps <= 0:
            return
        min_interval = 1.0 / self.rps
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def get(self, url: str, *, accept: Optional[str] = None) -> bytes:
        email = _extract_email(self.user_agent)
        headers = {
            "User-Agent": self.user_agent,
            **({"From": email} if email else {}),
            "Accept": accept or "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        # Retry on transient failures (timeouts, 429, 5xx).
        last_err: Exception | None = None
        attempts = max(1, int(self.retries) + 1)
        for attempt in range(1, attempts + 1):
            self._sleep_for_rate_limit()
            self._last_request_at = time.monotonic()
            try:
                with httpx.Client(timeout=self.timeout_s, headers=headers, follow_redirects=True) as client:
                    resp = client.get(url)
            except httpx.TimeoutException as e:
                last_err = e
            except httpx.HTTPError as e:
                last_err = e
            except OSError as e:
                # Some network stacks surface connect/read timeouts as plain OSError.
                last_err = e
            else:
                if resp.status_code < 400:
                    return resp.content

                # Non-retriable
                if resp.status_code == 403:
                    raise SecEdgarError(f"SEC request failed: 403 Forbidden ({url})")

                # Retriable: rate limit / server errors
                if resp.status_code in {429} or 500 <= resp.status_code < 600:
                    last_err = SecEdgarError(
                        f"SEC request failed: {resp.status_code} {resp.reason_phrase} ({url})"
                    )
                else:
                    raise SecEdgarError(f"SEC request failed: {resp.status_code} {resp.reason_phrase} ({url})")

            if attempt < attempts:
                time.sleep(self.backoff_s * attempt)

        raise SecEdgarError(f"SEC request failed: {last_err}") from last_err


def default_sec_client() -> SecEdgarClient:
    return SecEdgarClient(
        user_agent=settings.sec_user_agent,
        rps=settings.sec_rps,
        timeout_s=settings.sec_timeout_s,
        retries=settings.sec_retries,
        backoff_s=settings.sec_backoff_s,
    )
