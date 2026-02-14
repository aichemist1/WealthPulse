from collections.abc import Iterator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.settings import settings


def create_db_engine():
    connect_args = {}
    if settings.db_url.startswith("sqlite:"):
        connect_args = {"check_same_thread": False}
    return create_engine(settings.db_url, echo=False, connect_args=connect_args)


engine = create_db_engine()


def _sqlite_columns(table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}  # name


def _sqlite_add_column_if_missing(table: str, column: str, ddl: str) -> None:
    cols = _sqlite_columns(table)
    if column in cols:
        return
    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
        conn.commit()


def _sqlite_migrate() -> None:
    # Additive migrations only (safe for v0). This avoids requiring DB deletion when we add columns.
    # securities: OpenFIGI enrichment fields
    if "securities" in _existing_tables():
        _sqlite_add_column_if_missing("securities", "openfigi_market_sector", "openfigi_market_sector TEXT")
        _sqlite_add_column_if_missing("securities", "openfigi_security_type", "openfigi_security_type TEXT")
        _sqlite_add_column_if_missing("securities", "openfigi_security_type2", "openfigi_security_type2 TEXT")
        _sqlite_add_column_if_missing("securities", "openfigi_exch_code", "openfigi_exch_code TEXT")

    # insider_txs: fields added after early schema versions
    if "insider_txs" in _existing_tables():
        _sqlite_add_column_if_missing("insider_txs", "transaction_value", "transaction_value REAL")
        _sqlite_add_column_if_missing("insider_txs", "is_derivative", "is_derivative INTEGER")
        _sqlite_add_column_if_missing("insider_txs", "acquired_disposed", "acquired_disposed TEXT")
        _sqlite_add_column_if_missing("insider_txs", "shares", "shares REAL")
        _sqlite_add_column_if_missing("insider_txs", "price", "price REAL")
        _sqlite_add_column_if_missing("insider_txs", "shares_owned_following", "shares_owned_following REAL")
        _sqlite_add_column_if_missing("insider_txs", "filed_at", "filed_at TIMESTAMP")
        _sqlite_add_column_if_missing("insider_txs", "detected_at", "detected_at TIMESTAMP")
        # Best-effort backfills for older DBs (non-destructive).
        with engine.connect() as conn:
            conn.execute(text("UPDATE insider_txs SET is_derivative = 0 WHERE is_derivative IS NULL"))
            conn.execute(
                text(
                    "UPDATE insider_txs "
                    "SET transaction_value = (shares * price) "
                    "WHERE transaction_value IS NULL AND shares IS NOT NULL AND price IS NOT NULL"
                )
            )
            conn.commit()

    # large_owner_filings: ensure table shape is forward-compatible
    if "large_owner_filings" in _existing_tables():
        _sqlite_add_column_if_missing("large_owner_filings", "accepted_at", "accepted_at TIMESTAMP")
        _sqlite_add_column_if_missing("large_owner_filings", "detected_at", "detected_at TIMESTAMP")
        _sqlite_add_column_if_missing("large_owner_filings", "raw_payload_id", "raw_payload_id TEXT")

    # alert_runs: manual-only send requires status/sent_at columns
    if "alert_runs" in _existing_tables():
        _sqlite_add_column_if_missing("alert_runs", "status", "status TEXT")
        _sqlite_add_column_if_missing("alert_runs", "sent_at", "sent_at TIMESTAMP")


def _existing_tables() -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    return {r[0] for r in rows}


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    if settings.db_url.startswith("sqlite:"):
        _sqlite_migrate()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
