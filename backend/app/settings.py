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

    # Optional social listener (v0.1, feature-flagged)
    social_enabled: bool = False
    social_velocity_threshold: float = 1.5
    social_min_mentions: int = 5
    social_reddit_enabled: bool = False
    social_reddit_subreddits: str = "wallstreetbets,stocks,investing,options"
    social_reddit_listing: str = "new"
    social_reddit_limit_per_subreddit: int = 100
    social_reddit_bucket_minutes: int = 15
    social_reddit_allow_plain_upper: bool = False
    social_reddit_source_label: str = "reddit"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Subscriber alerts (pilot): SMTP email
    public_base_url: str = "http://localhost:8000"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_starttls: bool = True
    smtp_from_email: str = ""
    smtp_from_name: str = "WealthPulse"

    # Admin auth (pilot): if admin_password is empty, auth is disabled (local dev convenience).
    admin_password: str = ""
    admin_token_secret: str = ""
    admin_token_ttl_hours: int = 24


settings = Settings()
