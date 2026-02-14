from __future__ import annotations

import hashlib
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
from app.models import Event, Filing, InsiderTx, Investor, RawPayload, Stock
from app.models import Institution13FHolding, Institution13FReport, Snapshot13FWhale
from app.models import LargeOwnerFiling
from app.models import PriceBar
from app.models import Security
from app.models import DividendMetrics
from app.models import SnapshotInsiderWhale, SnapshotRun
from app.models import SnapshotRecommendation
from app.snapshot.insider_whales import compute_insider_whales, window_start
from app.security_map import parse_security_map_csv
from app.snapshot.thirteenf_whales import HoldingValueRow, compute_13f_whales, previous_quarter_end
from app.snapshot.recommendations_v0 import WhaleDeltaRow, score_recommendations_from_13f
from app.snapshot.fresh_signals_v0 import FreshSignalParams, compute_fresh_signals_v0
from app.snapshot.trend import compute_trend_from_closes
from app.snapshot.watchlists import parse_ticker_csv
from app.connectors.yahoo_finance import YahooFinanceClient, YahooFinanceError
from app.snapshot.alerts_v0 import generate_alerts_v0


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
        known = {s.cusip for s in session.exec(select(Security.cusip)).all()}
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
        insider_buy_tickers = {
            t
            for (t,) in session.exec(
                select(InsiderTx.ticker)
                .where(col(InsiderTx.transaction_code) == "P")
                .where(col(InsiderTx.is_derivative) == False)  # noqa: E712
                .where(InsiderTx.event_date != None)  # noqa: E711
                .where(InsiderTx.event_date >= fresh_start)
                .where(InsiderTx.transaction_value != None)  # noqa: E711
                .where(InsiderTx.transaction_value >= insider_min_value)
                .distinct()
            ).all()
        }
        sc13_tickers = {
            t
            for (t,) in session.exec(
                select(LargeOwnerFiling.ticker)
                .where(LargeOwnerFiling.filed_at != None)  # noqa: E711
                .where(LargeOwnerFiling.filed_at >= fresh_start)
                .distinct()
            ).all()
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
            tm = compute_trend_from_closes(dates=dates, closes=closes)
            ret60 = None
            if len(closes) >= 61:
                prev = closes[-61]
                if prev:
                    ret60 = (closes[-1] / prev) - 1.0
            sma200 = None
            if len(closes) >= 200:
                sma200 = sum(closes[-200:]) / 200.0
            trend_by_ticker[rec.ticker] = {
                "as_of_date": tm.as_of_date,
                "close": tm.close,
                "sma50": tm.sma50,
                "sma200": sma200,
                "return_20d": tm.return_20d,
                "return_60d": ret60,
                "bullish": tm.bullish,
            }
            # "fresh" = last price within 3 days of as_of (calendar)
            if tm.as_of_date:
                try:
                    y, m, d = (int(x) for x in tm.as_of_date.split("-"))
                    last_day = datetime(y, m, d).date()
                    delta_days = (as_of_dt.date() - last_day).days
                    if 0 <= delta_days <= 3 and tm.bullish:
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
            rec.score = max(0, min(100, whale_score + trend_adj))

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


if __name__ == "__main__":
    app()
