export type ApiConfig = {
  baseUrl: string;
};

const envBaseUrl = String((import.meta as any).env?.VITE_API_BASE_URL || "").trim();
// Production default: when the UI is served by our reverse proxy, the backend is reachable at /api.
// Dev overrides should set VITE_API_BASE_URL explicitly (run_demo_dashboard.sh already does this).
const defaultBaseUrl = envBaseUrl || "/api";
const tokenStorageKey = "wealthpulse_admin_token";

export const apiConfig: ApiConfig = {
  baseUrl: defaultBaseUrl,
};

export function getAdminToken(): string {
  try {
    return String(localStorage.getItem(tokenStorageKey) || "");
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  try {
    if (!token) localStorage.removeItem(tokenStorageKey);
    else localStorage.setItem(tokenStorageKey, token);
  } catch {
    // ignore
  }
}

function authHeaders(): Record<string, string> {
  const t = getAdminToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function apiGet<T>(path: string): Promise<T> {
  const url = apiConfig.baseUrl ? `${apiConfig.baseUrl}${path}` : path;
  const resp = await fetch(url, { headers: { Accept: "application/json", ...authHeaders() } });
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
    headers: { Accept: "application/json", "Content-Type": "application/json", ...authHeaders() },
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

export type LatestSegments = {
  as_of: string;
  segments: Array<{
    key: string;
    name: string;
    as_of: string | null;
    picks: Array<{
      ticker: string;
      score: number;
      action: string;
      confidence: number;
      why: string;
      source_kind: "recommendations_v0" | "fresh_signals_v0";
    }>;
  }>;
};

export type AdminSettingKV = {
  key: string;
  value: Record<string, unknown>;
};

export const api = {
  authStatus: () => apiGet<{ enabled: boolean; ttl_hours: number }>("/admin/auth/status"),
  adminLogin: (password: string) =>
    apiPost<{ ok: boolean; token?: string; expires_at?: number; error?: string }>("/admin/auth/login", { password }),
  listSubscribers: (status: string = "", limit: number = 200) =>
    apiGet<{
      counts: Record<string, number>;
      rows: Array<{ email: string; status: string; created_at: string | null; confirmed_at: string | null; unsubscribed_at: string | null }>;
    }>(`/admin/subscribers?status=${encodeURIComponent(status)}&limit=${encodeURIComponent(String(limit))}`),
  manualAddSubscriber: (email: string, status: "pending" | "active" = "active") =>
    apiPost<{ ok: boolean; email?: string; status?: string; error?: string }>("/admin/subscribers/manual-add", { email, status }),
  inviteSubscriber: (email: string) =>
    apiPost<{ ok: boolean; status?: string; error?: string }>("/subscribe", { email }),
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
  latestSubscriberAlertDraft: () =>
    apiGet<{
      ok: boolean;
      run: { id: string; as_of: string; created_at: string; status: string; sent_at: string | null; policy: Record<string, unknown> } | null;
      items: Array<{ ticker: string; action: string; segment: string; score: number; confidence: number; why: Array<string>; evidence: Record<string, unknown> }>;
    }>("/admin/subscriber-alerts/draft/latest"),
  latestSegments: () => apiGet<LatestSegments>("/admin/segments/latest"),
  getSubscriberAlertPolicyV0: () => apiGet<AdminSettingKV>("/admin/settings/subscriber-alert-policy-v0"),
  setSubscriberAlertPolicyV0: (value: Record<string, unknown>) =>
    apiPost<{ ok: boolean; value?: Record<string, unknown>; error?: string }>("/admin/settings/subscriber-alert-policy-v0", { value }),
  createSubscriberAlertDraft: (asOf?: string) =>
    apiPost<{
      ok: boolean;
      run?: {
        id: string;
        as_of: string;
        created_at: string;
        status: string;
        sent_at: string | null;
        items_count: number;
        diff: any;
      };
      error?: string;
    }>("/admin/subscriber-alerts/draft", asOf ? { as_of: asOf } : {}),
  sendSubscriberAlertRun: (runId: string, limitSubscribers: number = 0) =>
    apiPost<{
      ok: boolean;
      result?: { status: string; subscribers_seen: number; sent: number; failed: number; skipped: number; changed: boolean; run_id: string };
      run?: { id: string; status: string; sent_at: string | null } | null;
      error?: string;
    }>(`/admin/subscriber-alerts/run/${encodeURIComponent(runId)}/send`, { limit_subscribers: limitSubscribers }),
  sendSubscriberAlertItem: (sourceRunId: string, ticker: string, limitSubscribers: number = 0) =>
    apiPost<{
      ok: boolean;
      source_run_id?: string;
      new_run_id?: string;
      result?: { status: string; subscribers_seen: number; sent: number; failed: number; skipped: number; changed: boolean; run_id: string };
      run?: { id: string; status: string; sent_at: string | null } | null;
      error?: string;
    }>(`/admin/subscriber-alerts/run/${encodeURIComponent(sourceRunId)}/send-item`, { ticker, limit_subscribers: limitSubscribers }),
  listSubscriberAlertRuns: (days: number = 5) =>
    apiGet<{
      days: number;
      runs: Array<{
        id: string;
        as_of: string;
        created_at: string;
        status: string;
        sent_at: string | null;
        items_count: number;
        deliveries: Record<string, number>;
        diff: any;
      }>;
    }>(
      `/admin/subscriber-alerts/runs?days=${encodeURIComponent(String(days))}&limit=50`,
    ),
  getSubscriberAlertRun: (runId: string) =>
    apiGet<{
      ok: boolean;
      run?: {
        id: string;
        as_of: string;
        created_at: string;
        status: string;
        sent_at: string | null;
        policy: Record<string, unknown>;
        source_runs: Record<string, unknown>;
      };
      items?: Array<{ ticker: string; action: string; segment: string; score: number; confidence: number; why: Array<string>; evidence: Record<string, unknown> }>;
      deliveries?: Array<{ email: string; delivery: { status: string; queued_at: string; sent_at: string | null; error: string | null } }>;
      error?: string;
    }>(`/admin/subscriber-alerts/run/${encodeURIComponent(runId)}`),
};
