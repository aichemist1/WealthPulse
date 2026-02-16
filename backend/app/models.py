from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.utcnow()


class RawPayload(SQLModel, table=True):
    __tablename__ = "raw_payloads"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    source: str = Field(index=True)  # e.g. "sec_edgar"
    source_id: str = Field(index=True)  # e.g. accession number, URL, etc.

    fetched_at: datetime = Field(default_factory=utcnow, index=True)
    content_type: Optional[str] = None
    sha256: str = Field(index=True)
    payload: bytes = Field(default=b"", sa_column_kwargs={"nullable": False})

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_raw_payload_source_source_id"),
        UniqueConstraint("sha256", name="uq_raw_payload_sha256"),
    )


class Stock(SQLModel, table=True):
    __tablename__ = "stocks"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    ticker: str = Field(index=True)
    name: Optional[str] = None

    created_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (UniqueConstraint("ticker", name="uq_stock_ticker"),)


class Investor(SQLModel, table=True):
    __tablename__ = "investors"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(index=True)
    cik: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("cik", name="uq_investor_cik"),
        Index("ix_investor_name_lower", "name"),
    )


class Filing(SQLModel, table=True):
    __tablename__ = "filings"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    source: str = Field(index=True)  # e.g. "sec_edgar"
    form_type: str = Field(index=True)  # e.g. "4", "SC 13D", "13F-HR"
    accession_number: Optional[str] = Field(default=None, index=True)

    filer_cik: Optional[str] = Field(default=None, index=True)
    issuer_cik: Optional[str] = Field(default=None, index=True)
    filed_at: Optional[datetime] = Field(default=None, index=True)
    accepted_at: Optional[datetime] = Field(default=None, index=True)
    report_period: Optional[str] = Field(default=None, index=True)  # YYYY-MM-DD (as filed)

    raw_payload_id: Optional[str] = Field(default=None, foreign_key="raw_payloads.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("source", "accession_number", name="uq_filing_source_accession"),
        Index("ix_filing_source_form_filed_at", "source", "form_type", "filed_at"),
    )


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    event_type: str = Field(index=True)  # e.g. "insider_tx"
    dedupe_key: str = Field(index=True)  # stable idempotency key from normalized inputs

    stock_id: Optional[str] = Field(default=None, foreign_key="stocks.id", index=True)
    investor_id: Optional[str] = Field(default=None, foreign_key="investors.id", index=True)
    filing_id: Optional[str] = Field(default=None, foreign_key="filings.id", index=True)

    event_date: Optional[datetime] = Field(default=None, index=True)
    filed_at: Optional[datetime] = Field(default=None, index=True)
    detected_at: datetime = Field(default_factory=utcnow, index=True)

    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_event_dedupe_key"),
        Index("ix_event_type_event_date", "event_type", "event_date"),
    )


class InsiderTx(SQLModel, table=True):
    """
    Denormalized Form 4 transaction row for fast UI and signal calculation.

    Canonical date fields:
    - event_date: transaction date
    - filed_at: when reported/accepted
    - detected_at: when ingested
    """

    __tablename__ = "insider_txs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    event_id: str = Field(foreign_key="events.id", index=True)

    ticker: str = Field(index=True)
    issuer_cik: Optional[str] = Field(default=None, index=True)
    insider_name: str = Field(index=True)
    insider_cik: Optional[str] = Field(default=None, index=True)

    transaction_code: str = Field(index=True)  # e.g. "P" purchase, "S" sale
    acquired_disposed: Optional[str] = Field(default=None, index=True)  # "A" or "D"
    is_derivative: bool = Field(default=False, index=True)
    shares: Optional[float] = None
    price: Optional[float] = None
    transaction_value: Optional[float] = Field(default=None, index=True)
    shares_owned_following: Optional[float] = None

    event_date: Optional[datetime] = Field(default=None, index=True)
    filed_at: Optional[datetime] = Field(default=None, index=True)
    detected_at: datetime = Field(default_factory=utcnow, index=True)

    source_accession: Optional[str] = Field(default=None, index=True)
    seq: int = Field(default=0, index=True)

    __table_args__ = (
        UniqueConstraint(
            "source_accession",
            "seq",
            name="uq_insider_tx_accession_seq",
        ),
        Index("ix_insider_tx_ticker_event_date", "ticker", "event_date"),
    )


