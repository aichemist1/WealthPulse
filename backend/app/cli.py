from __future__ import annotations

import hashlib
import csv
from datetime import datetime, timedelta
from pathlib import Path

import typer
import httpx
from sqlmodel import Session, select
from sqlmodel import col

from app.connectors.form4 import parse_form4_xml
from app.connectors.openfigi import default_openfigi_client, pick_best_equity_mapping
from app.connectors.sec_edgar import default_sec_client
from app.connectors.sp500_constituents import parse_sp500_constituents_csv
from app.db import engine, init_db
from app.ingestion.form4_edgar import ingest_form4_day
from app.ingestion.prices_stooq import ingest_stooq_prices
from app.ingestion.sc13_edgar import ingest_sc13_day
from app.ingestion.thirteenf_edgar import ingest_13f_day
from app.models import Event, Filing, InsiderTx, InsiderTxMeta, Investor, RawPayload, Stock
from app.models import Institution13FHolding, Institution13FReport, Snapshot13FWhale
from app.models import LargeOwnerFiling
from app.models import PriceBar
from app.models import SocialSignal
from app.models import Security
from app.models import DividendMetrics
from app.models import SnapshotInsiderWhale, SnapshotRun
from app.models import SnapshotRecommendation
from app.models import Subscriber
from app.models import AlertDelivery, AlertRun
from app.models import DailySnapshotArtifact
from app.models import BacktestRun
from app.snapshot.insider_whales import compute_insider_whales, window_start
from app.security_map import parse_security_map_csv
from app.snapshot.thirteenf_whales import HoldingValueRow, compute_13f_whales, previous_quarter_end
from app.snapshot.recommendations_v0 import WhaleDeltaRow, score_recommendations_from_13f
from app.snapshot.fresh_signals_v0 import FreshSignalParams, compute_fresh_signals_v0
from app.snapshot.trend import compute_technical_snapshot_from_closes, compute_trend_from_closes
from app.snapshot.tech_guardrail_v0 import apply_tech_guardrail_v0
from app.snapshot.market_regime import compute_market_regime
from app.snapshot.watchlists import parse_ticker_csv
from app.connectors.yahoo_finance import YahooFinanceClient, YahooFinanceError
from app.connectors.social_reddit import RedditSocialClient, RedditSocialError, parse_reddit_listing_to_buckets
from app.snapshot.alerts_v0 import generate_alerts_v0
from app.subscriptions import issue_token, upsert_subscriber, confirm_subscription, unsubscribe
from app.notifications.email_smtp import send_email_smtp, EmailSendError
from app.alerts.send_subscriber_alerts_v0 import (
    build_draft_subscriber_alert_run_v0,
    send_subscriber_alert_run_v0,
)
from app.admin_settings import get_setting, set_setting
from app.snapshot.sector_regime import compute_sector_regimes
from app.settings import settings
from app.snapshot.daily_artifact_v0 import build_daily_snapshot_payload_v0
from app.backtest.harness_v0 import run_backtest_v0


app = typer.Typer(add_completion=False)


@app.callback()
def _ensure_db_initialized() -> None:
    # Make CLI commands robust to schema drift / first-run.
    # This is intentionally silent (no output) so command output stays script-friendly.
    init_db()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@app.command("init-db")
def init_db_cmd() -> None:
    init_db()
    typer.echo("DB initialized.")


@app.command("ingest-form4-xml")
def ingest_form4_xml(path: Path, accession: str = typer.Option("", help="Optional accession number")) -> None:
    """
    Dev-only ingestion path: parse a local Form 4 XML file and write normalized rows.
    """

    raw_bytes = path.read_bytes()
    xml_text = raw_bytes.decode("utf-8", errors="replace")
    txs = parse_form4_xml(xml_text)
    if not txs:
        raise typer.Exit(code=2)

    source = "sec_edgar"
    source_id = accession or path.name
    sha256 = _sha256(raw_bytes)

    now = datetime.utcnow()

    with Session(engine) as session:
        existing_raw = session.exec(
            select(RawPayload).where(RawPayload.source == source, RawPayload.source_id == source_id)
        ).first()
        if existing_raw is None:
            raw = RawPayload(
                source=source,
                source_id=source_id,
                fetched_at=now,
                content_type="application/xml",
                sha256=sha256,
                payload=raw_bytes,
            )
            session.add(raw)
            session.flush()
            raw_id = raw.id
        else:
            raw_id = existing_raw.id

        filing = session.exec(
            select(Filing).where(Filing.source == source, Filing.accession_number == (accession or None))
        ).first()
        if filing is None:
            filing = Filing(
                source=source,
                form_type="4",
                accession_number=accession or None,
                filer_cik=txs[0].reporting_owner_cik,
                issuer_cik=txs[0].issuer_cik,
                raw_payload_id=raw_id,
            )
            session.add(filing)
            session.flush()

        ticker = txs[0].issuer_trading_symbol or "UNKNOWN"
        stock = session.exec(select(Stock).where(Stock.ticker == ticker)).first()
        if stock is None:
            stock = Stock(ticker=ticker)
            session.add(stock)
            session.flush()

        investor_name = txs[0].reporting_owner_name or "UNKNOWN"
        investor = session.exec(select(Investor).where(Investor.name == investor_name)).first()
        if investor is None:
            investor = Investor(name=investor_name, cik=txs[0].reporting_owner_cik)
            session.add(investor)
            session.flush()

        inserted = 0
        for i, tx in enumerate(txs):
            dedupe_key = f"form4:{accession or source_id}:{i}"
            event = session.exec(select(Event).where(Event.dedupe_key == dedupe_key)).first()
            if event is not None:
                continue

            event = Event(
                event_type="insider_tx",
                dedupe_key=dedupe_key,
                stock_id=stock.id,
                investor_id=investor.id,
                filing_id=filing.id,
                event_date=datetime.combine(tx.transaction_date, datetime.min.time()) if tx.transaction_date else None,
                filed_at=None,
                detected_at=now,
                data={
                    "transaction_code": tx.transaction_code,
                    "acquired_disposed": tx.acquired_disposed,
                    "shares": tx.shares,
                    "price_per_share": tx.price_per_share,
                    "shares_owned_following": tx.shares_owned_following,
                    "is_derivative": tx.is_derivative,
                },
            )
            session.add(event)
            session.flush()

            insider_tx = InsiderTx(
                event_id=event.id,
                ticker=ticker,
                issuer_cik=tx.issuer_cik,
                insider_name=investor_name,
                insider_cik=tx.reporting_owner_cik,
                transaction_code=tx.transaction_code or "",
                acquired_disposed=tx.acquired_disposed,
                is_derivative=tx.is_derivative,
                shares=tx.shares,
                price=tx.price_per_share,
                transaction_value=(float(tx.shares) * float(tx.price_per_share))
                if (tx.shares is not None and tx.price_per_share is not None)
                else None,
                shares_owned_following=tx.shares_owned_following,
                event_date=event.event_date,
                filed_at=event.filed_at,
                detected_at=now,
                source_accession=accession or source_id,
                seq=i,
            )
            session.add(insider_tx)
            session.flush()
            session.add(InsiderTxMeta(insider_tx_id=insider_tx.id, is_10b5_1=tx.is_10b5_1))
            inserted += 1

        session.commit()

    typer.echo(f"Inserted {inserted} transactions.")


@app.command("ingest-form4-edgar")
def ingest_form4_edgar(
    day: str = typer.Option(..., help="Filing date (YYYY-MM-DD) for SEC daily master index"),
    universe_file: Path = typer.Option(
        None, help="Optional newline-delimited ticker list to restrict ingestion (e.g., S&P 500)"
    ),
    limit: int = typer.Option(0, help="Optional max number of Form 4 filings to process (0 = no limit)"),
) -> None:
    """
    Ingest Form 4 filings from SEC EDGAR for a given day (via daily master index).

    Requires: WEALTHPULSE_SEC_USER_AGENT to be set to a descriptive User-Agent with contact info.
    """

    try:
        y, m, d = (int(x) for x in day.split("-"))
        day_date = datetime(y, m, d).date()
    except Exception:
        raise typer.BadParameter("day must be in YYYY-MM-DD format")

    universe_tickers = None
    if universe_file is not None:
        if not universe_file.exists():
            raise typer.BadParameter(f"universe_file not found: {universe_file}")
        universe_tickers = {line.strip().upper() for line in universe_file.read_text().splitlines() if line.strip()}

    client = default_sec_client()

    with Session(engine) as session:
        result = ingest_form4_day(
            session=session,
            client=client,
            day=day_date,
            universe_tickers=universe_tickers,
            limit=limit,
        )

    typer.echo(
        f"Form4 day {day_date.isoformat()}: filings_seen={result.filings_seen} "
        f"filings_ingested={result.filings_ingested} tx_inserted={result.transactions_inserted}"
    )


