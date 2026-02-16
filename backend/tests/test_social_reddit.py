from datetime import datetime

from app.connectors.social_reddit import extract_tickers_from_text, parse_reddit_listing_to_buckets


def test_extract_tickers_from_text_cashtag_only() -> None:
    text = "Watching $AAPL and $NVDA, also TSLA without cashtag."
    got = extract_tickers_from_text(text, allow_plain_upper=False)
    assert got == {"AAPL", "NVDA"}


def test_extract_tickers_from_text_with_plain_upper() -> None:
    text = "AAPL and NVDA look strong; THE should be ignored."
    got = extract_tickers_from_text(text, allow_plain_upper=True)
    assert "AAPL" in got
    assert "NVDA" in got
    assert "THE" not in got


def test_parse_reddit_listing_to_buckets_counts_mentions() -> None:
    payload = {
        "data": {
            "children": [
                {"data": {"created_utc": 1763128800, "title": "Buy $AAPL", "selftext": "adding"}},
                {"data": {"created_utc": 1763128850, "title": "$AAPL and $NVDA", "selftext": ""}},
            ]
        }
    }
    rows = parse_reddit_listing_to_buckets(
        payload=payload,
        source="reddit:stocks",
        bucket_minutes=15,
        since=datetime(2025, 11, 14, 0, 0, 0),
    )
    by_ticker = {r.ticker: r.mentions for r in rows}
    assert by_ticker.get("AAPL") == 2
    assert by_ticker.get("NVDA") == 1