class InsiderTxMeta(SQLModel, table=True):
    """
    Per-transaction metadata that we may want to evolve without ALTERing InsiderTx often.
    (Keeps schema changes incremental in a pilot.)
    """

    __tablename__ = "insider_tx_meta"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    insider_tx_id: str = Field(foreign_key="insider_txs.id", index=True)

    is_10b5_1: Optional[bool] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("insider_tx_id", name="uq_insider_tx_meta_tx"),
        Index("ix_insider_tx_meta_10b5", "is_10b5_1"),
    )


class SnapshotRun(SQLModel, table=True):
    __tablename__ = "snapshot_runs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    kind: str = Field(index=True)  # e.g. "insider_whales"
    as_of: datetime = Field(index=True)
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (Index("ix_snapshot_run_kind_as_of", "kind", "as_of"),)


class SnapshotInsiderWhale(SQLModel, table=True):
    __tablename__ = "snapshot_insider_whales"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="snapshot_runs.id", index=True)

    ticker: str = Field(index=True)
    total_purchase_value: float = Field(index=True)
    purchase_tx_count: int = Field(default=0, index=True)
    latest_event_date: Optional[datetime] = Field(default=None, index=True)

    __table_args__ = (Index("ix_snapshot_whale_run_value", "run_id", "total_purchase_value"),)


class Institution13FReport(SQLModel, table=True):
    __tablename__ = "institution_13f_reports"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    investor_id: str = Field(foreign_key="investors.id", index=True)

    accession_number: Optional[str] = Field(default=None, index=True)
    report_period: Optional[str] = Field(default=None, index=True)  # YYYY-MM-DD

    filed_at: Optional[datetime] = Field(default=None, index=True)
    accepted_at: Optional[datetime] = Field(default=None, index=True)

    raw_payload_id: Optional[str] = Field(default=None, foreign_key="raw_payloads.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_13f_accession"),
        Index("ix_13f_report_investor_period", "investor_id", "report_period"),
    )


class Institution13FHolding(SQLModel, table=True):
    __tablename__ = "institution_13f_holdings"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    report_id: str = Field(foreign_key="institution_13f_reports.id", index=True)

    cusip: str = Field(index=True)
    name_of_issuer: Optional[str] = None
    title_of_class: Optional[str] = None

    value_usd: Optional[int] = Field(default=None, index=True)  # as reported in the 13F XML
    shares: Optional[float] = None
    shares_type: Optional[str] = None  # e.g. "SH", "PRN"
    put_call: Optional[str] = Field(default=None, index=True)  # PUT/CALL if present
    investment_discretion: Optional[str] = None

    voting_sole: Optional[int] = None
    voting_shared: Optional[int] = None
    voting_none: Optional[int] = None

    seq: int = Field(default=0, index=True)

    __table_args__ = (
        UniqueConstraint("report_id", "seq", name="uq_13f_holding_report_seq"),
        Index("ix_13f_holding_cusip_value", "cusip", "value_usd"),
    )


class Snapshot13FWhale(SQLModel, table=True):
    __tablename__ = "snapshot_13f_whales"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="snapshot_runs.id", index=True)

    cusip: str = Field(index=True)
    total_value_usd: int = Field(index=True)
    delta_value_usd: int = Field(index=True)
    manager_count: int = Field(default=0, index=True)
    manager_increase_count: int = Field(default=0, index=True)
    manager_decrease_count: int = Field(default=0, index=True)

    __table_args__ = (Index("ix_snapshot_13f_run_delta", "run_id", "delta_value_usd"),)


class Security(SQLModel, table=True):
    """
    Minimal security master mapping for v0.

    13F holdings are CUSIP-based; most UI and recommendation work is ticker-based,
    so we store a user-provided mapping (CSV import).
    """

    __tablename__ = "securities"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    cusip: str = Field(index=True)
    ticker: str = Field(index=True)
    name: Optional[str] = None
    cik: Optional[str] = Field(default=None, index=True)
    openfigi_market_sector: Optional[str] = Field(default=None, index=True)
    openfigi_security_type: Optional[str] = Field(default=None, index=True)
    openfigi_security_type2: Optional[str] = Field(default=None, index=True)
    openfigi_exch_code: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("cusip", name="uq_security_cusip"),
        UniqueConstraint("ticker", name="uq_security_ticker"),
        Index("ix_security_ticker_upper", "ticker"),
    )


