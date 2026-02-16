#!/usr/bin/env bash
set -euo pipefail

OUT_FILE="${1:-/tmp/wealthpulse_social_sample.csv}"

cat >"$OUT_FILE" <<'CSV'
ticker,bucket_start,mentions,sentiment_hint,source,bucket_minutes
CTRI,2025-11-14T14:00:00,42,0.6,sample_listener,15
CTRI,2025-11-14T14:15:00,45,0.5,sample_listener,15
CTRI,2025-11-14T14:30:00,40,0.4,sample_listener,15
TSLA,2025-11-14T14:00:00,28,0.2,sample_listener,15
TSLA,2025-11-14T14:15:00,31,0.3,sample_listener,15
NVDA,2025-11-14T14:00:00,22,0.4,sample_listener,15
NVDA,2025-11-14T14:15:00,21,0.4,sample_listener,15
AAPL,2025-11-14T14:00:00,18,0.1,sample_listener,15
MU,2025-11-14T14:00:00,14,-0.1,sample_listener,15
MU,2025-11-14T14:15:00,12,-0.2,sample_listener,15
CSV

echo "Wrote sample social CSV: $OUT_FILE"
echo "Next:"
echo "  cd backend"
echo "  python -m app.cli ingest-social-signals-csv --csv-file \"$OUT_FILE\""
