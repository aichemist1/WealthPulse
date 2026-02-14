from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.settings import settings


class OpenFigiError(RuntimeError):
    pass


@dataclass
class OpenFigiClient:
    api_key: str = ""
    rps: float = 2.0
    timeout_s: float = 30.0
    _last_request_at: float = 0.0

    def _sleep_for_rate_limit(self) -> None:
        if self.rps <= 0:
            return
        min_interval = 1.0 / self.rps
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def map_cusips(self, cusips: list[str]) -> list[dict[str, Any]]:
        """
        Call OpenFIGI mapping endpoint for a batch of CUSIPs.
        Returns raw JSON objects from the API.
        """

        self._sleep_for_rate_limit()
        self._last_request_at = time.monotonic()

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key

        payload = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]
        try:
            with httpx.Client(timeout=self.timeout_s, headers=headers) as client:
                resp = client.post("https://api.openfigi.com/v3/mapping", json=payload)
        except httpx.HTTPError as e:
            raise OpenFigiError(f"OpenFIGI request failed: {e}") from e

        if resp.status_code >= 400:
            raise OpenFigiError(f"OpenFIGI request failed: {resp.status_code} {resp.reason_phrase}")

        data = resp.json()
        if not isinstance(data, list):
            raise OpenFigiError("OpenFIGI response is not a list")
        return data


def default_openfigi_client() -> OpenFigiClient:
    return OpenFigiClient(api_key=settings.openfigi_api_key, rps=settings.openfigi_rps)


def pick_best_equity_mapping(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Pick a 'best' mapping result from one OpenFIGI mapping item.
    Prefer common stock equities when present.
    """

    results = item.get("data")
    if not isinstance(results, list) or not results:
        return None

    def score(r: dict[str, Any]) -> int:
        # Higher is better
        st = (r.get("securityType") or "").upper()
        stm = (r.get("securityType2") or "").upper()
        ex = (r.get("exchCode") or "").upper()
        s = 0
        if st == "COMMON STOCK":
            s += 50
        if stm in {"EQUITY", "COMMON STOCK"}:
            s += 20
        if ex:
            s += 5
        if r.get("ticker"):
            s += 10
        return s

    return sorted(results, key=score, reverse=True)[0]