class SnapshotRecommendation(SQLModel, table=True):
    __tablename__ = "snapshot_recommendations"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="snapshot_runs.id", index=True)

    ticker: str = Field(index=True)
    segment: str = Field(index=True)  # e.g. "Institutional Accumulation (13F)"
    action: str = Field(index=True)  # buy|sell|watch
    direction: str = Field(index=True)  # bullish|bearish|neutral
    score: int = Field(index=True)  # 0-100
    confidence: float = Field(index=True)  # 0-1

    reasons: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    __table_args__ = (
        UniqueConstraint("run_id", "ticker", name="uq_snapshot_rec_run_ticker"),
        Index("ix_snapshot_rec_run_score", "run_id", "score"),
    )


class LargeOwnerFiling(SQLModel, table=True):
    """
    Denormalized large-owner/activist filings (Schedule 13D/13G).
    Used as a corroborator for turning 13F ideas into actionable Buy/Sell.
    """

    __tablename__ = "large_owner_filings"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    source_accession: str = Field(index=True)
    form_type: str = Field(index=True)  # "SC 13D", "SC 13G", ... incl /A

    ticker: str = Field(index=True)
    issuer_cik: Optional[str] = Field(default=None, index=True)

    filer_cik: Optional[str] = Field(default=None, index=True)
    filer_name: Optional[str] = None

    filed_at: Optional[datetime] = Field(default=None, index=True)
    accepted_at: Optional[datetime] = Field(default=None, index=True)
    detected_at: datetime = Field(default_factory=utcnow, index=True)

    raw_payload_id: Optional[str] = Field(default=None, foreign_key="raw_payloads.id", index=True)

    __table_args__ = (
        UniqueConstraint("source_accession", name="uq_large_owner_accession"),
        Index("ix_large_owner_ticker_filed_at", "ticker", "filed_at"),
    )


class PriceBar(SQLModel, table=True):
    __tablename__ = "price_bars"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    ticker: str = Field(index=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    close: float = Field(index=True)
    volume: Optional[int] = None
    source: str = Field(default="stooq", index=True)
    detected_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("ticker", "date", "source", name="uq_price_bar_ticker_date_source"),
        Index("ix_price_bar_ticker_date", "ticker", "date"),
    )


class SocialSignal(SQLModel, table=True):
    """
    Lightweight social/cashtag signal buckets.
    Source can be CSV/manual in pilot; provider integration can be added later.
    """

    __tablename__ = "social_signals"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    ticker: str = Field(index=True)
    bucket_start: datetime = Field(index=True)
    bucket_minutes: int = Field(default=15, index=True)
    mentions: int = Field(default=0, index=True)
    sentiment_hint: Optional[float] = Field(default=None, index=True)  # -1..1 if available
    source: str = Field(default="manual_csv", index=True)
    detected_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("ticker", "bucket_start", "bucket_minutes", "source", name="uq_social_signal_bucket"),
        Index("ix_social_signal_ticker_bucket", "ticker", "bucket_start"),
    )


class DividendMetrics(SQLModel, table=True):
    """
    Best-effort dividend/yield fundamentals for curated income watchlists.

    Notes:
    - Values are provider-derived and may be stale/inaccurate for some tickers.
    - This is NOT a corporate-actions engine; treat as informational only.
    """

    __tablename__ = "dividend_metrics"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    ticker: str = Field(index=True)
    source: str = Field(default="yahoo_finance", index=True)

    dividend_yield_ttm: Optional[float] = Field(default=None, index=True)  # 0..1
    payout_ratio: Optional[float] = Field(default=None, index=True)  # 0..1 (provider definition)
    forward_annual_dividend: Optional[float] = None
    trailing_annual_dividend: Optional[float] = None

    ex_dividend_date: Optional[str] = Field(default=None, index=True)  # YYYY-MM-DD
    as_of: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("ticker", "source", name="uq_dividend_metrics_ticker_source"),
        Index("ix_dividend_metrics_ticker_as_of", "ticker", "as_of"),
    )


class AdminAlert(SQLModel, table=True):
    """
    Admin-only alert feed (v0).
    """

    __tablename__ = "admin_alerts"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    dedupe_key: str = Field(index=True)

    kind: str = Field(index=True)  # e.g. fresh_buy, fresh_avoid, trend_flip_bull, trend_flip_bear
    ticker: Optional[str] = Field(default=None, index=True)
    severity: str = Field(default="info", index=True)  # info|warn|high

    title: str
    body: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow, index=True)
    read_at: Optional[datetime] = Field(default=None, index=True)

    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_admin_alert_dedupe_key"),
        Index("ix_admin_alert_created_at", "created_at"),
        Index("ix_admin_alert_kind_created_at", "kind", "created_at"),
    )


