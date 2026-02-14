from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEALTHPULSE_", extra="ignore")

    db_url: str = "sqlite:///./wealthpulse.db"
    sec_user_agent: str = "WealthPulse dev (email@example.com)"
    sec_rps: float = 3.0
    sec_timeout_s: float = 45.0
    sec_retries: int = 3
    sec_backoff_s: float = 1.0

    # Public bootstrap sources (override as needed)
    sp500_constituents_csv_url: str = (
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
    )

    # Optional: OpenFIGI enrichment (CUSIP -> ticker)
    openfigi_api_key: str = ""
    openfigi_rps: float = 2.0

    # Dashboard watchlists (comma-delimited tickers)
    watchlist_etfs: str = "GLD,AIQ,QTUM,SKYY,MAGS,JTEK,ARKW,CHAT,HACK"
    watchlist_dividend_stocks: str = "VNOM,SLB,EOG"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


settings = Settings()
