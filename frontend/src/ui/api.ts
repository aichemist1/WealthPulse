export type ApiConfig = {
  baseUrl: string;
};

const defaultBaseUrl = (import.meta as any).env?.VITE_API_BASE_URL || "";

export const apiConfig: ApiConfig = {
  baseUrl: defaultBaseUrl,
};

async function apiGet<T>(path: string): Promise<T> {
  const url = apiConfig.baseUrl ? `${apiConfig.baseUrl}${path}` : path;
  const resp = await fetch(url, { headers: { Accept: "application/json" } });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${txt}`);
  }
  return (await resp.json()) as T;
}

async function apiPost<T>(path: string, body: unknown = null): Promise<T> {
  const url = apiConfig.baseUrl ? `${apiConfig.baseUrl}${path}` : path;
  const resp = await fetch(url, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: body == null ? null : JSON.stringify(body),
  });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${txt}`);
  }
  return (await resp.json()) as T;
}

export type AdminMetrics = {
  counts: {
    "13f_reports": number;
    "13f_distinct_cusips": number;
    "security_mapped_cusips": number;
  };
  coverage: {
    "cusip_to_ticker_ratio": number | null;
  };
};

export type Latest13FWhales = {
  as_of: string | null;
  run_id?: string;
  params?: Record<string, unknown>;
  rows: Array<{
    cusip: string;
    ticker: string | null;
    name: string | null;
    total_value_usd: number;
    delta_value_usd: number;
    manager_count: number;
    manager_increase_count: number;
    manager_decrease_count: number;
  }>;
};

export type LatestInsiderWhales = {
  as_of: string | null;
  run_id?: string;
  params?: Record<string, unknown>;
  rows: Array<{
    ticker: string;
    total_purchase_value: number;
    purchase_tx_count: number;
    latest_event_date: string | null;
  }>;
};

export type WatchlistRows = {
  as_of: string | null;
  rows: Array<{
    ticker: string;
    as_of_date: string | null;
    close: number | null;
    sma50: number | null;
    sma200: number | null;
    return_20d: number | null;
    return_60d: number | null;
    bullish_recent: boolean | null;
    bearish_recent: boolean | null;
    volume: number | null;
    volume_avg20: number | null;
    volume_ratio: number | null;
    dividend_yield_ttm?: number | null;
    payout_ratio?: number | null;
    ex_dividend_date?: string | null;
    dividend_as_of?: string | null;
  }>;
};

export const api = {
  adminMetrics: () => apiGet<AdminMetrics>("/admin/metrics"),
  latest13FWhales: () => apiGet<Latest13FWhales>("/admin/snapshots/13f-whales/latest"),
  latestInsiderWhales: () => apiGet<LatestInsiderWhales>("/admin/snapshots/insider-whales/latest"),
  latestRecommendations: () =>
    apiGet<{
      as_of: string | null;
      run_id?: string;
      params?: Record<string, unknown>;
      rows: Array<{
        ticker: string;
        segment: string;
        action: string;
        direction: string;
        score: number;
        confidence: number;
        reasons: Record<string, unknown>;
      }>;
    }>("/admin/recommendations/latest"),
  latestFreshSignals: () =>
    apiGet<{
      as_of: string | null;
      run_id?: string;
      params?: Record<string, unknown>;
      rows: Array<{
        ticker: string;
        segment: string;
        action: string;
        direction: string;
        score: number;
        confidence: number;
        reasons: Record<string, unknown>;
      }>;
    }>("/admin/fresh-signals/latest"),
  listSnapshotRuns: (kind?: string) =>
    apiGet<{ runs: Array<{ id: string; kind: string; as_of: string; params: Record<string, unknown>; created_at: string }> }>(
      `/admin/snapshots/runs${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`,
    ),
  get13FWhalesRun: (runId: string) => apiGet<Latest13FWhales>(`/admin/snapshots/13f-whales/run/${runId}`),
  getInsiderWhalesRun: (runId: string) => apiGet<LatestInsiderWhales>(`/admin/snapshots/insider-whales/run/${runId}`),
  watchlistEtfs: () => apiGet<WatchlistRows>("/admin/watchlists/etfs"),
  watchlistDividends: () => apiGet<WatchlistRows>("/admin/watchlists/dividends"),
  latestAlerts: (unreadOnly: boolean = false) =>
    apiGet<{ rows: Array<{ id: string; kind: string; ticker: string | null; severity: string; title: string; body: string; payload: Record<string, unknown>; created_at: string; read_at: string | null }> }>(
      `/admin/alerts/latest?unread_only=${unreadOnly ? "true" : "false"}&limit=30`,
    ),
  ackAlert: (alertId: string) => apiPost<{ ok: boolean }>(`/admin/alerts/${encodeURIComponent(alertId)}/ack`),
};