@app.command("ingest-13f-edgar")
def ingest_13f_edgar(
    day: str = typer.Option(..., help="Filing date (YYYY-MM-DD) for SEC daily master index"),
    limit: int = typer.Option(0, help="Optional max number of 13F filings to process (0 = no limit)"),
) -> None:
    """
    Ingest 13F-HR (institutional holdings) filings from SEC EDGAR for a given day.
    """

    try:
        y, m, d = (int(x) for x in day.split("-"))
        day_date = datetime(y, m, d).date()
    except Exception:
        raise typer.BadParameter("day must be in YYYY-MM-DD format")

    client = default_sec_client()
    with Session(engine) as session:
        result = ingest_13f_day(session=session, client=client, day=day_date, limit=limit)

    typer.echo(
        f"13F day {day_date.isoformat()}: filings_seen={result.filings_seen} "
        f"filings_ingested={result.filings_ingested} holdings_inserted={result.holdings_inserted}"
    )


@app.command("ingest-sc13-edgar")
def ingest_sc13_edgar(
    day: str = typer.Option(..., help="Filing date (YYYY-MM-DD) for SEC daily index"),
    universe_tickers_file: Path = typer.Option(None, help="Optional newline-delimited ticker list"),
    limit: int = typer.Option(0, help="Optional max filings to process (0 = no limit)"),
) -> None:
    """
    Ingest Schedule 13D/13G filings (large-owner/activist corroborator) for a given day.
    """

    try:
        y, m, d = (int(x) for x in day.split("-"))
        day_date = datetime(y, m, d).date()
    except Exception:
        raise typer.BadParameter("day must be in YYYY-MM-DD format")

    universe = None
    if universe_tickers_file is not None:
        if not universe_tickers_file.exists():
            raise typer.BadParameter(f"universe_tickers_file not found: {universe_tickers_file}")
        universe = {ln.strip().upper() for ln in universe_tickers_file.read_text().splitlines() if ln.strip()}

    client = default_sec_client()
    with Session(engine) as session:
        result = ingest_sc13_day(session=session, client=client, day=day_date, universe_tickers=universe, limit=limit)

    typer.echo(f"SC13 day {day_date.isoformat()}: filings_seen={result.filings_seen} filings_ingested={result.filings_ingested}")


@app.command("ingest-prices-stooq")
def ingest_prices_stooq(
    tickers_file: Path = typer.Option(None, help="Optional newline-delimited tickers file"),
    tickers: str = typer.Option("", help="Comma-separated tickers (e.g. AAPL,NVDA)"),
    keep_last_days: int = typer.Option(200, help="How many daily bars to keep per ticker"),
    limit_tickers: int = typer.Option(0, help="Optional limit tickers processed (0 = no limit)"),
) -> None:
    """
    Ingest daily close prices from Stooq (free) for trend corroboration.
    """

    ts: list[str] = []
    if tickers_file is not None:
        if not tickers_file.exists():
            raise typer.BadParameter(f"tickers_file not found: {tickers_file}")
        ts.extend([ln.strip().upper() for ln in tickers_file.read_text().splitlines() if ln.strip()])
    if tickers.strip():
        ts.extend([t.strip().upper() for t in tickers.split(",") if t.strip()])
    ts = list(dict.fromkeys(ts))
    if limit_tickers and limit_tickers > 0:
        ts = ts[:limit_tickers]
    if not ts:
        raise typer.BadParameter("Provide tickers or tickers_file")

    with Session(engine) as session:
        res = ingest_stooq_prices(session=session, tickers=ts, keep_last_days=keep_last_days)
    typer.echo(f"Stooq prices: tickers_seen={res.tickers_seen} bars_inserted={res.bars_inserted}")


@app.command("ingest-social-signals-csv")
def ingest_social_signals_csv(
    csv_file: Path = typer.Option(..., help="CSV with at least: ticker,bucket_start,mentions"),
    source: str = typer.Option("manual_csv", help="Source label"),
    bucket_minutes: int = typer.Option(15, help="Bucket duration in minutes"),
) -> None:
    """
    Ingest social/cashtag buckets from CSV (feature-flagged listener input).

    CSV columns:
    - required: ticker, bucket_start (ISO datetime), mentions (int)
    - optional: sentiment_hint (float -1..1), source, bucket_minutes
    """
    if not csv_file.exists():
        raise typer.BadParameter(f"csv_file not found: {csv_file}")

    inserted = 0
    updated = 0
    rows_seen = 0

    with Session(engine) as session:
        with csv_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows_seen += 1
                ticker = str(row.get("ticker") or "").strip().upper()
                if not ticker:
                    continue
                bucket_start_s = str(row.get("bucket_start") or "").strip()
                if not bucket_start_s:
                    continue
                try:
                    bucket_start = datetime.fromisoformat(bucket_start_s)
                except Exception:
                    continue
                try:
                    mentions = int(float(str(row.get("mentions") or "0").strip() or "0"))
                except Exception:
                    mentions = 0

                sentiment_hint = None
                if row.get("sentiment_hint") not in (None, ""):
                    try:
                        sentiment_hint = float(str(row.get("sentiment_hint")).strip())
                    except Exception:
                        sentiment_hint = None

                row_source = str(row.get("source") or source).strip() or source
                row_bucket_minutes = bucket_minutes
                if row.get("bucket_minutes") not in (None, ""):
                    try:
                        row_bucket_minutes = int(float(str(row.get("bucket_minutes")).strip()))
                    except Exception:
                        row_bucket_minutes = bucket_minutes

                existing = session.exec(
                    select(SocialSignal).where(
                        col(SocialSignal.ticker) == ticker,
                        col(SocialSignal.bucket_start) == bucket_start,
                        col(SocialSignal.bucket_minutes) == row_bucket_minutes,
                        col(SocialSignal.source) == row_source,
                    )
                ).first()

                if existing is None:
                    session.add(
                        SocialSignal(
                            ticker=ticker,
                            bucket_start=bucket_start,
                            bucket_minutes=row_bucket_minutes,
                            mentions=max(0, mentions),
                            sentiment_hint=sentiment_hint,
                            source=row_source,
                        )
                    )
                    inserted += 1
                else:
                    existing.mentions = max(0, mentions)
                    existing.sentiment_hint = sentiment_hint
                    updated += 1
        session.commit()

    typer.echo(f"Social CSV: rows_seen={rows_seen} inserted={inserted} updated={updated}")


