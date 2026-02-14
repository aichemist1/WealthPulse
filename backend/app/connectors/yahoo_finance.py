from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx


class YahooFinanceError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_num(obj: Any) -> Optional[float]:
    if obj is None:
        return None
    if isinstance(obj, (int, float)):
        return float(obj)
    if isinstance(obj, dict):
        for k in ("raw", "fmt"):
            if k in obj and obj[k] is not None:
                try:
                    return float(obj[k])
                except Exception:
                    return None
    return None


def _get_epoch_date(obj: Any) -> Optional[str]:
    # Yahoo sometimes returns exDividendDate as epoch seconds (raw).
    v = _get_num(obj)
    if v is None:
        return None
    try:
        dt = datetime.fromtimestamp(float(v), tz=timezone.utc)
    except Exception:
        return None
    return dt.date().isoformat()


@dataclass(frozen=True)
class YahooDividendSnapshot:
    ticker: str
    dividend_yield_ttm: Optional[float]
    payout_ratio: Optional[float]
    forward_annual_dividend: Optional[float]
    trailing_annual_dividend: Optional[float]
    ex_dividend_date: Optional[str]
    as_of: datetime


def parse_quote_summary_json(*, ticker: str, json_text: str) -> YahooDividendSnapshot:
    try:
        payload = json.loads(json_text)
    except Exception as e:
        raise YahooFinanceError(f"Invalid JSON for {ticker}: {e}") from e

    qs = payload.get("quoteSummary") or {}
    result = (qs.get("result") or [None])[0] or {}
    if not result:
        err = (qs.get("error") or {}).get("description") if isinstance(qs.get("error"), dict) else None
        raise YahooFinanceError(f"Missing quoteSummary result for {ticker}: {err or 'unknown error'}")

    summary = result.get("summaryDetail") or {}
    stats = result.get("defaultKeyStatistics") or {}

    # Prefer trailingAnnualDividendYield where available; fall back to dividendYield.
    dy = _get_num(summary.get("trailingAnnualDividendYield"))
    if dy is None:
        dy = _get_num(summary.get("dividendYield"))

    payout = _get_num(stats.get("payoutRatio"))

    forward_div = _get_num(summary.get("dividendRate"))
    trailing_div = _get_num(summary.get("trailingAnnualDividendRate"))

    ex_div = None
    if "exDividendDate" in summary:
        ex_div = _get_epoch_date(summary.get("exDividendDate"))

    return YahooDividendSnapshot(
        ticker=ticker,
        dividend_yield_ttm=dy,
        payout_ratio=payout,
        forward_annual_dividend=forward_div,
        trailing_annual_dividend=trailing_div,
        ex_dividend_date=ex_div,
        as_of=_utc_now(),
    )


@dataclass
class YahooFinanceClient:
    user_agent: str = "WealthPulse dev"
    timeout_s: float = 20.0
    rps: float = 2.0
    _last_request_at: float = 0.0

    def _sleep_for_rate_limit(self) -> None:
        if self.rps <= 0:
            return
        min_interval = 1.0 / self.rps
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def fetch_dividend_snapshot(self, ticker: str) -> YahooDividendSnapshot:
        t = ticker.strip().upper()
        if not t:
            raise YahooFinanceError("empty ticker")

        # Unofficial but widely used endpoint.
        url = (
            f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{t}"
            "?modules=summaryDetail,defaultKeyStatistics"
        )

        self._sleep_for_rate_limit()
        self._last_request_at = time.monotonic()
        try:
            resp = httpx.get(url, timeout=self.timeout_s, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise YahooFinanceError(f"Yahoo request failed for {t}: {e}") from e

        return parse_quote_summary_json(ticker=t, json_text=resp.text)