class Subscriber(SQLModel, table=True):
    """
    Subscriber account (alerts only, no dashboard access).
    v0: email + status.
    """

    __tablename__ = "subscribers"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    email: str = Field(index=True)
    status: str = Field(default="pending", index=True)  # pending|active|unsubscribed|bounced
    tier: str = Field(default="pilot", index=True)  # pilot|pro|...

    created_at: datetime = Field(default_factory=utcnow, index=True)
    confirmed_at: Optional[datetime] = Field(default=None, index=True)
    unsubscribed_at: Optional[datetime] = Field(default=None, index=True)

    __table_args__ = (
        UniqueConstraint("email", name="uq_subscriber_email"),
        Index("ix_subscriber_status_created", "status", "created_at"),
    )


class SubscriberToken(SQLModel, table=True):
    """
    Token table for double opt-in and unsubscribe.
    Store only a hash of the token (never plaintext).
    """

    __tablename__ = "subscriber_tokens"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    token_hash: str = Field(index=True)
    purpose: str = Field(index=True)  # confirm|unsubscribe
    subscriber_id: str = Field(foreign_key="subscribers.id", index=True)

    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    used_at: Optional[datetime] = Field(default=None, index=True)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_subscriber_token_hash"),
        Index("ix_subscriber_token_purpose_expires", "purpose", "expires_at"),
    )


class AlertRun(SQLModel, table=True):
    """
    Auditable artifact: the set of alert items we intended to deliver for an as-of time.
    """

    __tablename__ = "alert_runs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    as_of: datetime = Field(index=True)
    status: str = Field(default="draft", index=True)  # draft|sent|skipped
    policy: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    source_runs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))  # run_id per snapshot kind
    created_at: datetime = Field(default_factory=utcnow, index=True)
    sent_at: Optional[datetime] = Field(default=None, index=True)

    __table_args__ = (
        Index("ix_alert_run_as_of_created", "as_of", "created_at"),
        Index("ix_alert_run_status_created", "status", "created_at"),
    )


class AlertItem(SQLModel, table=True):
    __tablename__ = "alert_items"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="alert_runs.id", index=True)

    ticker: str = Field(index=True)
    action: str = Field(index=True)  # buy|sell
    segment: str = Field(index=True)
    score: int = Field(index=True)
    confidence: float = Field(index=True)

    why: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    __table_args__ = (
        UniqueConstraint("run_id", "ticker", name="uq_alert_item_run_ticker"),
        Index("ix_alert_item_run_score", "run_id", "score"),
    )


class AlertDelivery(SQLModel, table=True):
    __tablename__ = "alert_deliveries"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="alert_runs.id", index=True)
    subscriber_id: str = Field(foreign_key="subscribers.id", index=True)

    status: str = Field(default="queued", index=True)  # queued|sent|failed|skipped
    provider_message_id: Optional[str] = None
    error: Optional[str] = None

    queued_at: datetime = Field(default_factory=utcnow, index=True)
    sent_at: Optional[datetime] = Field(default=None, index=True)

    __table_args__ = (Index("ix_alert_delivery_run_status", "run_id", "status"),)


class AdminSetting(SQLModel, table=True):
    """
    Simple admin-controlled settings store (v0).
    Used for thresholds/toggles without redeploying.
    """

    __tablename__ = "admin_settings"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    key: str = Field(index=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (UniqueConstraint("key", name="uq_admin_settings_key"),)


class DailySnapshotArtifact(SQLModel, table=True):
    """
    Versioned, auditable daily snapshot payload for reproducibility/backtests.
    """

    __tablename__ = "daily_snapshot_artifacts"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    kind: str = Field(default="daily_snapshot_v0", index=True)
    as_of: datetime = Field(index=True)
    version: str = Field(default="v0.1", index=True)
    artifact_hash: str = Field(index=True)

    source_runs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("kind", "as_of", "version", "artifact_hash", name="uq_daily_snapshot_artifact_hash"),
        Index("ix_daily_snapshot_artifact_as_of_created", "as_of", "created_at"),
    )


class BacktestRun(SQLModel, table=True):
    """
    Basic backtest artifact for snapshot recommendation performance.
    """

    __tablename__ = "backtest_runs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    kind: str = Field(default="backtest_v0", index=True)
    started_at: datetime = Field(default_factory=utcnow, index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)

    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    __table_args__ = (
        Index("ix_backtest_run_kind_started", "kind", "started_at"),
        Index("ix_backtest_run_completed", "completed_at"),
    )