@app.command("ingest-social-reddit")
def ingest_social_reddit(
    subreddits: str = typer.Option("", help="Comma-separated subreddits (default from settings)"),
    listing: str = typer.Option("", help="new|hot (default from settings)"),
    limit_per_subreddit: int = typer.Option(0, help="Posts per subreddit (max 100; default from settings)"),
    lookback_hours: int = typer.Option(24, help="Only include posts created in this window"),
    bucket_minutes: int = typer.Option(0, help="Bucket minutes (default from settings)"),
    allow_plain_upper: bool = typer.Option(False, help="Also parse plain uppercase tokens (higher false positives)"),
    source: str = typer.Option("", help="Source label override"),
    dry_run: bool = typer.Option(False, help="Parse and print counts; do not write DB"),
) -> None:
    """
    Ingest social mention buckets from Reddit listings.

    v0.1 uses strict cashtag extraction by default ($AAPL).
    """

    subs_raw = subreddits.strip() or settings.social_reddit_subreddits
    subs = [s.strip().lower() for s in subs_raw.split(",") if s.strip()]
    if not subs:
        raise typer.BadParameter("No subreddits provided")

    list_name = (listing.strip() or settings.social_reddit_listing or "new").lower()
    if list_name not in {"new", "hot"}:
        raise typer.BadParameter("listing must be new|hot")
    lim = limit_per_subreddit if limit_per_subreddit > 0 else int(settings.social_reddit_limit_per_subreddit)
    lim = max(1, min(int(lim), 100))
    bmin = bucket_minutes if bucket_minutes > 0 else int(settings.social_reddit_bucket_minutes)
    bmin = max(1, min(int(bmin), 120))
    src = source.strip() or settings.social_reddit_source_label or "reddit"
    plain_upper = bool(allow_plain_upper or settings.social_reddit_allow_plain_upper)
    since = datetime.utcnow() - timedelta(hours=max(1, min(int(lookback_hours), 168)))

    client = RedditSocialClient(user_agent=settings.sec_user_agent, timeout_s=20.0, rps=1.0)

    rows_seen = 0
    inserted = 0
    updated = 0
    sub_ok = 0
    sub_failed = 0
    by_ticker: dict[str, int] = {}

    with Session(engine) as session:
        for sub in subs:
            try:
                payload = client.fetch_listing(subreddit=sub, listing=list_name, limit=lim)
                rows = parse_reddit_listing_to_buckets(
                    payload=payload,
                    source=f"{src}:{sub}",
                    bucket_minutes=bmin,
                    since=since,
                    allow_plain_upper=plain_upper,
                )
                sub_ok += 1
            except RedditSocialError as e:
                sub_failed += 1
                typer.echo(f"WARN: {e}")
                continue

            for row in rows:
                rows_seen += 1
                by_ticker[row.ticker] = by_ticker.get(row.ticker, 0) + int(row.mentions or 0)
                if dry_run:
                    continue

                existing = session.exec(
                    select(SocialSignal).where(
                        col(SocialSignal.ticker) == row.ticker,
                        col(SocialSignal.bucket_start) == row.bucket_start,
                        col(SocialSignal.bucket_minutes) == row.bucket_minutes,
                        col(SocialSignal.source) == row.source,
                    )
                ).first()
                if existing is None:
                    session.add(
                        SocialSignal(
                            ticker=row.ticker,
                            bucket_start=row.bucket_start,
                            bucket_minutes=row.bucket_minutes,
                            mentions=max(0, int(row.mentions)),
                            sentiment_hint=row.sentiment_hint,
                            source=row.source,
                        )
                    )
                    inserted += 1
                else:
                    existing.mentions = max(0, int(row.mentions))
                    existing.sentiment_hint = row.sentiment_hint
                    updated += 1

        if not dry_run:
            session.commit()

    top = sorted(by_ticker.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_txt = ", ".join([f"{t}:{m}" for (t, m) in top]) if top else "none"
    typer.echo(
        f"Social Reddit: subreddits_ok={sub_ok} failed={sub_failed} "
        f"rows_seen={rows_seen} inserted={inserted} updated={updated} dry_run={dry_run}"
    )
    typer.echo(f"Top mentions: {top_txt}")


@app.command("ingest-dividend-metrics-yahoo")
def ingest_dividend_metrics_yahoo(
    tickers: str = typer.Option("", help="Comma-delimited tickers (default: WEALTHPULSE_WATCHLIST_DIVIDEND_STOCKS)"),
    timeout_s: float = typer.Option(20.0, help="HTTP timeout seconds"),
    rps: float = typer.Option(2.0, help="Requests per second"),
) -> None:
    """
    Fetch dividend/yield fundamentals from Yahoo Finance (unofficial endpoint) and store them.
    Intended for the High-Yield Dividend watchlist (v0).
    """

    from app.settings import settings

    ticker_list = parse_ticker_csv(tickers) if tickers.strip() else parse_ticker_csv(settings.watchlist_dividend_stocks)
    if not ticker_list:
        typer.echo("No tickers.")
        raise typer.Exit(code=2)

    client = YahooFinanceClient(user_agent=settings.sec_user_agent, timeout_s=timeout_s, rps=rps)

    upserted = 0
    failed = 0
    with Session(engine) as session:
        for t in ticker_list:
            try:
                snap = client.fetch_dividend_snapshot(t)
            except YahooFinanceError as e:
                failed += 1
                typer.echo(f"WARN: {e}")
                continue

            existing = session.exec(
                select(DividendMetrics).where(DividendMetrics.ticker == t, DividendMetrics.source == "yahoo_finance")
            ).first()
            if existing is None:
                existing = DividendMetrics(ticker=t, source="yahoo_finance")
                session.add(existing)

            existing.dividend_yield_ttm = snap.dividend_yield_ttm
            existing.payout_ratio = snap.payout_ratio
            existing.forward_annual_dividend = snap.forward_annual_dividend
            existing.trailing_annual_dividend = snap.trailing_annual_dividend
            existing.ex_dividend_date = snap.ex_dividend_date
            existing.as_of = snap.as_of
            session.commit()
            upserted += 1

    typer.echo(f"Dividend metrics (Yahoo): tickers={len(ticker_list)} upserted={upserted} failed={failed}")


@app.command("generate-alerts-v0")
def generate_alerts_v0_cmd() -> None:
    """
    Generate admin-only alerts from the latest snapshots + watchlists.
    """

    with Session(engine) as session:
        inserted = generate_alerts_v0(session=session)
    typer.echo(f"Alerts generated: inserted={inserted}")


@app.command("import-security-map")
def import_security_map(
    path: Path = typer.Argument(..., help="CSV with columns: cusip,ticker[,name][,cik]"),
    upsert: bool = typer.Option(True, help="Upsert rows by cusip/ticker"),
) -> None:
    """
    Import a minimal CUSIP↔ticker mapping for 13F enrichment and S&P 500 filtering.
    """

    if not path.exists():
        raise typer.BadParameter(f"file not found: {path}")

    try:
        rows = parse_security_map_csv(path.read_text())
    except ValueError as e:
        raise typer.BadParameter(str(e))
    if not rows:
        raise typer.Exit(code=2)

    inserted = 0
    updated = 0

    with Session(engine) as session:
        for r in rows:
            existing = session.exec(select(Security).where(col(Security.cusip) == r.cusip)).first()
            if existing is None:
                existing = session.exec(select(Security).where(col(Security.ticker) == r.ticker)).first()

            if existing is None:
                session.add(Security(cusip=r.cusip, ticker=r.ticker, name=r.name, cik=r.cik))
                inserted += 1
            else:
                if not upsert:
                    continue
                changed = False
                if existing.cusip != r.cusip:
                    existing.cusip = r.cusip
                    changed = True
                if existing.ticker != r.ticker:
                    existing.ticker = r.ticker
                    changed = True
                if r.name and existing.name != r.name:
                    existing.name = r.name
                    changed = True
                if r.cik and existing.cik != r.cik:
                    existing.cik = r.cik
                    changed = True
                if changed:
                    session.add(existing)
                    updated += 1

        session.commit()

    typer.echo(f"Imported security map: inserted={inserted} updated={updated}")


@app.command("fetch-sp500-tickers")
def fetch_sp500_tickers(
    out: Path = typer.Option(Path("sp500_tickers.txt"), help="Output path (newline-delimited tickers)"),
    url: str = typer.Option("", help="Override constituents CSV URL"),
) -> None:
    """
    Download an S&P 500 constituents CSV from a public URL and write tickers to a file.
    """

    from app.settings import settings

    src = url.strip() or settings.sp500_constituents_csv_url
    try:
        resp = httpx.get(src, timeout=30.0, headers={"User-Agent": settings.sec_user_agent})
        resp.raise_for_status()
        csv_text = resp.text
    except httpx.HTTPError as e:
        typer.echo(f"Failed to download S&P 500 constituents: {e}")
        raise typer.Exit(code=2)

    rows = parse_sp500_constituents_csv(csv_text)
    tickers = sorted({r.ticker for r in rows})
    if not tickers:
        raise typer.Exit(code=2)
    out.write_text("\n".join(tickers) + "\n")
    typer.echo(f"Wrote {len(tickers)} tickers to {out}")


@app.command("enrich-security-map-openfigi")
def enrich_security_map_openfigi(
    cusips_file: Path = typer.Option(None, help="Optional newline-delimited CUSIP list (default: infer from 13F holdings)"),
    limit: int = typer.Option(200, help="Max CUSIPs to query this run"),
    batch_size: int = typer.Option(10, help="OpenFIGI batch size (reduce if you see 413 errors)"),
) -> None:
    """
    Enrich Security map using OpenFIGI (CUSIP -> ticker).

    If no cusips_file is provided, pulls distinct CUSIPs from ingested 13F holdings.
    """

    client = default_openfigi_client()
    if not client.api_key:
        typer.echo("Warning: WEALTHPULSE_OPENFIGI_API_KEY not set; OpenFIGI may rate-limit anonymous requests.")

    with Session(engine) as session:
        if cusips_file is not None:
            if not cusips_file.exists():
                raise typer.BadParameter(f"cusips_file not found: {cusips_file}")
            cusips = [ln.strip().upper() for ln in cusips_file.read_text().splitlines() if ln.strip()]
        else:
            cusips = [str(c).upper() for c in session.exec(select(Institution13FHolding.cusip).distinct()).all()]

        # Only query those not yet mapped.
        # SQLModel returns scalars for single-column selects.
        known = {str(c).upper() for c in session.exec(select(Security.cusip)).all() if c}
        todo = [c for c in cusips if c and c not in known][:limit]

        inserted = 0
        start = 0
        bs = max(1, batch_size)
        while start < len(todo):
            batch = todo[start : start + bs]
            if not batch:
                break
            try:
                resp = client.map_cusips(batch)
            except Exception as e:
                msg = str(e)
                if "413" in msg and bs > 1:
                    bs = max(1, bs // 2)
                    typer.echo(f"OpenFIGI payload too large; retrying with batch_size={bs}")
                    continue
                raise

            for idx, item in enumerate(resp):
                best = pick_best_equity_mapping(item)
                if not best:
                    continue
                cusip = batch[idx].upper() if idx < len(batch) else ""
                ticker = (best.get("ticker") or "").upper()
                name = best.get("name")
                market_sector = best.get("marketSector")
                security_type = best.get("securityType")
                security_type2 = best.get("securityType2")
                exch_code = best.get("exchCode")
                if not cusip or not ticker:
                    continue
                if session.exec(select(Security).where(col(Security.cusip) == cusip)).first() is not None:
                    continue
                session.add(
                    Security(
                        cusip=cusip,
                        ticker=ticker,
                        name=name,
                        openfigi_market_sector=market_sector,
                        openfigi_security_type=security_type,
                        openfigi_security_type2=security_type2,
                        openfigi_exch_code=exch_code,
                    )
                )
                inserted += 1
            session.commit()
            start += bs

    typer.echo(f"OpenFIGI enrichment: inserted={inserted}")


@app.command("report-insider-buys")
def report_insider_buys(
    min_value: float = typer.Option(250_000, help="Minimum transaction value (shares * price)"),
    limit: int = typer.Option(25, help="Max rows to print"),
    ticker: str = typer.Option("", help="Optional ticker filter (e.g. AAPL)"),
) -> None:
    """
    Print largest insider purchase transactions ingested so far (proxy for 'whale buys').
    """

    ticker_u = ticker.strip().upper() if ticker else ""
    with Session(engine) as session:
        stmt = (
            select(InsiderTx)
            .where(InsiderTx.transaction_value != None)  # noqa: E711
            .where(InsiderTx.transaction_value >= min_value)
            .where(col(InsiderTx.transaction_code) == "P")
            .where(col(InsiderTx.is_derivative) == False)  # noqa: E712
            .order_by(col(InsiderTx.transaction_value).desc())
            .limit(limit)
        )
        if ticker_u:
            stmt = stmt.where(col(InsiderTx.ticker) == ticker_u)

        rows = list(session.exec(stmt).all())

    if not rows:
        typer.echo("No matching insider buys found.")
        raise typer.Exit(code=0)

    for r in rows:
        typer.echo(
            f"{r.ticker} value=${r.transaction_value:,.0f} shares={r.shares or 0:g} "
            f"px={r.price or 0:g} date={r.event_date.date().isoformat() if r.event_date else 'n/a'} "
            f"insider={r.insider_name} accession={r.source_accession}"
        )


@app.command("snapshot-insider-whales")
def snapshot_insider_whales(
    as_of: str = typer.Option(..., help="As-of datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"),
    window_days: int = typer.Option(7, help="Lookback window size (days)"),
    min_value: float = typer.Option(250_000, help="Min transaction value (shares*price) to count"),
    universe_file: Path = typer.Option(None, help="Optional newline-delimited ticker list"),
    limit: int = typer.Option(50, help="Max tickers to persist/print"),
) -> None:
    """
    Compute and persist an auditable 'insider whale buys' snapshot as-of a timestamp.
    """

    try:
        if "T" in as_of:
            as_of_dt = datetime.fromisoformat(as_of)
        else:
            y, m, d = (int(x) for x in as_of.split("-"))
            as_of_dt = datetime(y, m, d, 23, 59, 59)
    except Exception:
        raise typer.BadParameter("as_of must be YYYY-MM-DD or ISO datetime (YYYY-MM-DDTHH:MM:SS)")

    universe = None
    if universe_file is not None:
        if not universe_file.exists():
            raise typer.BadParameter(f"universe_file not found: {universe_file}")
        universe = {line.strip().upper() for line in universe_file.read_text().splitlines() if line.strip()}

    start_dt = window_start(as_of_dt, window_days)

    with Session(engine) as session:
        stmt = (
            select(InsiderTx)
            .where(InsiderTx.event_date != None)  # noqa: E711
            .where(InsiderTx.event_date >= start_dt)
            .where(InsiderTx.event_date <= as_of_dt)
        )
        if universe is not None:
            stmt = stmt.where(col(InsiderTx.ticker).in_(universe))

        rows = list(session.exec(stmt).all())
        computed = compute_insider_whales(rows=rows, min_value=min_value)[:limit]

        run = SnapshotRun(
            kind="insider_whales",
            as_of=as_of_dt,
            params={"window_days": window_days, "min_value": min_value, "limit": limit, "universe": bool(universe)},
        )
        session.add(run)
        session.flush()

        for r in computed:
            session.add(
                SnapshotInsiderWhale(
                    run_id=run.id,
                    ticker=r.ticker,
                    total_purchase_value=r.total_purchase_value,
                    purchase_tx_count=r.purchase_tx_count,
                    latest_event_date=r.latest_event_date,
                )
            )

        session.commit()

    if not computed:
        typer.echo("No insider whales found for the given window/as_of.")
        return

    for r in computed:
        typer.echo(f"{r.ticker} total=${r.total_purchase_value:,.0f} txs={r.purchase_tx_count}")


@app.command("snapshot-13f-whales")
def snapshot_13f_whales(
    report_period: str = typer.Option(..., help="13F report period (quarter end) in YYYY-MM-DD"),
    universe_cusips_file: Path = typer.Option(None, help="Optional newline-delimited CUSIP list"),
    universe_tickers_file: Path = typer.Option(None, help="Optional newline-delimited ticker list (requires mapping)"),
    limit: int = typer.Option(50, help="Max rows to persist/print"),
) -> None:
    """
    Compute and persist a 13F quarter-over-quarter whale snapshot (by CUSIP).

    Note: 13F holdings are reported by CUSIP; mapping to ticker requires a separate dataset.
    """

    try:
        rp = datetime.fromisoformat(report_period).date()
    except Exception:
        raise typer.BadParameter("report_period must be YYYY-MM-DD")

    prev = previous_quarter_end(rp)
    if prev is None:
        raise typer.BadParameter("report_period must be a quarter end (03-31, 06-30, 09-30, 12-31)")

    universe: set[str] | None = None
    if universe_cusips_file is not None and universe_tickers_file is not None:
        raise typer.BadParameter("Provide only one of universe_cusips_file or universe_tickers_file")
    if universe_cusips_file is not None:
        if not universe_cusips_file.exists():
            raise typer.BadParameter(f"universe_cusips_file not found: {universe_cusips_file}")
        universe = {line.strip().upper() for line in universe_cusips_file.read_text().splitlines() if line.strip()}

    rp_s = rp.isoformat()
    prev_s = prev.isoformat()

    with Session(engine) as session:
        if universe_tickers_file is not None:
            if not universe_tickers_file.exists():
                raise typer.BadParameter(f"universe_tickers_file not found: {universe_tickers_file}")
            tickers = {line.strip().upper() for line in universe_tickers_file.read_text().splitlines() if line.strip()}
            cusips = list(session.exec(select(Security.cusip).where(col(Security.ticker).in_(tickers))).all())
            universe = {str(c).upper() for c in cusips}
            if not universe:
                typer.echo("No CUSIPs found for provided tickers; import mapping first via import-security-map.")
                raise typer.Exit(code=2)

        cur_rows = list(
            session.exec(
                select(Institution13FReport.investor_id, Institution13FHolding.cusip, Institution13FHolding.value_usd)
                .join(Institution13FHolding, Institution13FHolding.report_id == Institution13FReport.id)
                .where(Institution13FReport.report_period == rp_s)
                .where(Institution13FHolding.value_usd != None)  # noqa: E711
            ).all()
        )
        prev_rows = list(
            session.exec(
                select(Institution13FReport.investor_id, Institution13FHolding.cusip, Institution13FHolding.value_usd)
                .join(Institution13FHolding, Institution13FHolding.report_id == Institution13FReport.id)
                .where(Institution13FReport.report_period == prev_s)
                .where(Institution13FHolding.value_usd != None)  # noqa: E711
            ).all()
        )

        current = [HoldingValueRow(investor_id=r[0], cusip=(r[1] or "").upper(), value_usd=int(r[2])) for r in cur_rows]
        previous = [HoldingValueRow(investor_id=r[0], cusip=(r[1] or "").upper(), value_usd=int(r[2])) for r in prev_rows]

        computed = compute_13f_whales(current=current, previous=previous, universe_cusips=universe)[:limit]

        run = SnapshotRun(
            kind="13f_whales",
            as_of=datetime.combine(rp, datetime.min.time()),
            params={
                "report_period": rp_s,
                "previous_period": prev_s,
                "limit": limit,
                "universe": bool(universe),
                "universe_mode": "cusip" if universe_cusips_file is not None else ("ticker" if universe_tickers_file is not None else "all"),
            },
        )
        session.add(run)
        session.flush()

        for r in computed:
            session.add(
                Snapshot13FWhale(
                    run_id=run.id,
                    cusip=r.cusip,
                    total_value_usd=r.total_value_usd,
                    delta_value_usd=r.delta_value_usd,
                    manager_count=r.manager_count,
                    manager_increase_count=r.manager_increase_count,
                    manager_decrease_count=r.manager_decrease_count,
                )
            )

        session.commit()

    if not computed:
        typer.echo("No 13F whale rows found for the given report period(s).")
        return

    # Best-effort enrichment with ticker/name via Security mapping table.
    cusips = [r.cusip for r in computed]
    with Session(engine) as session:
        sec_rows = list(session.exec(select(Security).where(col(Security.cusip).in_(cusips))).all())
    sec_by_cusip = {s.cusip: s for s in sec_rows}

    for r in computed:
        sec = sec_by_cusip.get(r.cusip)
        label = f"{sec.ticker} ({r.cusip})" if sec else r.cusip
        typer.echo(
            f"{label} delta=${r.delta_value_usd:,.0f} total=${r.total_value_usd:,.0f} "
            f"mgrs={r.manager_count} (+{r.manager_increase_count}/-{r.manager_decrease_count})"
        )


@app.command("snapshot-recommendations-v0")
def snapshot_recommendations_v0(
    as_of: str = typer.Option("", help="Override as-of timestamp (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"),
    fresh_days: int = typer.Option(7, help="Freshness window for corroborators (days)"),
    buy_score_threshold: int = typer.Option(70, help="Score threshold to label as BUY when corroborated"),
    insider_min_value: float = typer.Option(100_000, help="Minimum insider buy value to count as corroborator"),
    top_n: int = typer.Option(20, help="Max recommendations to persist/print"),
) -> None:
    """
    Create a v0 recommendations snapshot from the latest 13F whale snapshot.
    """

    as_of_dt: datetime
    if as_of.strip():
        try:
            if "T" in as_of:
                as_of_dt = datetime.fromisoformat(as_of)
            else:
                y, m, d = (int(x) for x in as_of.split("-"))
                as_of_dt = datetime(y, m, d, 23, 59, 59)
        except Exception:
            raise typer.BadParameter("as_of must be YYYY-MM-DD or ISO datetime (YYYY-MM-DDTHH:MM:SS)")
    else:
        as_of_dt = datetime.utcnow()

    fresh_start = as_of_dt - timedelta(days=fresh_days)

    with Session(engine) as session:
        market = compute_market_regime(session=session, as_of=as_of_dt, ticker="SPY")
        sector_regimes = compute_sector_regimes(session=session, as_of=as_of_dt)
        ticker_sector_map = get_setting(session, "ticker_sector_etf_map_v0") or {}

        run = session.exec(
            select(SnapshotRun).where(col(SnapshotRun.kind) == "13f_whales").order_by(col(SnapshotRun.as_of).desc())
        ).first()
        if run is None:
            typer.echo("No 13f_whales snapshot runs found. Run snapshot-13f-whales first.")
            raise typer.Exit(code=2)

        whale_rows = list(
            session.exec(select(Snapshot13FWhale).where(Snapshot13FWhale.run_id == run.id)).all()
        )
        cusips = {r.cusip for r in whale_rows}
        sec_rows = list(session.exec(select(Security).where(col(Security.cusip).in_(cusips))).all()) if cusips else []
        sec_by_cusip = {s.cusip: s for s in sec_rows}

        # Coverage ratio from metrics endpoint logic
        distinct_cusips = session.exec(select(Institution13FHolding.cusip)).all()
        distinct_cusips_count = len({str(c).upper() for c in distinct_cusips if c})
        mapped_cusips_all = session.exec(select(Security.cusip)).all()
        mapped_cusips_count = len({str(c).upper() for c in mapped_cusips_all if c})
        coverage = (mapped_cusips_count / distinct_cusips_count) if distinct_cusips_count else None

        inputs: list[WhaleDeltaRow] = []
        for r in whale_rows:
            sec = sec_by_cusip.get(r.cusip)
            if not sec:
                continue
            inputs.append(
                WhaleDeltaRow(
                    ticker=sec.ticker,
                    cusip=r.cusip,
                    delta_value_usd=r.delta_value_usd,
                    total_value_usd=r.total_value_usd,
                    manager_count=r.manager_count,
                    manager_increase_count=r.manager_increase_count,
                    manager_decrease_count=r.manager_decrease_count,
                    security_type=sec.openfigi_security_type,
                    security_type2=sec.openfigi_security_type2,
                    market_sector=sec.openfigi_market_sector,
                )
            )

        recs = score_recommendations_from_13f(rows=inputs, mapped_coverage_ratio=coverage, top_n=top_n)
        # Corroborators (fresh window)
        # NOTE: SQLModel returns scalars (not 1-tuples) for single-column selects.
        insider_buy_tickers = {
            str(t).upper()
            for t in session.exec(
                select(InsiderTx.ticker)
                .join(InsiderTxMeta, col(InsiderTxMeta.insider_tx_id) == col(InsiderTx.id), isouter=True)
                .where(col(InsiderTx.transaction_code) == "P")
                .where(col(InsiderTx.is_derivative) == False)  # noqa: E712
                .where(InsiderTx.event_date != None)  # noqa: E711
                .where(InsiderTx.event_date >= fresh_start)
                .where(InsiderTx.transaction_value != None)  # noqa: E711
                .where(InsiderTx.transaction_value >= insider_min_value)
                # 10b5-1 planned buys do not act as strong "fresh corroborator".
                .where((InsiderTxMeta.is_10b5_1 == None) | (col(InsiderTxMeta.is_10b5_1) == False))  # noqa: E711,E712
                .distinct()
            ).all()
            if t
        }
        sc13_tickers = {
            str(t).upper()
            for t in session.exec(
                select(LargeOwnerFiling.ticker)
                .where(LargeOwnerFiling.filed_at != None)  # noqa: E711
                .where(LargeOwnerFiling.filed_at >= fresh_start)
                .distinct()
            ).all()
            if t
        }

        # Trend corroborator (requires recent price bars).
        # IMPORTANT: compute trend using price bars *up to as_of_dt* (no lookahead),
        # and consider it "recent" if the last available bar is within ~3 calendar days
        # (to handle weekends/holidays).
        trend_bullish_tickers: set[str] = set()
        trend_by_ticker: dict[str, dict] = {}
        for rec in recs:
            as_of_day_s = as_of_dt.date().isoformat()
            bars = list(
                session.exec(
                    select(PriceBar.date, PriceBar.close)
                    .where(
                        PriceBar.ticker == rec.ticker,
                        PriceBar.source == "stooq",
                        PriceBar.date <= as_of_day_s,
                    )
                    .order_by(PriceBar.date)
                ).all()
            )
            if len(bars) < 55:
                continue
            dates = [d for (d, _) in bars]
            closes = [float(c) for (_, c) in bars]
            tech = compute_technical_snapshot_from_closes(dates=dates, closes=closes)
            # Keep `trend` as a dict for UI and add technical guardrail fields.
            trend_by_ticker[rec.ticker] = tech
            # "fresh" = last price within 3 days of as_of (calendar)
            if tech.get("as_of_date"):
                try:
                    y, m, d = (int(x) for x in str(tech.get("as_of_date")).split("-"))
                    last_day = datetime(y, m, d).date()
                    delta_days = (as_of_dt.date() - last_day).days
                    if 0 <= delta_days <= 3 and bool(tech.get("bullish")):
                        trend_bullish_tickers.add(rec.ticker)
                except Exception:
                    pass

        # Add context to reasons + compute actions
        for rec in recs:
            rec.reasons["as_of"] = as_of_dt.isoformat()
            if isinstance(run.params, dict):
                rp = run.params.get("report_period")
                pp = run.params.get("previous_period")
                if rp:
                    rec.reasons["report_period"] = rp
                if pp:
                    rec.reasons["previous_period"] = pp
            rec.reasons["corroborators"] = {
                "fresh_days": fresh_days,
                "insider_min_value": insider_min_value,
                "insider_buy_recent": rec.ticker in insider_buy_tickers,
                "sc13_recent": rec.ticker in sc13_tickers,
                "trend_bullish_recent": rec.ticker in trend_bullish_tickers,
            }
            if rec.ticker in trend_by_ticker:
                rec.reasons["trend"] = trend_by_ticker[rec.ticker]

            # Trend-based adjustment: 13F is conviction/context; trend is timing.
            # Penalize bearish setups and lightly reward bullish setups so Score better matches "buy now".
            whale_score = int(rec.score)
            trend_adj = 0
            trend_obj = trend_by_ticker.get(rec.ticker)
            if trend_obj is not None:
                if rec.ticker in trend_bullish_tickers:
                    trend_adj = 8
                    rec.confidence = min(0.85, rec.confidence + 0.10)
                else:
                    trend_adj = -8
                    rec.confidence = max(0.05, rec.confidence - 0.05)

            rec.reasons["whale_score"] = whale_score
            rec.reasons["trend_adjustment"] = trend_adj

            # Market regime (additive): small de-risking in bearish tape.
            market_score_adj = 0
            market_conf_adj = 0.0
            if market is not None:
                rec.reasons["market"] = market
                if market.get("bearish_recent"):
                    market_score_adj = -2
                    market_conf_adj = -0.05
                elif market.get("bullish_recent"):
                    market_score_adj = +1
                    market_conf_adj = +0.02

            rec.reasons["market_adjustment"] = {"score": market_score_adj, "confidence": market_conf_adj}

            # Sector regime (optional): requires a ticker->sector ETF mapping.
            sector_score_adj = 0
            sector_conf_adj = 0.0
            sector_etf = None
            if isinstance(ticker_sector_map, dict):
                sector_etf = ticker_sector_map.get(rec.ticker)
            if isinstance(sector_etf, str) and sector_etf in sector_regimes:
                sr = sector_regimes[sector_etf]
                rec.reasons["sector"] = {"etf": sector_etf, "regime": sr}
                if sr.get("bearish_recent"):
                    sector_score_adj = -1
                    sector_conf_adj = -0.02
                elif sr.get("bullish_recent"):
                    sector_score_adj = +1
                    sector_conf_adj = +0.01
            rec.reasons["sector_adjustment"] = {"score": sector_score_adj, "confidence": sector_conf_adj}

            rec.score = max(0, min(100, whale_score + trend_adj + market_score_adj + sector_score_adj))
            rec.confidence = max(0.05, min(0.90, rec.confidence + market_conf_adj + sector_conf_adj))

            # Technical guardrail: penalize chasing (extended/near-high), boost near support.
            tg = apply_tech_guardrail_v0(score=rec.score, tech=trend_by_ticker.get(rec.ticker))
            rec.reasons["tech_guardrail"] = {
                "ft": tg.ft,
                "adj": tg.adj,
                "score_before": tg.score_before,
                "score_after": tg.score_after,
                "notes": tg.notes,
            }
            rec.score = tg.score_after

            # Derived display value: 1..10 conviction band (do not treat as guaranteed performance).
            rec.reasons["conviction_1_10"] = int((rec.score + 9) // 10)

            if rec.score >= buy_score_threshold and (
                rec.ticker in insider_buy_tickers or rec.ticker in sc13_tickers or rec.ticker in trend_bullish_tickers
            ):
                rec.action = "buy"
                rec.confidence = min(0.80, rec.confidence + 0.20)

        rec_run = SnapshotRun(
            kind="recommendations_v0",
            as_of=as_of_dt,
            params={
                "source_run_id": run.id,
                "source_kind": "13f_whales",
                "top_n": top_n,
                "fresh_days": fresh_days,
                "buy_score_threshold": buy_score_threshold,
                "insider_min_value": insider_min_value,
            },
        )
        session.add(rec_run)
        session.flush()

        for rec in recs:
            session.add(
                SnapshotRecommendation(
                    run_id=rec_run.id,
                    ticker=rec.ticker,
                    segment=rec.segment,
                    action=rec.action,
                    direction=rec.direction,
                    score=rec.score,
                    confidence=rec.confidence,
                    reasons=rec.reasons,
                )
            )

        session.commit()

    for rec in recs:
        typer.echo(f"{rec.ticker} score={rec.score} action={rec.action} dir={rec.direction} conf={rec.confidence:.2f}")


@app.command("snapshot-fresh-signals-v0")
def snapshot_fresh_signals_v0(
    as_of: str = typer.Option("", help="Override as-of timestamp (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"),
    fresh_days: int = typer.Option(7, help="Freshness window for SC13 + insider tx (days)"),
    insider_min_value: float = typer.Option(100_000, help="Min Form 4 tx value (P/S) to count"),
    buy_score_threshold: int = typer.Option(75, help="Score threshold to label as BUY"),
    avoid_score_threshold: int = typer.Option(35, help="Score threshold to label as AVOID"),
    top_n: int = typer.Option(20, help="Max rows to persist/print"),
) -> None:
    """
    Create a v0 "Fresh Whale Signals" snapshot emphasizing SC 13D/13G + Form 4,
    with trend/volume confirmation. 13F is optional context only.
    """

    as_of_dt: datetime
    if as_of.strip():
        try:
            if "T" in as_of:
                as_of_dt = datetime.fromisoformat(as_of)
            else:
                y, m, d = (int(x) for x in as_of.split("-"))
                as_of_dt = datetime(y, m, d, 23, 59, 59)
        except Exception:
            raise typer.BadParameter("as_of must be YYYY-MM-DD or ISO datetime (YYYY-MM-DDTHH:MM:SS)")
    else:
        as_of_dt = datetime.utcnow()

    params = FreshSignalParams(
        as_of=as_of_dt,
        fresh_days=fresh_days,
        insider_min_value=insider_min_value,
        top_n=top_n,
        buy_score_threshold=buy_score_threshold,
        avoid_score_threshold=avoid_score_threshold,
    )

    with Session(engine) as session:
        rows = compute_fresh_signals_v0(session=session, params=params)

        if not rows:
            fresh_start = as_of_dt - timedelta(days=fresh_days)
            sc13_count = session.exec(
                select(LargeOwnerFiling.id)
                .where(LargeOwnerFiling.filed_at != None)  # noqa: E711
                .where(LargeOwnerFiling.filed_at >= fresh_start)
            ).all()
            insider_ge_min_count = session.exec(
                select(InsiderTx.id)
                .where(InsiderTx.event_date != None)  # noqa: E711
                .where(InsiderTx.event_date >= fresh_start)
                .where(col(InsiderTx.is_derivative) == False)  # noqa: E712
                .where(InsiderTx.transaction_value != None)  # noqa: E711
                .where(InsiderTx.transaction_value >= insider_min_value)
                .where(col(InsiderTx.transaction_code).in_(["P", "S"]))
            ).all()
            insider_total_ps = session.exec(
                select(InsiderTx.id)
                .where(InsiderTx.event_date != None)  # noqa: E711
                .where(InsiderTx.event_date >= fresh_start)
                .where(col(InsiderTx.is_derivative) == False)  # noqa: E712
                .where(col(InsiderTx.transaction_code).in_(["P", "S"]))
            ).all()
            insider_value_missing = session.exec(
                select(InsiderTx.id)
                .where(InsiderTx.event_date != None)  # noqa: E711
                .where(InsiderTx.event_date >= fresh_start)
                .where(col(InsiderTx.is_derivative) == False)  # noqa: E712
                .where(col(InsiderTx.transaction_code).in_(["P", "S"]))
                .where(InsiderTx.transaction_value == None)  # noqa: E711
            ).all()
            typer.echo(
                "No rows produced for fresh_signals_v0.\n"
                f"- Window: {fresh_start.isoformat()} .. {as_of_dt.isoformat()}\n"
                f"- SC13 filings in window: {len(sc13_count)}\n"
                f"- Insider tx (P/S, non-derivative) in window: {len(insider_total_ps)}\n"
                f"- Insider tx with missing value (needs shares*price): {len(insider_value_missing)}\n"
                f"- Insider tx (P/S, >= min, with value) in window: {len(insider_ge_min_count)}\n"
                "Next: run ingest-sc13-edgar and ingest-form4-edgar for days in this window "
                "(and ensure you are using the intended DB via WEALTHPULSE_DB_URL). "
                "If value is missing, lower --insider-min-value to 0 to validate pipeline, "
                "or ingest prices so we can estimate value."
            )
            raise typer.Exit(code=0)

        run = SnapshotRun(
            kind="fresh_signals_v0",
            as_of=as_of_dt,
            params={
                "top_n": top_n,
                "fresh_days": fresh_days,
                "insider_min_value": insider_min_value,
                "buy_score_threshold": buy_score_threshold,
                "avoid_score_threshold": avoid_score_threshold,
            },
        )
        session.add(run)
        session.flush()

        for r in rows:
            session.add(
                SnapshotRecommendation(
                    run_id=run.id,
                    ticker=r.ticker,
                    segment=r.segment,
                    action=r.action,
                    direction=r.direction,
                    score=r.score,
                    confidence=r.confidence,
                    reasons=r.reasons,
                )
            )
        session.commit()

    for r in rows:
        typer.echo(f"{r.ticker} score={r.score} action={r.action} dir={r.direction} conf={r.confidence:.2f}")


@app.command("snapshot-daily-artifact-v0")
def snapshot_daily_artifact_v0(
    as_of: str = typer.Option("", help="As-of timestamp (ISO), default now"),
    version: str = typer.Option("v0.1", help="Artifact schema/version tag"),
    top_n_rows: int = typer.Option(25, help="Top rows saved per snapshot source"),
    picks_per_segment: int = typer.Option(3, help="Segment picks per bucket saved in artifact"),
    force: bool = typer.Option(False, help="Write new artifact even if same hash already exists for as_of/version"),
) -> None:
    """
    Build and persist a versioned/auditable daily snapshot artifact.
    """

    run_as_of = datetime.utcnow()
    if as_of.strip():
        try:
            run_as_of = datetime.fromisoformat(as_of.strip())
        except Exception:
            raise typer.BadParameter("as_of must be ISO datetime (e.g. 2026-02-15T09:00:00)")

    version_tag = version.strip() or "v0.1"

    with Session(engine) as session:
        payload, digest, source_runs = build_daily_snapshot_payload_v0(
            session=session,
            as_of=run_as_of,
            version=version_tag,
            top_n_rows=top_n_rows,
            picks_per_segment=picks_per_segment,
        )

        existing = session.exec(
            select(DailySnapshotArtifact)
            .where(col(DailySnapshotArtifact.kind) == "daily_snapshot_v0")
            .where(col(DailySnapshotArtifact.as_of) == run_as_of)
            .where(col(DailySnapshotArtifact.version) == version_tag)
            .where(col(DailySnapshotArtifact.artifact_hash) == digest)
        ).first()

        if existing is not None and not force:
            typer.echo(
                f"Daily artifact unchanged. id={existing.id} as_of={existing.as_of.isoformat()} "
                f"version={existing.version} hash={existing.artifact_hash[:12]}"
            )
            return

        art = DailySnapshotArtifact(
            kind="daily_snapshot_v0",
            as_of=run_as_of,
            version=version_tag,
            artifact_hash=digest,
            source_runs=source_runs,
            payload=payload,
        )
        session.add(art)
        session.commit()
        session.refresh(art)

    typer.echo(
        f"Daily artifact created: id={art.id} as_of={art.as_of.isoformat()} "
        f"version={art.version} hash={art.artifact_hash[:12]}"
    )


@app.command("backtest-snapshots-v0")
def backtest_snapshots_v0(
    start_as_of: str = typer.Option(..., help="Start as-of date (YYYY-MM-DD)"),
    end_as_of: str = typer.Option(..., help="End as-of date (YYYY-MM-DD)"),
    source_kinds: str = typer.Option(
        "recommendations_v0,fresh_signals_v0",
        help="Comma-separated snapshot kinds",
    ),
    baseline_ticker: str = typer.Option("SPY", help="Baseline ticker for excess-return comparison"),
    horizons: str = typer.Option("5,20", help="Forward horizons in trading days"),
    top_n_per_action: int = typer.Option(5, help="Top rows per action (buy/avoid) per run"),
    persist: bool = typer.Option(True, help="Persist backtest artifact in DB"),
) -> None:
    """
    Basic backtest harness for snapshot recommendations vs baseline (SPY by default).
    """

    try:
        y1, m1, d1 = (int(x) for x in start_as_of.split("-"))
        y2, m2, d2 = (int(x) for x in end_as_of.split("-"))
        dt_start = datetime(y1, m1, d1, 0, 0, 0)
        dt_end = datetime(y2, m2, d2, 23, 59, 59)
    except Exception:
        raise typer.BadParameter("start_as_of/end_as_of must be YYYY-MM-DD")

    hs: list[int] = []
    for x in horizons.split(","):
        x = x.strip()
        if not x:
            continue
        try:
            v = int(x)
        except Exception:
            continue
        if v > 0:
            hs.append(v)
    if not hs:
        hs = [5, 20]

    kinds = [k.strip() for k in source_kinds.split(",") if k.strip()]
    if not kinds:
        kinds = ["recommendations_v0", "fresh_signals_v0"]

    with Session(engine) as session:
        summary = run_backtest_v0(
            session=session,
            start_as_of=dt_start,
            end_as_of=dt_end,
            source_kinds=kinds,
            baseline_ticker=baseline_ticker.strip().upper(),
            horizons=hs,
            top_n_per_action=top_n_per_action,
        )

        run_id = None
        if persist:
            br = BacktestRun(
                kind="backtest_v0",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                params={
                    "start_as_of": dt_start.isoformat(),
                    "end_as_of": dt_end.isoformat(),
                    "source_kinds": kinds,
                    "baseline_ticker": baseline_ticker.strip().upper(),
                    "horizons": hs,
                    "top_n_per_action": top_n_per_action,
                },
                summary=summary,
            )
            session.add(br)
            session.commit()
            session.refresh(br)
            run_id = br.id

    typer.echo(
        f"Backtest v0: runs={summary.get('runs_considered')} baseline={summary.get('baseline_ticker')} "
        f"window={summary.get('window', {}).get('start_as_of')}..{summary.get('window', {}).get('end_as_of')}"
    )
    if run_id:
        typer.echo(f"Backtest artifact id={run_id}")

    for m in summary.get("metrics", []):
        hr = m.get("hit_rate_vs_baseline")
        ex = m.get("avg_excess_return")
        cov = m.get("coverage")
        typer.echo(
            f"{m.get('source_kind')} {m.get('action')} h={m.get('horizon_days')} "
            f"n={m.get('evaluated')}/{m.get('attempted')} cov={cov:.2f} "
            f"hit={(f'{hr:.2f}' if isinstance(hr, float) else 'n/a')} "
            f"excess={(f'{100*ex:.2f}%' if isinstance(ex, float) else 'n/a')}"
        )


@app.command("subscribe-email")
def subscribe_email(
    email: str = typer.Option(..., help="Email address to subscribe (sends confirm email)"),
) -> None:
    from app.settings import settings

    with Session(engine) as session:
        sub = upsert_subscriber(session=session, email=email)
        tok = issue_token(session=session, subscriber_id=sub.id, purpose="confirm", ttl_hours=48)
        confirm_url = f"{settings.public_base_url.rstrip('/')}/confirm?token={tok.token}"
        unsub_tok = issue_token(session=session, subscriber_id=sub.id, purpose="unsubscribe", ttl_hours=24 * 365 * 2)
        unsub_url = f"{settings.public_base_url.rstrip('/')}/unsubscribe?token={unsub_tok.token}"

        subject = "Confirm your WealthPulse subscription"
        text = (
            "Welcome to WealthPulse!\n\n"
            "Please confirm your subscription:\n"
            f"{confirm_url}\n\n"
            f"Unsubscribe: {unsub_url}\n"
        )
        try:
            send_email_smtp(to_email=sub.email, subject=subject, text_body=text)
        except EmailSendError as e:
            typer.echo(f"ERROR: failed to send confirmation email: {e}")
            typer.echo("Manual confirm link (copy/paste in browser):")
            typer.echo(confirm_url)
            raise typer.Exit(code=2)
        typer.echo(f"Sent confirmation email to {sub.email}.")
        typer.echo(f"Confirm: {confirm_url}")


@app.command("confirm-email-token")
def confirm_email_token(
    token: str = typer.Option(..., help="Confirmation token (from email link)"),
) -> None:
    with Session(engine) as session:
        ok = confirm_subscription(session=session, token=token)
    typer.echo("OK" if ok else "INVALID")


@app.command("unsubscribe-token")
def unsubscribe_token(
    token: str = typer.Option(..., help="Unsubscribe token (from email link)"),
) -> None:
    with Session(engine) as session:
        ok = unsubscribe(session=session, token=token)
    typer.echo("OK" if ok else "INVALID")


@app.command("send-daily-subscriber-alerts-v0")
def send_daily_subscriber_alerts_cli(
    as_of: str = typer.Option("", help="As-of datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"),
    limit_subscribers: int = typer.Option(0, help="Limit number of subscribers (0 = all)"),
    send: bool = typer.Option(False, help="If set, also send emails (manual-only default is draft only)"),
) -> None:
    as_of_dt: Optional[datetime] = None
    if as_of.strip():
        try:
            if "T" in as_of:
                as_of_dt = datetime.fromisoformat(as_of)
            else:
                y, m, d = (int(x) for x in as_of.split("-"))
                as_of_dt = datetime(y, m, d, 23, 59, 59)
        except Exception:
            raise typer.BadParameter("as_of must be YYYY-MM-DD or ISO datetime")

    with Session(engine) as session:
        run = build_draft_subscriber_alert_run_v0(session=session, as_of=as_of_dt)
        typer.echo(f"Draft alert run created: run_id={run.id} status={run.status}")
        if send:
            res = send_subscriber_alert_run_v0(session=session, run_id=run.id, limit_subscribers=limit_subscribers)
            typer.echo(
                f"Send result: status={res.status} subs={res.subscribers_seen} sent={res.sent} failed={res.failed} skipped={res.skipped} changed={res.changed}"
            )
            return

    typer.echo("Manual-only mode: review in dashboard and click Send when ready.")


@app.command("list-subscribers")
def list_subscribers(
    status: str = typer.Option("", help="Optional status filter: pending|active|unsubscribed|bounced"),
    limit: int = typer.Option(50, help="Max rows"),
) -> None:
    with Session(engine) as session:
        stmt = select(Subscriber).order_by(col(Subscriber.created_at).desc()).limit(min(limit, 500))
        if status.strip():
            stmt = stmt.where(col(Subscriber.status) == status.strip())
        rows = list(session.exec(stmt).all())

    if not rows:
        typer.echo("No subscribers.")
        return

    for s in rows:
        typer.echo(
            f"{s.email}\tstatus={s.status}\tcreated={s.created_at.isoformat()}"
            + (f"\tconfirmed={s.confirmed_at.isoformat()}" if s.confirmed_at else "")
            + (f"\tunsubscribed={s.unsubscribed_at.isoformat()}" if s.unsubscribed_at else "")
        )


@app.command("admin-activate-subscriber")
def admin_activate_subscriber(
    email: str = typer.Option(..., help="Email to activate (pilot/testing override; bypasses confirm token)"),
) -> None:
    email_n = (email or "").strip().lower()
    with Session(engine) as session:
        s = session.exec(select(Subscriber).where(col(Subscriber.email) == email_n)).first()
        if s is None:
            typer.echo("NOT FOUND")
            raise typer.Exit(code=2)
        s.status = "active"
        s.confirmed_at = s.confirmed_at or datetime.utcnow()
        session.add(s)
        session.commit()
    typer.echo("OK")


@app.command("get-subscriber-alert-policy-v0")
def get_subscriber_alert_policy_v0() -> None:
    with Session(engine) as session:
        v = get_setting(session, "subscriber_alert_policy_v0") or {}
    if not v:
        typer.echo("{}")
    else:
        typer.echo(v)


@app.command("set-subscriber-alert-policy-v0")
def set_subscriber_alert_policy_v0(
    max_items: int = typer.Option(5, help="Max tickers per email"),
    min_confidence: float = typer.Option(0.30, help="Min confidence to include"),
    min_score_buy: int = typer.Option(75, help="Min score for BUY"),
    min_score_sell: int = typer.Option(35, help="Max score for SELL"),
    fresh_days: int = typer.Option(7, help="Freshness window (days)"),
) -> None:
    v = {
        "max_items": int(max_items),
        "min_confidence": float(min_confidence),
        "min_score_buy": int(min_score_buy),
        "min_score_sell": int(min_score_sell),
        "fresh_days": int(fresh_days),
    }
    with Session(engine) as session:
        row = set_setting(session, "subscriber_alert_policy_v0", v)
    typer.echo(f"OK updated_at={row.updated_at.isoformat()} value={row.value}")


@app.command("get-ticker-sector-etf-map-v0")
def get_ticker_sector_etf_map_v0() -> None:
    with Session(engine) as session:
        v = get_setting(session, "ticker_sector_etf_map_v0") or {}
    typer.echo(v)


@app.command("set-ticker-sector-etf-map-v0")
def set_ticker_sector_etf_map_v0(
    mapping: str = typer.Option(
        ...,
        help="Comma-delimited pairs like AAPL=XLK,MSFT=XLK,XOM=XLE (sector ETFs: XLK,XLF,XLE,XLV,XLI,XLY,XLP,XLU,XLB,XLC,XLRE)",
    ),
) -> None:
    m: dict[str, str] = {}
    for part in (mapping or "").split(","):
        p = part.strip()
        if not p:
            continue
        if "=" not in p:
            raise typer.BadParameter("mapping must use KEY=VALUE pairs")
        k, v = p.split("=", 1)
        k_u = k.strip().upper()
        v_u = v.strip().upper()
        if not k_u or not v_u:
            continue
        m[k_u] = v_u
    with Session(engine) as session:
        row = set_setting(session, "ticker_sector_etf_map_v0", m)
    typer.echo(f"OK updated_at={row.updated_at.isoformat()} size={len(m)}")


@app.command("list-alert-deliveries")
def list_alert_deliveries(
    run_id: str = typer.Option("", help="AlertRun id (default: latest)"),
    limit: int = typer.Option(50, help="Max rows"),
) -> None:
    """
    Inspect subscriber email send outcomes (queued/sent/failed) for debugging.
    """

    with Session(engine) as session:
        run: AlertRun | None
        if run_id.strip():
            run = session.exec(select(AlertRun).where(col(AlertRun.id) == run_id.strip())).first()
        else:
            run = session.exec(select(AlertRun).order_by(col(AlertRun.created_at).desc())).first()

        if run is None:
            typer.echo("No alert runs.")
            return

        deliveries = list(
            session.exec(
                select(AlertDelivery, Subscriber.email)
                .where(col(AlertDelivery.run_id) == run.id)
                .join(Subscriber, col(Subscriber.id) == col(AlertDelivery.subscriber_id))
                .order_by(col(AlertDelivery.queued_at).desc())
                .limit(min(limit, 500))
            ).all()
        )

    typer.echo(f"run_id={run.id} as_of={run.as_of.isoformat()} created_at={run.created_at.isoformat()}")
    if not deliveries:
        typer.echo("No deliveries.")
        return

    for d, email in deliveries:
        msg = f"{email}\tstatus={d.status}\tqueued={d.queued_at.isoformat()}"
        if d.sent_at:
            msg += f"\tsent={d.sent_at.isoformat()}"
        if d.error:
            msg += f"\terror={d.error}"
        typer.echo(msg)


if __name__ == "__main__":
    app()
