import React, { useEffect, useMemo, useState } from "react";
import {
  api,
  getAdminToken,
  setAdminToken,
  type AdminMetrics,
  type Latest13FWhales,
  type LatestBacktestRun,
  type LatestInsiderWhales,
  type LatestSegments,
  type SocialCoverage,
  type WatchlistRows,
} from "./api";
import { Money, Percent } from "./format";
import { Drawer } from "./Drawer";

type LoadState<T> = { status: "idle" | "loading" | "error" | "ok"; data?: T; error?: string };

type Tab = "latest" | "runs" | "subscribers";

function clampInt(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}

function scoreTo10(score0to100: number, reasons?: Record<string, unknown>): number {
  const fromReasons = Number((reasons as any)?.conviction_1_10);
  if (!Number.isNaN(fromReasons) && fromReasons > 0) return clampInt(Math.trunc(fromReasons), 1, 10);
  const s = Number(score0to100) || 0;
  return clampInt(Math.ceil(s / 10), 1, 10);
}

export function App() {
  const [tab, setTab] = useState<Tab>("latest");
  const [authStatus, setAuthStatus] = useState<LoadState<{ enabled: boolean; ttl_hours: number }>>({ status: "idle" });
  const [authed, setAuthed] = useState<boolean>(false);
  const [loginPw, setLoginPw] = useState<string>("");
  const [loginErr, setLoginErr] = useState<string>("");
  const [metrics, setMetrics] = useState<LoadState<AdminMetrics>>({ status: "idle" });
  const [socialCoverage, setSocialCoverage] = useState<LoadState<SocialCoverage>>({ status: "idle" });
  const [backtest, setBacktest] = useState<LoadState<LatestBacktestRun>>({ status: "idle" });
  const [whales13f, setWhales13f] = useState<LoadState<Latest13FWhales>>({ status: "idle" });
  const [whalesInsider, setWhalesInsider] = useState<LoadState<LatestInsiderWhales>>({ status: "idle" });
  const [recs, setRecs] = useState<
    LoadState<{
      as_of: string | null;
      rows: Array<{
        ticker: string;
        segment: string;
        action: string;
        direction: string;
        score: number;
        confidence: number;
        reasons: Record<string, unknown>;
      }>;
    }>
  >({ status: "idle" });
  const [fresh, setFresh] = useState<
    LoadState<{
      as_of: string | null;
      rows: Array<{
        ticker: string;
        segment: string;
        action: string;
        direction: string;
        score: number;
        confidence: number;
        reasons: Record<string, unknown>;
      }>;
    }>
  >({ status: "idle" });
  const [selectedRec, setSelectedRec] = useState<null | {
    ticker: string;
    score: number;
    action: string;
    direction: string;
    confidence: number;
    reasons: Record<string, unknown>;
    segment: string;
  }>(null);
  const [selectedWatch, setSelectedWatch] = useState<null | {
    list: "etfs" | "dividends";
    row: WatchlistRows["rows"][number];
  }>(null);
  const [runs, setRuns] = useState<LoadState<{ runs: Array<{ id: string; kind: string; as_of: string }> }>>({
    status: "idle",
  });
  const [selectedRun, setSelectedRun] = useState<{ kind: "13f_whales" | "insider_whales"; id: string } | null>(null);
  const [runData13f, setRunData13f] = useState<LoadState<Latest13FWhales>>({ status: "idle" });
  const [runDataInsider, setRunDataInsider] = useState<LoadState<LatestInsiderWhales>>({ status: "idle" });
  const [etfs, setEtfs] = useState<LoadState<WatchlistRows>>({ status: "idle" });
  const [divs, setDivs] = useState<LoadState<WatchlistRows>>({ status: "idle" });
  const [alerts, setAlerts] = useState<
    LoadState<{ rows: Array<{ id: string; severity: string; title: string; body: string; created_at: string; read_at: string | null }> }>
  >({ status: "idle" });
  const [subscriberDraft, setSubscriberDraft] = useState<
    LoadState<{
      ok: boolean;
      run: { id: string; as_of: string; created_at: string; status: string; sent_at: string | null; policy: Record<string, unknown> } | null;
      items: Array<{ ticker: string; action: string; segment: string; score: number; confidence: number; why: Array<string>; evidence: Record<string, unknown> }>;
    }>
  >({ status: "idle" });
  const [segments, setSegments] = useState<LoadState<LatestSegments>>({ status: "idle" });
  const [policy, setPolicy] = useState<
    LoadState<{ key: string; value: { max_items: number; min_confidence: number; min_score_buy: number; min_score_sell: number; fresh_days: number } }>
  >({ status: "idle" });
  const [policyDraft, setPolicyDraft] = useState<{
    max_items: string;
    min_confidence: string;
    min_score_buy: string;
    min_score_sell: string;
    fresh_days: string;
  } | null>(null);
  const [policySaveMsg, setPolicySaveMsg] = useState<string>("");
  const [subscriberRuns, setSubscriberRuns] = useState<
    LoadState<{
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
    }>
  >({ status: "idle" });
  const [selectedSubscriberRunId, setSelectedSubscriberRunId] = useState<string | null>(null);
  const [subscriberRunDetail, setSubscriberRunDetail] = useState<
    LoadState<{
      ok: boolean;
      run?: { id: string; as_of: string; created_at: string; status: string; sent_at: string | null; policy: Record<string, unknown>; source_runs: Record<string, unknown> };
      items?: Array<{ ticker: string; action: string; segment: string; score: number; confidence: number; why: Array<string>; evidence: Record<string, unknown> }>;
      deliveries?: Array<{ email: string; delivery: { status: string; queued_at: string; sent_at: string | null; error: string | null } }>;
      error?: string;
    }>
  >({ status: "idle" });
  const [subscriberOpsMsg, setSubscriberOpsMsg] = useState<string>("");
  const [subscriberSendLimit, setSubscriberSendLimit] = useState<string>("0");
  const [subs, setSubs] = useState<
    LoadState<{
      counts: Record<string, number>;
      rows: Array<{ email: string; status: string; created_at: string | null; confirmed_at: string | null; unsubscribed_at: string | null }>;
    }>
  >({ status: "idle" });
  const [subsStatusFilter, setSubsStatusFilter] = useState<string>("");
  const [inviteEmail, setInviteEmail] = useState<string>("");
  const [inviteMsg, setInviteMsg] = useState<string>("");
  const [manualEmail, setManualEmail] = useState<string>("");
  const [manualMsg, setManualMsg] = useState<string>("");
  const avoidFresh = useMemo(() => {
    const rows = fresh.data?.rows ?? [];
    return rows.filter((r) => r.action === "avoid");
  }, [fresh.data]);

  useEffect(() => {
    setAuthStatus({ status: "loading" });
    api.authStatus()
      .then((s) => {
        setAuthStatus({ status: "ok", data: s });
        if (!s.enabled) {
          setAuthed(true);
          return;
        }
        const tok = getAdminToken();
        if (!tok) {
          setAuthed(false);
          return;
        }
        // Validate token by calling a cheap admin endpoint.
        api.adminMetrics()
          .then(() => setAuthed(true))
          .catch(() => {
            setAdminToken("");
            setAuthed(false);
          });
      })
      .catch((e) => {
        setAuthStatus({ status: "error", error: String(e) });
        // If status endpoint fails, fall back to the old behavior (no auth gating).
        setAuthed(true);
      });
  }, []);

  useEffect(() => {
    if (!authed) return;
    setMetrics({ status: "loading" });
    api.adminMetrics()
      .then((data) => setMetrics({ status: "ok", data }))
      .catch((e) => setMetrics({ status: "error", error: String(e) }));

    setWhales13f({ status: "loading" });
    api.latest13FWhales()
      .then((data) => setWhales13f({ status: "ok", data }))
      .catch((e) => setWhales13f({ status: "error", error: String(e) }));

    setWhalesInsider({ status: "loading" });
    api.latestInsiderWhales()
      .then((data) => setWhalesInsider({ status: "ok", data }))
      .catch((e) => setWhalesInsider({ status: "error", error: String(e) }));

    setRecs({ status: "loading" });
    api.latestRecommendations()
      .then((data) => setRecs({ status: "ok", data }))
      .catch((e) => setRecs({ status: "error", error: String(e) }));

    setFresh({ status: "loading" });
    api.latestFreshSignals()
      .then((data) => setFresh({ status: "ok", data }))
      .catch((e) => setFresh({ status: "error", error: String(e) }));

    setEtfs({ status: "loading" });
    api.watchlistEtfs()
      .then((data) => setEtfs({ status: "ok", data }))
      .catch((e) => setEtfs({ status: "error", error: String(e) }));

    setDivs({ status: "loading" });
    api.watchlistDividends()
      .then((data) => setDivs({ status: "ok", data }))
      .catch((e) => setDivs({ status: "error", error: String(e) }));

    setSubscriberDraft({ status: "loading" });
    api.latestSubscriberAlertDraft()
      .then((data) => setSubscriberDraft({ status: "ok", data }))
      .catch((e) => setSubscriberDraft({ status: "error", error: String(e) }));

    setSegments({ status: "loading" });
    api.latestSegments()
      .then((data) => setSegments({ status: "ok", data }))
      .catch((e) => setSegments({ status: "error", error: String(e) }));

    setPolicy({ status: "loading" });
    api.getSubscriberAlertPolicyV0()
      .then((data: any) => {
        const v = data.value || {};
        const parsed = {
          key: String(data.key || "subscriber_alert_policy_v0"),
          value: {
            max_items: Number(v.max_items ?? 5),
            min_confidence: Number(v.min_confidence ?? 0.3),
            min_score_buy: Number(v.min_score_buy ?? 75),
            min_score_sell: Number(v.min_score_sell ?? 35),
            fresh_days: Number(v.fresh_days ?? 7),
          },
        };
        setPolicy({ status: "ok", data: parsed });
        setPolicyDraft({
          max_items: String(parsed.value.max_items),
          min_confidence: String(parsed.value.min_confidence),
          min_score_buy: String(parsed.value.min_score_buy),
          min_score_sell: String(parsed.value.min_score_sell),
          fresh_days: String(parsed.value.fresh_days),
        });
      })
      .catch((e) => setPolicy({ status: "error", error: String(e) }));
  }, [authed]);

  useEffect(() => {
    if (tab !== "runs") return;
    if (!authed) return;
    setRuns({ status: "loading" });
    api.listSnapshotRuns()
      .then((data) => setRuns({ status: "ok", data: { runs: data.runs.map((r) => ({ id: r.id, kind: r.kind, as_of: r.as_of })) } }))
      .catch((e) => setRuns({ status: "error", error: String(e) }));

    setSubscriberRuns({ status: "loading" });
    api.listSubscriberAlertRuns(5)
      .then((data) => setSubscriberRuns({ status: "ok", data }))
      .catch((e) => setSubscriberRuns({ status: "error", error: String(e) }));

    setSocialCoverage({ status: "loading" });
    api.socialCoverage(24, 10)
      .then((data) => setSocialCoverage({ status: "ok", data }))
      .catch((e) => setSocialCoverage({ status: "error", error: String(e) }));

    setBacktest({ status: "loading" });
    api.latestBacktestRun()
      .then((data) => setBacktest({ status: "ok", data }))
      .catch((e) => setBacktest({ status: "error", error: String(e) }));
  }, [tab]);

  useEffect(() => {
    if (tab !== "subscribers") return;
    if (!authed) return;
    setSubs({ status: "loading" });
    api.listSubscribers(subsStatusFilter, 200)
      .then((data) => setSubs({ status: "ok", data }))
      .catch((e) => setSubs({ status: "error", error: String(e) }));
  }, [tab, authed, subsStatusFilter]);

  useEffect(() => {
    if (!selectedSubscriberRunId) return;
    if (!authed) return;
    setSubscriberRunDetail({ status: "loading" });
    api.getSubscriberAlertRun(selectedSubscriberRunId)
      .then((data) => setSubscriberRunDetail({ status: "ok", data }))
      .catch((e) => setSubscriberRunDetail({ status: "error", error: String(e) }));
  }, [selectedSubscriberRunId]);

  useEffect(() => {
    if (!selectedRun) return;
    if (!authed) return;
    if (selectedRun.kind === "13f_whales") {
      setRunData13f({ status: "loading" });
      api.get13FWhalesRun(selectedRun.id)
        .then((data) => setRunData13f({ status: "ok", data }))
        .catch((e) => setRunData13f({ status: "error", error: String(e) }));
    } else {
      setRunDataInsider({ status: "loading" });
      api.getInsiderWhalesRun(selectedRun.id)
        .then((data) => setRunDataInsider({ status: "ok", data }))
        .catch((e) => setRunDataInsider({ status: "error", error: String(e) }));
    }
  }, [selectedRun]);

  const coveragePct = useMemo(() => {
    const v = metrics.data?.coverage.cusip_to_ticker_ratio;
    return typeof v === "number" ? v : null;
  }, [metrics.data]);

  const split13f = useMemo(() => {
    const rows = whales13f.data?.rows ?? [];
    const accumulators = rows.filter((r) => r.delta_value_usd > 0);
    const disposers = rows.filter((r) => r.delta_value_usd < 0);
    return { accumulators, disposers };
  }, [whales13f.data]);

  const split13fRun = useMemo(() => {
    const rows = runData13f.data?.rows ?? [];
    return {
      accumulators: rows.filter((r) => r.delta_value_usd > 0),
      disposers: rows.filter((r) => r.delta_value_usd < 0),
    };
  }, [runData13f.data]);

  const authEnabled = authStatus.status === "ok" && !!authStatus.data?.enabled;

  if (authStatus.status === "loading") {
    return (
      <div className="page">
        <header className="header">
          <div>
            <div className="title">WealthPulse Admin</div>
            <div className="subtitle">Loading…</div>
          </div>
        </header>
      </div>
    );
  }

  if (authEnabled && !authed) {
    const doLogin = () => {
      setLoginErr("");
      api.adminLogin(loginPw)
        .then((resp: any) => {
          if (!resp.ok || !resp.token) {
            setLoginErr(String(resp.error || "Login failed"));
            return;
          }
          setAdminToken(String(resp.token));
          setAuthed(true);
          setLoginPw("");
        })
        .catch((e) => setLoginErr(String(e)));
    };

    return (
      <div className="page">
        <div className="loginShell">
          <div className="card loginCard">
            <div className="loginTop">
              <div className="loginMark">WP</div>
              <div>
                <div className="loginTitle">WealthPulse Admin</div>
                <div className="muted loginSubtitle">Sign in to review today’s subscriber alerts and runs.</div>
              </div>
            </div>

            <div className="loginRow">
              <input
                className="loginInput"
                type="password"
                value={loginPw}
                onChange={(e) => setLoginPw(e.target.value)}
                placeholder="Admin password"
                onKeyDown={(e) => {
                  if (e.key === "Enter") doLogin();
                }}
                autoFocus
              />
              <button className="btnSmall btnPrimary" onClick={doLogin}>
                Login
              </button>
            </div>

            {loginErr ? (
              <div className="loginErrBox">
                <div className="error">{loginErr}</div>
              </div>
            ) : null}

            <div className="muted" style={{ marginTop: 10 }}>
              Auth is enabled via backend env `WEALTHPULSE_ADMIN_PASSWORD`.
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="header">
        <div>
          <div className="title">WealthPulse Admin</div>
          <div className="subtitle">Snapshots + whale signals (v0)</div>
        </div>
        {authEnabled ? (
          <button
            className="btnSmall"
            onClick={() => {
              setAdminToken("");
              setAuthed(false);
              setTab("latest");
            }}
          >
            Logout
          </button>
        ) : null}
        <div className="tabs">
          <button className={tab === "latest" ? "tab active" : "tab"} onClick={() => setTab("latest")}>
            Latest
          </button>
          <button className={tab === "runs" ? "tab active" : "tab"} onClick={() => setTab("runs")}>
            Runs
          </button>
          <button className={tab === "subscribers" ? "tab active" : "tab"} onClick={() => setTab("subscribers")}>
            Subscribers
          </button>
        </div>
      </header>

      {tab === "latest" && (
        <section className="grid gridLatest">
          <div className="card span2">
            <div className="cardTitle">Themes</div>
            <div className="muted">One ticker appears in one segment (priority + score).</div>
            {segments.status === "loading" && <div className="muted">Loading…</div>}
            {segments.status === "error" && <div className="error">{segments.error}</div>}
            {segments.status === "ok" && segments.data && (
              <div className="themesGrid">
                {segments.data.segments.map((s) => (
                  <div key={s.key} className="themeBucket">
                    <div className="themeTitle">{s.name}</div>
                    <div className="muted">{s.as_of ? `as_of: ${s.as_of}` : "no data yet"}</div>
                    <div className="themePicks">
                      {(s.picks ?? []).length === 0 ? (
                        <div className="muted" style={{ marginTop: 6 }}>
                          —
                        </div>
                      ) : null}
                      {(s.picks ?? []).map((p) => (
                        <button
                          key={`${s.key}-${p.ticker}`}
                          className="themePick"
                          onClick={() => {
                            const sourceRows =
                              p.source_kind === "recommendations_v0" ? recs.data?.rows ?? [] : fresh.data?.rows ?? [];
                            const found = sourceRows.find((r) => r.ticker === p.ticker);
                            if (!found) return;
                            setSelectedRec({
                              ticker: found.ticker,
                              score: found.score,
                              action: found.action,
                              direction: found.direction,
                              confidence: found.confidence,
                              reasons: found.reasons,
                              segment: found.segment,
                            });
                          }}
                        >
                          <div className="themePickTop">
                            <span className="mono">{p.ticker}</span>
                            <span className="muted">{p.action.toUpperCase()}</span>
                          </div>
                          <div className="muted">
                            Score {scoreTo10(p.score, (p as any).reasons)} · Conf {(p.confidence * 100).toFixed(0)}%
                          </div>
                          <div className="muted">{p.why}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="card">
            <div className="cardTitle">Top Picks (v0)</div>
            <div className="muted">Score is 1–10 (derived). Buy requires corroboration (13F is delayed).</div>
            {recs.status === "loading" && <div className="muted">Loading…</div>}
            {recs.status === "error" && <div className="error">{recs.error}</div>}
            {recs.status === "ok" && recs.data && (
              <>
                <div className="muted">as_of: {recs.data.as_of ?? "n/a"}</div>
                {recs.data.rows.length === 0 ? (
                  <div className="muted" style={{ marginTop: 8 }}>
                    No rows yet. Run the demo script again to regenerate snapshots, or run
                    <span className="mono"> snapshot-recommendations-v0 </span>
                    after 13F ingestion + OpenFIGI enrichment.
                  </div>
                ) : null}
                <table className="table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Ticker</th>
                      <th className="num">Score(1–10)</th>
                      <th>Action</th>
                      <th className="num">Conf</th>
                      <th>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recs.data.rows.slice(0, 10).map((r, idx) => (
                      <tr
                        key={`${r.ticker}-${idx}`}
                        style={{ cursor: "pointer" }}
                        onClick={() =>
                          setSelectedRec({
                            ticker: r.ticker,
                            score: r.score,
                            action: r.action,
                            direction: r.direction,
                            confidence: r.confidence,
                            reasons: r.reasons,
                            segment: r.segment,
                          })
                        }
                      >
                        <td className="muted">{idx + 1}</td>
                        <td>{r.ticker}</td>
                        <td className="num">{scoreTo10(r.score, r.reasons)}</td>
                        <td>{r.action}</td>
                        <td className="num">{(r.confidence * 100).toFixed(0)}%</td>
                        <td className="muted">
                          {String((r.reasons as any)?.signal ?? "13F signal")} · Δ{" "}
                          <Money value={Number((r.reasons as any)?.delta_value_usd ?? 0)} /> · mgrs{" "}
                          {Number((r.reasons as any)?.breadth?.increase ?? 0)}/{Number((r.reasons as any)?.breadth?.total ?? 0)}
                          {" · "}
                          SC13 {((r.reasons as any)?.corroborators?.sc13_recent ? "yes" : "no")} / Insider{" "}
                          {((r.reasons as any)?.corroborators?.insider_buy_recent ? "yes" : "no")}
                          {" / "}
                          Trend {((r.reasons as any)?.corroborators?.trend_bullish_recent ? "yes" : "no")}
                          {" · "}
                          Whale {Number((r.reasons as any)?.whale_score ?? r.score)} {Number((r.reasons as any)?.trend_adjustment ?? 0) >= 0 ? "+" : ""}
                          {Number((r.reasons as any)?.trend_adjustment ?? 0)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="card">
            <div className="cardTitle">Fresh Whale Signals (v0)</div>
            <div className="muted">Score is 1–10 (derived). Primarily SC 13D/13G + Form 4 (fresh) with trend/volume confirmation. Technical guardrail is applied when price data is available.</div>
            {fresh.status === "loading" && <div className="muted">Loading…</div>}
            {fresh.status === "error" && <div className="error">{fresh.error}</div>}
            {fresh.status === "ok" && fresh.data && (
              <>
                <div className="muted">as_of: {fresh.data.as_of ?? "n/a"}</div>
                {fresh.data.rows.length === 0 ? (
                  <div className="muted" style={{ marginTop: 8 }}>
                    No rows yet. Run <span className="mono">snapshot-fresh-signals-v0</span> after SC13/Form4 + prices ingestion.
                  </div>
                ) : null}
                <table className="table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Ticker</th>
                      <th className="num">Score(1–10)</th>
                      <th>Action</th>
                      <th className="num">Conf</th>
                      <th>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fresh.data.rows.slice(0, 10).map((r, idx) => (
                      <tr
                        key={`${r.ticker}-${idx}`}
                        style={{ cursor: "pointer" }}
                        onClick={() =>
                          setSelectedRec({
                            ticker: r.ticker,
                            score: r.score,
                            action: r.action,
                            direction: r.direction,
                            confidence: r.confidence,
                            reasons: r.reasons,
                            segment: r.segment,
                          })
                        }
                      >
                        <td className="muted">{idx + 1}</td>
                        <td>{r.ticker}</td>
                        <td className="num">{scoreTo10(r.score, r.reasons)}</td>
                        <td>{r.action}</td>
                        <td className="num">{(r.confidence * 100).toFixed(0)}%</td>
                        <td className="muted">
                          SC13 {Number((r.reasons as any)?.sc13?.count ?? 0)} · Insider net{" "}
                          <Money value={Number((r.reasons as any)?.insider?.net_value ?? 0)} /> · Trend{" "}
                          {((r.reasons as any)?.trend_flags?.bullish_recent
                            ? "bull"
                            : (r.reasons as any)?.trend_flags?.bearish_recent
                              ? "bear"
                              : "n/a")}{" "}
                          · Vol {((r.reasons as any)?.volume?.spike ? "spike" : "—")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="card">
            <div className="cardTitle">High-Yield Dividend Stocks</div>
            <div className="muted">Curated income names with yield + payout (best-effort).</div>
            {divs.status === "loading" && <div className="muted">Loading…</div>}
            {divs.status === "error" && <div className="error">{divs.error}</div>}
            {divs.status === "ok" && divs.data && (
              <>
                <div className="muted">as_of: {divs.data.as_of ?? "n/a"}</div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th className="num">Yield</th>
                      <th className="num">Payout</th>
                      <th className="num">Close</th>
                      <th className="num">20D</th>
                      <th className="num">60D</th>
                      <th>Trend</th>
                      <th className="num">Vol</th>
                    </tr>
                  </thead>
                  <tbody>
                    {divs.data.rows.map((r) => (
                      <tr
                        key={r.ticker}
                        style={{ cursor: "pointer" }}
                        onClick={() => setSelectedWatch({ list: "dividends", row: r })}
                      >
                        <td>{r.ticker}</td>
                        <td className="num">
                          {r.dividend_yield_ttm == null ? "n/a" : `${(Number(r.dividend_yield_ttm) * 100).toFixed(1)}%`}
                        </td>
                        <td className="num">{r.payout_ratio == null ? "n/a" : `${(Number(r.payout_ratio) * 100).toFixed(0)}%`}</td>
                        <td className="num">{r.close == null ? "n/a" : <Money value={Number(r.close ?? 0)} />}</td>
                        <td className="num">{r.return_20d == null ? "n/a" : `${(r.return_20d * 100).toFixed(1)}%`}</td>
                        <td className="num">{r.return_60d == null ? "n/a" : `${(r.return_60d * 100).toFixed(1)}%`}</td>
                        <td className="muted">{r.bullish_recent ? "bull" : r.bearish_recent ? "bear" : "n/a"}</td>
                        <td className="num">{r.volume_ratio == null ? "n/a" : `${r.volume_ratio.toFixed(2)}x`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="card">
            <div className="cardTitle">ETF / Macro Plays</div>
            <div className="muted">Curated ETFs with trend + 20D/60D returns.</div>
            {etfs.status === "loading" && <div className="muted">Loading…</div>}
            {etfs.status === "error" && <div className="error">{etfs.error}</div>}
            {etfs.status === "ok" && etfs.data && (
              <>
                <div className="muted">as_of: {etfs.data.as_of ?? "n/a"}</div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th className="num">Close</th>
                      <th className="num">20D</th>
                      <th className="num">60D</th>
                      <th>Trend</th>
                      <th className="num">Vol</th>
                    </tr>
                  </thead>
                  <tbody>
                    {etfs.data.rows.map((r) => (
                      <tr
                        key={r.ticker}
                        style={{ cursor: "pointer" }}
                        onClick={() => setSelectedWatch({ list: "etfs", row: r })}
                      >
                        <td>{r.ticker}</td>
                        <td className="num">{r.close == null ? "n/a" : <Money value={Number(r.close ?? 0)} />}</td>
                        <td className="num">{r.return_20d == null ? "n/a" : `${(r.return_20d * 100).toFixed(1)}%`}</td>
                        <td className="num">{r.return_60d == null ? "n/a" : `${(r.return_60d * 100).toFixed(1)}%`}</td>
                        <td className="muted">{r.bullish_recent ? "bull" : r.bearish_recent ? "bear" : "n/a"}</td>
                        <td className="num">{r.volume_ratio == null ? "n/a" : `${r.volume_ratio.toFixed(2)}x`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="card">
            <div className="cardTitle">Avoid / Risk (v0)</div>
            <div className="muted">Fresh bearish signals (insider selling + bearish trend); 13F shown only as context.</div>
            {fresh.status === "loading" && <div className="muted">Loading…</div>}
            {fresh.status === "error" && <div className="error">{fresh.error}</div>}
            {fresh.status === "ok" && fresh.data && (
              <>
                <div className="muted">as_of: {fresh.data.as_of ?? "n/a"}</div>
                {avoidFresh.length === 0 ? <div className="muted" style={{ marginTop: 8 }}>No avoid rows in this snapshot.</div> : null}
                <table className="table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Ticker</th>
                      <th className="num">Score(1–10)</th>
                      <th>Action</th>
                      <th className="num">Conf</th>
                      <th>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {avoidFresh.slice(0, 10).map((r, idx) => (
                      <tr
                        key={`${r.ticker}-avoid-${idx}`}
                        style={{ cursor: "pointer" }}
                        onClick={() =>
                          setSelectedRec({
                            ticker: r.ticker,
                            score: r.score,
                            action: r.action,
                            direction: r.direction,
                            confidence: r.confidence,
                            reasons: r.reasons,
                            segment: r.segment,
                          })
                        }
                      >
                        <td className="muted">{idx + 1}</td>
                        <td>{r.ticker}</td>
                        <td className="num">{scoreTo10(r.score, r.reasons)}</td>
                        <td>{r.action}</td>
                        <td className="num">{(r.confidence * 100).toFixed(0)}%</td>
                        <td className="muted">
                          Insider sell <Money value={Number((r.reasons as any)?.insider?.sell_value ?? 0)} /> · Trend{" "}
                          {((r.reasons as any)?.trend_flags?.bearish_recent ? "bear" : "n/a")} · Vol{" "}
                          {((r.reasons as any)?.volume?.spike ? "spike" : "—")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="card">
            <div className="cardTitle">Insider Whale Buys (Latest Snapshot)</div>
            {whalesInsider.status === "loading" && <div className="muted">Loading…</div>}
            {whalesInsider.status === "error" && <div className="error">{whalesInsider.error}</div>}
            {whalesInsider.status === "ok" && whalesInsider.data && (
              <>
                <div className="muted">as_of: {whalesInsider.data.as_of ?? "n/a"}</div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th className="num">Total Buy Value</th>
                      <th className="num">Tx Count</th>
                      <th>Latest Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {whalesInsider.data.rows.slice(0, 15).map((r) => (
                      <tr key={`${r.ticker}-${r.latest_event_date ?? ""}`}>
                        <td>{r.ticker}</td>
                        <td className="num">
                          <Money value={r.total_purchase_value} />
                        </td>
                        <td className="num">{r.purchase_tx_count}</td>
                        <td>{r.latest_event_date ?? "n/a"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="card span2">
            <div className="cardTitle">Subscriber Alerts</div>

            {subscriberDraft.status === "loading" && <div className="muted">Loading…</div>}
            {subscriberDraft.status === "error" && <div className="error">{subscriberDraft.error}</div>}
            {subscriberDraft.status === "ok" && subscriberDraft.data && (
              <>
                {!subscriberDraft.data.run ? (
                  <div className="muted" style={{ marginTop: 10 }}>
                    No draft yet.
                  </div>
                ) : (
                  <>
                    <table className="table" style={{ marginTop: 8 }}>
                      <thead>
                        <tr>
                          <th>Ticker</th>
                          <th>Action</th>
                          <th className="num">Score(1–10)</th>
                          <th className="num">Conf</th>
                          <th>Why</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {subscriberDraft.data.items.slice(0, 20).map((it) => (
                          <tr key={`${it.ticker}-${it.action}`}>
                            <td className="mono">{it.ticker}</td>
                            <td>{it.action}</td>
                            <td className="num">{scoreTo10(it.score, it.evidence as any)}</td>
                            <td className="num">{Math.round(it.confidence * 100)}%</td>
                            <td className="muted">{(it.why ?? []).slice(0, 2).join(" · ")}</td>
                            <td style={{ textAlign: "right" }}>
                              <button
                                className="btnSmall"
                                onClick={() => {
                                  const runId = subscriberDraft.data?.run?.id;
                                  if (!runId) return;
                                  api
                                    .sendSubscriberAlertItem(runId, it.ticker, 0)
                                    .then((resp) => {
                                      if (!resp.ok) console.error(resp);
                                    })
                                    .catch((e) => console.error(e));
                                }}
                              >
                                Send
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
                      <button
                        className="btnSmall"
                        onClick={() => {
                          const runId = subscriberDraft.data?.run?.id;
                          if (!runId) return;
                          api
                            .sendSubscriberAlertRun(runId, 0)
                            .then((resp) => { if (!resp.ok) console.error(resp); })
                            .then(() => api.latestSubscriberAlertDraft().then((d) => setSubscriberDraft({ status: "ok", data: d })).catch(() => { }))
                            .catch((e) => console.error(e));
                        }}
                      >
                        Send All
                      </button>
                      <div className="muted">This sends the whole draft run.</div>
                    </div>
                  </>
                )}
              </>
            )}
          </div>

          <div className="card span2">
            <div className="cardTitle">Tools: Subscriber Alert Thresholds</div>
            <div className="muted">Controls which BUY/SELL signals are emailed in the pilot (thresholds use raw 0–100 score for now).</div>
            {policy.status === "loading" && <div className="muted">Loading…</div>}
            {policy.status === "error" && <div className="error">{policy.error}</div>}
            {policy.status === "ok" && policyDraft && (
              <>
                <div className="formGrid">
                  <label className="formRow">
                    <span className="muted">Max picks</span>
                    <input value={policyDraft.max_items} onChange={(e) => setPolicyDraft({ ...policyDraft, max_items: e.target.value })} />
                  </label>
                  <label className="formRow">
                    <span className="muted">Min confidence</span>
                    <input
                      value={policyDraft.min_confidence}
                      onChange={(e) => setPolicyDraft({ ...policyDraft, min_confidence: e.target.value })}
                    />
                  </label>
                  <label className="formRow">
                    <span className="muted">Min score (BUY)</span>
                    <input
                      value={policyDraft.min_score_buy}
                      onChange={(e) => setPolicyDraft({ ...policyDraft, min_score_buy: e.target.value })}
                    />
                  </label>
                  <label className="formRow">
                    <span className="muted">Max score (SELL)</span>
                    <input
                      value={policyDraft.min_score_sell}
                      onChange={(e) => setPolicyDraft({ ...policyDraft, min_score_sell: e.target.value })}
                    />
                  </label>
                  <label className="formRow">
                    <span className="muted">Fresh window (days)</span>
                    <input value={policyDraft.fresh_days} onChange={(e) => setPolicyDraft({ ...policyDraft, fresh_days: e.target.value })} />
                  </label>
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
                  <button
                    className="btnSmall"
                    onClick={() => {
                      setPolicySaveMsg("");
                      const value = {
                        max_items: Number(policyDraft.max_items),
                        min_confidence: Number(policyDraft.min_confidence),
                        min_score_buy: Number(policyDraft.min_score_buy),
                        min_score_sell: Number(policyDraft.min_score_sell),
                        fresh_days: Number(policyDraft.fresh_days),
                      };
                      api
                        .setSubscriberAlertPolicyV0(value as any)
                        .then((resp) => {
                          if ((resp as any).ok) setPolicySaveMsg("Saved.");
                          else setPolicySaveMsg(String((resp as any).error || "Failed"));
                        })
                        .catch((e) => setPolicySaveMsg(String(e)));
                    }}
                  >
                    Save
                  </button>
                  {policySaveMsg ? <div className={policySaveMsg === "Saved." ? "muted" : "error"}>{policySaveMsg}</div> : null}
                </div>
              </>
            )}
          </div>
        </section>
      )}

      {tab === "runs" && (
        <section className="grid">
          <div className="card span3">
            <div className="cardTitle">Subscriber Email History (last 5 days)</div>
            <div className="muted">Alert runs + deliveries (sent/failed/skipped). Click a row for details.</div>
            <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
              <button
                className="btnSmall"
                onClick={() => {
                  setSubscriberOpsMsg("Creating draft…");
                  api
                    .createSubscriberAlertDraft()
                    .then((resp) => {
                      if (!resp.ok || !resp.run?.id) {
                        setSubscriberOpsMsg(String((resp as any).error || "Failed to create draft."));
                        return;
                      }
                      setSubscriberOpsMsg(`Draft created: ${resp.run.id.slice(0, 8)} (status=${resp.run.status})`);
                      setSelectedSubscriberRunId(resp.run.id);
                      api.listSubscriberAlertRuns(5).then((data) => setSubscriberRuns({ status: "ok", data })).catch(() => { });
                    })
                    .catch((e) => setSubscriberOpsMsg(String(e)));
                }}
              >
                Generate Draft Now
              </button>
              <div className="muted">Send limit</div>
              <input
                style={{ width: 80 }}
                value={subscriberSendLimit}
                onChange={(e) => setSubscriberSendLimit(e.target.value)}
                title="0 = send to all subscribers"
              />
              {subscriberOpsMsg ? <div className={subscriberOpsMsg.includes("Failed") || subscriberOpsMsg.includes("Error") ? "error" : "muted"}>{subscriberOpsMsg}</div> : null}
            </div>
            {subscriberRuns.status === "loading" && <div className="muted">Loading…</div>}
            {subscriberRuns.status === "error" && <div className="error">{subscriberRuns.error}</div>}
            {subscriberRuns.status === "ok" && subscriberRuns.data && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Created</th>
                    <th>Status</th>
                    <th>Sent</th>
                    <th className="num">Picks</th>
                    <th className="num">Sent</th>
                    <th className="num">Failed</th>
                    <th className="num">Skipped</th>
                    <th>Diff</th>
                    <th className="mono">Run</th>
                  </tr>
                </thead>
                <tbody>
                  {subscriberRuns.data.runs.slice(0, 15).map((r) => (
                    <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => setSelectedSubscriberRunId(r.id)}>
                      <td className="muted">{String(r.created_at).replace("T", " ").slice(0, 19)}</td>
                      <td>{r.status}</td>
                      <td className="muted">{r.sent_at ? String(r.sent_at).replace("T", " ").slice(0, 19) : "—"}</td>
                      <td className="num">{r.items_count}</td>
                      <td className="num">{Number(r.deliveries?.sent ?? 0)}</td>
                      <td className="num">{Number(r.deliveries?.failed ?? 0)}</td>
                      <td className="num">{Number(r.deliveries?.skipped ?? 0)}</td>
                      <td className="muted">{r.diff && (r.diff.changed === false) ? "no change" : "changed"}</td>
                      <td className="mono">{r.id.slice(0, 8)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="card">
            <div className="cardTitle">Coverage</div>
            {metrics.status === "loading" && <div className="muted">Loading…</div>}
            {metrics.status === "error" && <div className="error">{metrics.error}</div>}
            {metrics.status === "ok" && metrics.data && (
              <div className="kv">
                <div className="kvRow">
                  <div className="kvKey">13F reports</div>
                  <div className="kvVal">{metrics.data.counts["13f_reports"]}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Distinct 13F CUSIPs</div>
                  <div className="kvVal">{metrics.data.counts["13f_distinct_cusips"]}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Mapped CUSIPs</div>
                  <div className="kvVal">{metrics.data.counts["security_mapped_cusips"]}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">CUSIP→ticker coverage</div>
                  <div className="kvVal">{coveragePct === null ? "n/a" : <Percent value={coveragePct} />}</div>
                </div>
              </div>
            )}
          </div>

          <div className="card">
            <div className="cardTitle">Social Coverage</div>
            <div className="muted">Listener visibility (last 24h).</div>
            {socialCoverage.status === "loading" && <div className="muted">Loading…</div>}
            {socialCoverage.status === "error" && <div className="error">{socialCoverage.error}</div>}
            {socialCoverage.status === "ok" && socialCoverage.data && (
              <>
                <div className="kv">
                  <div className="kvRow">
                    <div className="kvKey">Enabled</div>
                    <div className="kvVal">{socialCoverage.data.enabled ? "yes" : "no"}</div>
                  </div>
                  <div className="kvRow">
                    <div className="kvKey">Latest bucket</div>
                    <div className="kvVal">{socialCoverage.data.latest_bucket_start ? socialCoverage.data.latest_bucket_start.replace("T", " ").slice(0, 19) : "n/a"}</div>
                  </div>
                  <div className="kvRow">
                    <div className="kvKey">Rows (24h)</div>
                    <div className="kvVal">{socialCoverage.data.rows_window}</div>
                  </div>
                  <div className="kvRow">
                    <div className="kvKey">Tickers (24h)</div>
                    <div className="kvVal">{socialCoverage.data.distinct_tickers_window}</div>
                  </div>
                  <div className="kvRow">
                    <div className="kvKey">Policy</div>
                    <div className="kvVal">
                      v≥{socialCoverage.data.policy.velocity_threshold}, min m={socialCoverage.data.policy.min_mentions}
                    </div>
                  </div>
                </div>
                <table className="table" style={{ marginTop: 8 }}>
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th className="num">Mentions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(socialCoverage.data.top_tickers_window || []).slice(0, 6).map((r) => (
                      <tr key={r.ticker}>
                        <td>{r.ticker}</td>
                        <td className="num">{r.mentions}</td>
                      </tr>
                    ))}
                    {(socialCoverage.data.top_tickers_window || []).length === 0 && (
                      <tr>
                        <td colSpan={2} className="muted">
                          No social rows in window.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="card span2">
            <div className="cardTitle">Backtest (5D/20D)</div>
            <div className="muted">Latest backtest artifact vs baseline.</div>
            {backtest.status === "loading" && <div className="muted">Loading…</div>}
            {backtest.status === "error" && <div className="error">{backtest.error}</div>}
            {backtest.status === "ok" && backtest.data && (
              <>
                {!backtest.data.run ? (
                  <div className="muted">No backtest run yet.</div>
                ) : (
                  <>
                    <div className="muted">
                      baseline: {String(backtest.data.run.summary?.baseline_ticker || "SPY")} · runs: {Number(backtest.data.run.summary?.runs_considered || 0)} · completed: {backtest.data.run.completed_at ? String(backtest.data.run.completed_at).replace("T", " ").slice(0, 19) : "n/a"}
                    </div>
                    <table className="table" style={{ marginTop: 8 }}>
                      <thead>
                        <tr>
                          <th>Source</th>
                          <th>Action</th>
                          <th className="num">H</th>
                          <th className="num">N</th>
                          <th className="num">Cov</th>
                          <th className="num">Hit</th>
                          <th className="num">Excess</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(backtest.data.run.summary?.metrics || []).slice(0, 12).map((m, i) => (
                          <tr key={`${m.source_kind}-${m.action}-${m.horizon_days}-${i}`}>
                            <td>{m.source_kind}</td>
                            <td>{m.action}</td>
                            <td className="num">{m.horizon_days}D</td>
                            <td className="num">{m.evaluated}/{m.attempted}</td>
                            <td className="num">{(Number(m.coverage || 0) * 100).toFixed(0)}%</td>
                            <td className="num">{m.hit_rate_vs_baseline == null ? "n/a" : `${(Number(m.hit_rate_vs_baseline) * 100).toFixed(0)}%`}</td>
                            <td className="num">{m.avg_excess_return == null ? "n/a" : `${(Number(m.avg_excess_return) * 100).toFixed(2)}%`}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
              </>
            )}
          </div>

          <div className="card">
            <div className="cardTitle">Snapshot Runs</div>
            <div className="muted">Click a run to load its rows.</div>
            {runs.status === "loading" && <div className="muted">Loading…</div>}
            {runs.status === "error" && <div className="error">{runs.error}</div>}
            {runs.status === "ok" && runs.data && (
              <div className="runList">
                {runs.data.runs.slice(0, 100).map((r) => (
                  <button
                    key={r.id}
                    className={selectedRun?.id === r.id ? "runItem active" : "runItem"}
                    onClick={() =>
                      setSelectedRun(
                        r.kind === "13f_whales"
                          ? { kind: "13f_whales", id: r.id }
                          : r.kind === "insider_whales"
                            ? { kind: "insider_whales", id: r.id }
                            : null,
                      )
                    }
                    disabled={r.kind !== "13f_whales" && r.kind !== "insider_whales"}
                  >
                    <span className="mono">{r.kind}</span>
                    <span className="muted">{r.as_of}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="card span2">
            <div className="cardTitle">Run Details</div>
            {!selectedRun && <div className="muted">Select a run.</div>}
            {selectedRun?.kind === "13f_whales" && (
              <>
                {runData13f.status === "loading" && <div className="muted">Loading…</div>}
                {runData13f.status === "error" && <div className="error">{runData13f.error}</div>}
                {runData13f.status === "ok" && runData13f.data && (
                  <>
                    <div className="muted">as_of: {runData13f.data.as_of ?? "n/a"}</div>
                    <div className="splitRow">
                      <div className="pill">Accumulators: {split13fRun.accumulators.length}</div>
                      <div className="pill">Disposers: {split13fRun.disposers.length}</div>
                    </div>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Ticker</th>
                          <th>CUSIP</th>
                          <th className="num">Δ Value</th>
                          <th className="num">Total</th>
                          <th className="num">Managers</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runData13f.data.rows.slice(0, 50).map((r) => (
                          <tr key={r.cusip}>
                            <td>{r.ticker ?? "?"}</td>
                            <td className="mono">{r.cusip}</td>
                            <td className="num"><Money value={r.delta_value_usd} /></td>
                            <td className="num"><Money value={r.total_value_usd} /></td>
                            <td className="num">{r.manager_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
              </>
            )}

            {selectedRun?.kind === "insider_whales" && (
              <>
                {runDataInsider.status === "loading" && <div className="muted">Loading…</div>}
                {runDataInsider.status === "error" && <div className="error">{runDataInsider.error}</div>}
                {runDataInsider.status === "ok" && runDataInsider.data && (
                  <>
                    <div className="muted">as_of: {runDataInsider.data.as_of ?? "n/a"}</div>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Ticker</th>
                          <th className="num">Total Buy Value</th>
                          <th className="num">Tx Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runDataInsider.data.rows.slice(0, 50).map((r) => (
                          <tr key={`${r.ticker}-${r.latest_event_date ?? ""}`}>
                            <td>{r.ticker}</td>
                            <td className="num"><Money value={r.total_purchase_value} /></td>
                            <td className="num">{r.purchase_tx_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
              </>
            )}
          </div>

          <div className="card span3">
            <div className="cardTitle">13F Whale Deltas (Latest Snapshot)</div>
            <div className="muted">Raw snapshot output (delayed); use for validation.</div>
            {whales13f.status === "loading" && <div className="muted">Loading…</div>}
            {whales13f.status === "error" && <div className="error">{whales13f.error}</div>}
            {whales13f.status === "ok" && whales13f.data && (
              <>
                <div className="muted">as_of: {whales13f.data.as_of ?? "n/a"}</div>
                <div className="splitRow">
                  <div className="pill">Accumulators: {split13f.accumulators.length}</div>
                  <div className="pill">Disposers: {split13f.disposers.length}</div>
                </div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th>CUSIP</th>
                      <th className="num">Δ Value</th>
                      <th className="num">Total</th>
                      <th className="num">Managers</th>
                      <th className="num">Inc/Dec</th>
                    </tr>
                  </thead>
                  <tbody>
                    {whales13f.data.rows.slice(0, 30).map((r) => (
                      <tr key={r.cusip}>
                        <td>{r.ticker ?? "?"}</td>
                        <td className="mono">{r.cusip}</td>
                        <td className="num"><Money value={r.delta_value_usd} /></td>
                        <td className="num"><Money value={r.total_value_usd} /></td>
                        <td className="num">{r.manager_count}</td>
                        <td className="num">{r.manager_increase_count}/{r.manager_decrease_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </section>
      )}

      {tab === "subscribers" && (
        <section className="grid">
          <div className="card span3">
            <div className="cardTitle">Subscribers</div>
            <div className="muted">Pilot ops view (read-only). Filter by status.</div>

            <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
              <div className="muted">Status</div>
              <input
                style={{ width: 220 }}
                value={subsStatusFilter}
                onChange={(e) => setSubsStatusFilter(e.target.value)}
                placeholder="(all) or pending/active/…"
              />
              <button
                className="btnSmall"
                onClick={() => {
                  setSubs({ status: "loading" });
                  api.listSubscribers(subsStatusFilter, 200)
                    .then((data) => setSubs({ status: "ok", data }))
                    .catch((e) => setSubs({ status: "error", error: String(e) }));
                }}
              >
                Refresh
              </button>
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
              <div className="muted">Invite</div>
              <input
                style={{ width: 320 }}
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="email@domain.com"
              />
              <button
                className="btnSmall btnPrimary"
                onClick={() => {
                  const email = (inviteEmail || "").trim();
                  if (!email) return;
                  setInviteMsg("Sending confirmation email…");
                  api.inviteSubscriber(email)
                    .then((resp: any) => {
                      if (!resp.ok) {
                        setInviteMsg(String(resp.error || "Invite failed"));
                        return;
                      }
                      setInviteMsg(`Invited: ${email} (status=${String(resp.status || "pending")}).`);
                      setInviteEmail("");
                      api.listSubscribers(subsStatusFilter, 200).then((data) => setSubs({ status: "ok", data })).catch(() => { });
                    })
                    .catch((e) => setInviteMsg(String(e)));
                }}
              >
                Send Invite
              </button>
              {inviteMsg ? <div className={inviteMsg.includes("failed") || inviteMsg.includes("Error") ? "error" : "muted"}>{inviteMsg}</div> : null}
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
              <div className="muted">Manual add</div>
              <input
                style={{ width: 320 }}
                value={manualEmail}
                onChange={(e) => setManualEmail(e.target.value)}
                placeholder="email@domain.com"
              />
              <button
                className="btnSmall"
                onClick={() => {
                  const email = (manualEmail || "").trim();
                  if (!email) return;
                  setManualMsg("Adding…");
                  api.manualAddSubscriber(email, "active")
                    .then((resp: any) => {
                      if (!resp.ok) {
                        setManualMsg(String(resp.error || "Add failed"));
                        return;
                      }
                      setManualMsg(`Added: ${email} (status=${String(resp.status || "active")}).`);
                      setManualEmail("");
                      api.listSubscribers(subsStatusFilter, 200).then((data) => setSubs({ status: "ok", data })).catch(() => { });
                    })
                    .catch((e) => setManualMsg(String(e)));
                }}
              >
                Add Active
              </button>
              {manualMsg ? <div className={manualMsg.includes("failed") || manualMsg.includes("Error") ? "error" : "muted"}>{manualMsg}</div> : null}
            </div>

            {subs.status === "loading" && <div className="muted">Loading…</div>}
            {subs.status === "error" && <div className="error">{subs.error}</div>}
            {subs.status === "ok" && subs.data && (
              <>
                <div className="muted" style={{ marginTop: 10 }}>
                  counts: {Object.entries(subs.data.counts || {}).map(([k, v]) => `${k}=${v}`).join(" · ") || "—"}
                </div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Confirmed</th>
                      <th>Unsubscribed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {subs.data.rows.slice(0, 200).map((s) => (
                      <tr key={s.email}>
                        <td className="mono">{s.email}</td>
                        <td>{s.status}</td>
                        <td className="muted">{s.created_at ? String(s.created_at).replace("T", " ").slice(0, 19) : "—"}</td>
                        <td className="muted">{s.confirmed_at ? String(s.confirmed_at).replace("T", " ").slice(0, 19) : "—"}</td>
                        <td className="muted">{s.unsubscribed_at ? String(s.unsubscribed_at).replace("T", " ").slice(0, 19) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </section>
      )}

      <Drawer
        title={
          selectedRec
            ? `${selectedRec.ticker} — ${selectedRec.action.toUpperCase()} (score ${scoreTo10(selectedRec.score, selectedRec.reasons)}/10, conf ${Math.round(selectedRec.confidence * 100)}%)`
            : ""
        }
        open={selectedRec !== null}
        onClose={() => setSelectedRec(null)}
      >
        {selectedRec && (
          <div className="kv">
            {((selectedRec.reasons as any)?.sc13 || (selectedRec.reasons as any)?.insider) ? (
              <>
                <div style={{ marginTop: 2 }} className="muted">
                  Evidence (fresh)
                </div>
                <div className="kvRow">
                  <div className="kvKey">SC 13D/13G count</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.sc13?.count ?? 0)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">SC13 latest filed</div>
                  <div className="kvVal">{String((selectedRec.reasons as any)?.sc13?.latest_filed_at ?? "n/a")}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Insider buy</div>
                  <div className="kvVal"><Money value={Number((selectedRec.reasons as any)?.insider?.buy_value ?? 0)} /></div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Insider sell</div>
                  <div className="kvVal"><Money value={Number((selectedRec.reasons as any)?.insider?.sell_value ?? 0)} /></div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Insider net</div>
                  <div className="kvVal"><Money value={Number((selectedRec.reasons as any)?.insider?.net_value ?? 0)} /></div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Insider latest</div>
                  <div className="kvVal">{String((selectedRec.reasons as any)?.insider?.latest_event_date ?? "n/a")}</div>
                </div>
                {((selectedRec.reasons as any)?.insider?.buy_count_10b5 != null ||
                  (selectedRec.reasons as any)?.insider?.sell_count_10b5 != null ||
                  (selectedRec.reasons as any)?.insider?.cluster_buy_insiders != null) ? (
                  <>
                    <div style={{ marginTop: 8 }} className="muted">
                      Insider quality (v0.1)
                    </div>
                    <div className="kvRow">
                      <div className="kvKey">10b5-1 buy</div>
                      <div className="kvVal">
                        <Money value={Number((selectedRec.reasons as any)?.insider?.buy_value_10b5 ?? 0)} /> ·
                        {Number((selectedRec.reasons as any)?.insider?.buy_count_10b5 ?? 0)} tx
                      </div>
                    </div>
                    <div className="kvRow">
                      <div className="kvKey">10b5-1 sell</div>
                      <div className="kvVal">
                        <Money value={Number((selectedRec.reasons as any)?.insider?.sell_value_10b5 ?? 0)} /> ·
                        {Number((selectedRec.reasons as any)?.insider?.sell_count_10b5 ?? 0)} tx
                      </div>
                    </div>
                    <div className="kvRow">
                      <div className="kvKey">Cluster buy</div>
                      <div className="kvVal">
                        {Number((selectedRec.reasons as any)?.insider?.cluster_buy_insiders ?? 0) >= 3 ? "yes" : "no"} ·
                        {Number((selectedRec.reasons as any)?.insider?.cluster_buy_insiders ?? 0)} insiders
                      </div>
                    </div>
                  </>
                ) : null}
              </>
            ) : null}
            <div className="kvRow">
              <div className="kvKey">Segment</div>
              <div className="kvVal">{selectedRec.segment}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">Direction</div>
              <div className="kvVal">{selectedRec.direction}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">Confidence</div>
              <div className="kvVal">{(selectedRec.confidence * 100).toFixed(0)}%</div>
            </div>
            {(selectedRec.reasons as any)?.divergence ? (
              <>
                <div style={{ marginTop: 10 }} className="muted">
                  Divergence
                </div>
                <div className="kvRow">
                  <div className="kvKey">Type</div>
                  <div className="kvVal">{String((selectedRec.reasons as any)?.divergence?.label ?? "none")}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Insider vs trend</div>
                  <div className="kvVal">
                    {String((selectedRec.reasons as any)?.divergence?.insider_direction ?? "neutral")} /{" "}
                    {String((selectedRec.reasons as any)?.divergence?.trend_direction ?? "neutral")}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Score adj</div>
                  <div className="kvVal">
                    {Number((selectedRec.reasons as any)?.divergence?.score_adjustment ?? 0) >= 0 ? "+" : ""}
                    {Number((selectedRec.reasons as any)?.divergence?.score_adjustment ?? 0)}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Conf adj</div>
                  <div className="kvVal">
                    {Number((selectedRec.reasons as any)?.divergence?.confidence_adjustment ?? 0) >= 0 ? "+" : ""}
                    {((Number((selectedRec.reasons as any)?.divergence?.confidence_adjustment ?? 0)) * 100).toFixed(0)}%
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Note</div>
                  <div className="kvVal">{String((selectedRec.reasons as any)?.divergence?.note ?? "n/a")}</div>
                </div>
              </>
            ) : null}
            {(selectedRec.reasons as any)?.social?.enabled ? (
              <>
                <div style={{ marginTop: 10 }} className="muted">
                  Social listener (cashtag velocity)
                </div>
                <div className="kvRow">
                  <div className="kvKey">Source</div>
                  <div className="kvVal">{String((selectedRec.reasons as any)?.social?.source ?? "n/a")}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Latest bucket</div>
                  <div className="kvVal">{String((selectedRec.reasons as any)?.social?.latest_bucket_start ?? "n/a")}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Mentions (latest)</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.social?.mentions_latest ?? 0)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Mentions (7D avg)</div>
                  <div className="kvVal">
                    {(selectedRec.reasons as any)?.social?.mentions_baseline_7d == null
                      ? "n/a"
                      : Number((selectedRec.reasons as any)?.social?.mentions_baseline_7d ?? 0).toFixed(2)}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Velocity</div>
                  <div className="kvVal">
                    {(selectedRec.reasons as any)?.social?.velocity == null
                      ? "n/a"
                      : `${Number((selectedRec.reasons as any)?.social?.velocity ?? 0).toFixed(2)}x`}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Persistent (2 buckets)</div>
                  <div className="kvVal">{(selectedRec.reasons as any)?.social?.persistent ? "yes" : "no"}</div>
                </div>
              </>
            ) : null}

            {((selectedRec.reasons as any)?.delta_value_usd != null ||
              (selectedRec.reasons as any)?.context_13f != null) ? (
              <>
                <div style={{ marginTop: 10 }} className="muted">
                  Context (13F is delayed)
                </div>
                <div className="kvRow">
                  <div className="kvKey">Report period</div>
                  <div className="kvVal">
                    {String((selectedRec.reasons as any)?.report_period ?? (selectedRec.reasons as any)?.context_13f?.report_period ?? "n/a")}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Previous period</div>
                  <div className="kvVal">
                    {String((selectedRec.reasons as any)?.previous_period ?? (selectedRec.reasons as any)?.context_13f?.previous_period ?? "n/a")}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Δ value</div>
                  <div className="kvVal">
                    <Money value={Number((selectedRec.reasons as any)?.delta_value_usd ?? (selectedRec.reasons as any)?.context_13f?.delta_value_usd ?? 0)} />
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Total value</div>
                  <div className="kvVal">
                    <Money value={Number((selectedRec.reasons as any)?.total_value_usd ?? (selectedRec.reasons as any)?.context_13f?.total_value_usd ?? 0)} />
                  </div>
                </div>
                {(selectedRec.reasons as any)?.breadth ? (
                  <div className="kvRow">
                    <div className="kvKey">Breadth</div>
                    <div className="kvVal">
                      +{Number((selectedRec.reasons as any)?.breadth?.increase ?? 0)}/-{Number((selectedRec.reasons as any)?.breadth?.decrease ?? 0)} of{" "}
                      {Number((selectedRec.reasons as any)?.breadth?.total ?? 0)}
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}

            {(selectedRec.reasons as any)?.score_breakdown ? (
              <>
                <div style={{ marginTop: 10 }} className="muted">
                  Score breakdown
                </div>
                <div className="kvRow">
                  <div className="kvKey">Magnitude</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.score_breakdown?.magnitude?.score ?? 0).toFixed(1)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Breadth</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.score_breakdown?.breadth?.score ?? 0).toFixed(1)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Size</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.score_breakdown?.size?.score ?? 0).toFixed(1)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Penalty</div>
                  <div className="kvVal">-{Number((selectedRec.reasons as any)?.score_breakdown?.penalty?.total ?? 0).toFixed(1)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Whale score</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.whale_score ?? selectedRec.score)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Trend adj</div>
                  <div className="kvVal">
                    {Number((selectedRec.reasons as any)?.trend_adjustment ?? 0) >= 0 ? "+" : ""}
                    {Number((selectedRec.reasons as any)?.trend_adjustment ?? 0)}
                  </div>
                </div>
              </>
            ) : null}

            <div style={{ marginTop: 10 }} className="muted">
              Corroborators (fresh window)
            </div>
            {((selectedRec.reasons as any)?.fresh_days != null || (selectedRec.reasons as any)?.trend_flags) ? (
              <>
                <div className="kvRow">
                  <div className="kvKey">Fresh window</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.fresh_days ?? 7)} days</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">SC 13D/13G recent</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.sc13?.count ?? 0) > 0 ? "yes" : "no"}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Insider buy recent</div>
                  <div className="kvVal">
                    {Number((selectedRec.reasons as any)?.insider?.buy_count ?? 0) > 0 ? "yes" : "no"}{" "}
                    <span className="muted">
                      (min ${Number((selectedRec.reasons as any)?.insider_min_value ?? 0).toLocaleString()})
                    </span>
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Insider sell recent</div>
                  <div className="kvVal">
                    {Number((selectedRec.reasons as any)?.insider?.sell_count ?? 0) > 0 ? "yes" : "no"}{" "}
                    <span className="muted">
                      (min ${Number((selectedRec.reasons as any)?.insider_min_value ?? 0).toLocaleString()})
                    </span>
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Trend bullish (recent)</div>
                  <div className="kvVal">{(selectedRec.reasons as any)?.trend_flags?.bullish_recent ? "yes" : "no"}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Trend bearish (recent)</div>
                  <div className="kvVal">{(selectedRec.reasons as any)?.trend_flags?.bearish_recent ? "yes" : "no"}</div>
                </div>
              </>
            ) : (
              <>
                <div className="kvRow">
                  <div className="kvKey">Fresh window</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.corroborators?.fresh_days ?? 7)} days</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">SC 13D/13G recent</div>
                  <div className="kvVal">{(selectedRec.reasons as any)?.corroborators?.sc13_recent ? "yes" : "no"}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Insider buy recent</div>
                  <div className="kvVal">
                    {(selectedRec.reasons as any)?.corroborators?.insider_buy_recent ? "yes" : "no"}{" "}
                    <span className="muted">
                      (min ${Number((selectedRec.reasons as any)?.corroborators?.insider_min_value ?? 0).toLocaleString()})
                    </span>
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Trend bullish (recent)</div>
                  <div className="kvVal">{(selectedRec.reasons as any)?.corroborators?.trend_bullish_recent ? "yes" : "no"}</div>
                </div>
              </>
            )}

            {(selectedRec.reasons as any)?.trend ? (
              <>
                <div className="kvRow">
                  <div className="kvKey">Trend as-of</div>
                  <div className="kvVal">{String((selectedRec.reasons as any)?.trend?.as_of_date ?? "n/a")}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Close</div>
                  <div className="kvVal"><Money value={Number((selectedRec.reasons as any)?.trend?.close ?? 0)} /></div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">SMA50</div>
                  <div className="kvVal"><Money value={Number((selectedRec.reasons as any)?.trend?.sma50 ?? 0)} /></div>
                </div>
                {(selectedRec.reasons as any)?.trend?.sma200 != null ? (
                  <div className="kvRow">
                    <div className="kvKey">SMA200</div>
                    <div className="kvVal"><Money value={Number((selectedRec.reasons as any)?.trend?.sma200 ?? 0)} /></div>
                  </div>
                ) : null}
                <div className="kvRow">
                  <div className="kvKey">20D return</div>
                  <div className="kvVal">{(((selectedRec.reasons as any)?.trend?.return_20d ?? 0) * 100).toFixed(1)}%</div>
                </div>
                {(selectedRec.reasons as any)?.trend?.return_60d != null ? (
                  <div className="kvRow">
                    <div className="kvKey">60D return</div>
                    <div className="kvVal">{(((selectedRec.reasons as any)?.trend?.return_60d ?? 0) * 100).toFixed(1)}%</div>
                  </div>
                ) : null}
              </>
            ) : null}

            <div style={{ marginTop: 10 }} className="muted">
              Technical guardrail (entry quality)
            </div>
            {(selectedRec.reasons as any)?.tech_guardrail ? (
              <>
                <div className="kvRow">
                  <div className="kvKey">Signal</div>
                  <div className="kvVal">
                    {Array.isArray((selectedRec.reasons as any)?.tech_guardrail?.notes)
                      ? ((selectedRec.reasons as any)?.tech_guardrail?.notes ?? []).join(" · ")
                      : String((selectedRec.reasons as any)?.tech_guardrail?.notes ?? "—")}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Factor (Ft)</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.tech_guardrail?.ft ?? 1).toFixed(2)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Adj</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.tech_guardrail?.adj ?? 0) >= 0 ? "+" : ""}{Number((selectedRec.reasons as any)?.tech_guardrail?.adj ?? 0)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Score (raw)</div>
                  <div className="kvVal">
                    {Number((selectedRec.reasons as any)?.tech_guardrail?.score_before ?? selectedRec.score)} →{" "}
                    {Number((selectedRec.reasons as any)?.tech_guardrail?.score_after ?? selectedRec.score)}
                  </div>
                </div>
                {(selectedRec.reasons as any)?.trend?.dist_sma50_pct != null ? (
                  <div className="kvRow">
                    <div className="kvKey">Dist to SMA50</div>
                    <div className="kvVal">{(((selectedRec.reasons as any)?.trend?.dist_sma50_pct ?? 0) * 100).toFixed(1)}%</div>
                  </div>
                ) : null}
                {(selectedRec.reasons as any)?.trend?.dist_sma200_pct != null ? (
                  <div className="kvRow">
                    <div className="kvKey">Dist to SMA200</div>
                    <div className="kvVal">{(((selectedRec.reasons as any)?.trend?.dist_sma200_pct ?? 0) * 100).toFixed(1)}%</div>
                  </div>
                ) : null}
                {(selectedRec.reasons as any)?.trend?.dist_high_60d_pct != null ? (
                  <div className="kvRow">
                    <div className="kvKey">Dist to 60D high</div>
                    <div className="kvVal">{(((selectedRec.reasons as any)?.trend?.dist_high_60d_pct ?? 0) * 100).toFixed(1)}%</div>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="kvRow">
                <div className="kvKey">Status</div>
                <div className="kvVal">no technical data (insufficient recent price bars)</div>
              </div>
            )}

            {(selectedRec.reasons as any)?.volume ? (
              <>
                <div style={{ marginTop: 10 }} className="muted">
                  Volume (confirmation)
                </div>
                <div className="kvRow">
                  <div className="kvKey">Avg 20D vol</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.volume?.avg20 ?? 0).toFixed(0)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Latest vol</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.volume?.latest ?? 0).toFixed(0)}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Vol ratio</div>
                  <div className="kvVal">{Number((selectedRec.reasons as any)?.volume?.ratio ?? 0).toFixed(2)}x</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Spike</div>
                  <div className="kvVal">{(selectedRec.reasons as any)?.volume?.spike ? "yes" : "no"}</div>
                </div>
              </>
            ) : null}

            {(selectedRec.reasons as any)?.evidence ? (
              <>
                <div style={{ marginTop: 10 }} className="muted">
                  Evidence (filings/tx)
                </div>
                {Array.isArray((selectedRec.reasons as any)?.evidence?.sc13_filings) && (selectedRec.reasons as any)?.evidence?.sc13_filings?.length ? (
                  <div className="muted" style={{ marginTop: 6, lineHeight: 1.4 }}>
                    SC13: {((selectedRec.reasons as any)?.evidence?.sc13_filings ?? []).slice(0, 5).map((f: any) => `${String(f.form_type ?? "SC13")} ${String(f.accession ?? "").slice(-8)} (${String(f.filed_at ?? "")})`).join(" · ")}
                  </div>
                ) : null}
                {Array.isArray((selectedRec.reasons as any)?.evidence?.insider_txs) && (selectedRec.reasons as any)?.evidence?.insider_txs?.length ? (
                  <div className="muted" style={{ marginTop: 6, lineHeight: 1.4 }}>
                    Form4: {((selectedRec.reasons as any)?.evidence?.insider_txs ?? []).slice(0, 5).map((x: any) => `${String(x.code ?? "")} ${String(x.event_date ?? "").slice(0, 10)} ${String(x.insider_name ?? "").slice(0, 18)} $${Number(x.value ?? 0).toLocaleString()}${x.estimated ? "*" : ""}`).join(" · ")}
                  </div>
                ) : null}
                {Array.isArray((selectedRec.reasons as any)?.evidence?.insider_txs) && (selectedRec.reasons as any)?.evidence?.insider_txs?.some((x: any) => x.estimated) ? (
                  <div className="muted" style={{ marginTop: 4 }}>* estimated value (shares × close)</div>
                ) : null}
              </>
            ) : null}

            <div style={{ marginTop: 10 }} className="muted">
              Action rule (v0)
            </div>
            <div className="muted" style={{ lineHeight: 1.4 }}>
              {((selectedRec.reasons as any)?.sc13 || (selectedRec.reasons as any)?.insider)
                ? "Fresh signals prioritize SC13 + insider activity and use trend/volume as timing/confirmation. Action is conservative (BUY/AVOID only when corroborated)."
                : "13F provides delayed context. This becomes buy only if score ≥ threshold AND a fresh corroborator exists (SC13, insider buy, or bullish trend)."}
            </div>
          </div>
        )}
      </Drawer>

      <Drawer
        title={
          selectedWatch
            ? `${selectedWatch.row.ticker} — ${selectedWatch.list === "etfs" ? "ETF / Macro" : "Dividend"}`
            : ""
        }
        open={selectedWatch !== null}
        onClose={() => setSelectedWatch(null)}
      >
        {selectedWatch && (
          <div className="kv">
            {selectedWatch.list === "dividends" ? (
              <>
                <div style={{ marginTop: 2 }} className="muted">
                  Dividend (best-effort)
                </div>
                <div className="kvRow">
                  <div className="kvKey">Yield (TTM)</div>
                  <div className="kvVal">
                    {selectedWatch.row.dividend_yield_ttm == null
                      ? "n/a"
                      : `${(Number(selectedWatch.row.dividend_yield_ttm) * 100).toFixed(1)}%`}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Payout ratio</div>
                  <div className="kvVal">
                    {selectedWatch.row.payout_ratio == null
                      ? "n/a"
                      : `${(Number(selectedWatch.row.payout_ratio) * 100).toFixed(0)}%`}
                  </div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Ex-div date</div>
                  <div className="kvVal">{selectedWatch.row.ex_dividend_date ?? "n/a"}</div>
                </div>
                <div className="kvRow">
                  <div className="kvKey">Dividend as-of</div>
                  <div className="kvVal">{selectedWatch.row.dividend_as_of ?? "n/a"}</div>
                </div>
              </>
            ) : null}
            <div className="kvRow">
              <div className="kvKey">As-of</div>
              <div className="kvVal">{selectedWatch.row.as_of_date ?? "n/a"}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">Close</div>
              <div className="kvVal">{selectedWatch.row.close == null ? "n/a" : <Money value={Number(selectedWatch.row.close)} />}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">SMA50</div>
              <div className="kvVal">{selectedWatch.row.sma50 == null ? "n/a" : <Money value={Number(selectedWatch.row.sma50)} />}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">SMA200</div>
              <div className="kvVal">{selectedWatch.row.sma200 == null ? "n/a" : <Money value={Number(selectedWatch.row.sma200)} />}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">20D return</div>
              <div className="kvVal">{selectedWatch.row.return_20d == null ? "n/a" : `${(selectedWatch.row.return_20d * 100).toFixed(1)}%`}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">60D return</div>
              <div className="kvVal">{selectedWatch.row.return_60d == null ? "n/a" : `${(selectedWatch.row.return_60d * 100).toFixed(1)}%`}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">Trend (recent)</div>
              <div className="kvVal">
                {selectedWatch.row.bullish_recent ? "bullish" : selectedWatch.row.bearish_recent ? "bearish" : "n/a"}
              </div>
            </div>

            <div style={{ marginTop: 10 }} className="muted">
              Volume (confirmation)
            </div>
            <div className="kvRow">
              <div className="kvKey">Latest vol</div>
              <div className="kvVal">{selectedWatch.row.volume == null ? "n/a" : Number(selectedWatch.row.volume).toLocaleString()}</div>
            </div>
            <div className="kvRow">
              <div className="kvKey">Avg 20D vol</div>
              <div className="kvVal">
                {selectedWatch.row.volume_avg20 == null ? "n/a" : Number(selectedWatch.row.volume_avg20).toFixed(0)}
              </div>
            </div>
            <div className="kvRow">
              <div className="kvKey">Vol ratio</div>
              <div className="kvVal">{selectedWatch.row.volume_ratio == null ? "n/a" : `${selectedWatch.row.volume_ratio.toFixed(2)}x`}</div>
            </div>

          </div>
        )}
      </Drawer>

      <Drawer
        title={selectedSubscriberRunId ? `Email run: ${selectedSubscriberRunId.slice(0, 8)}` : ""}
        open={selectedSubscriberRunId !== null}
        onClose={() => {
          setSelectedSubscriberRunId(null);
          setSubscriberRunDetail({ status: "idle" });
        }}
      >
        {subscriberRunDetail.status === "loading" && <div className="muted">Loading…</div>}
        {subscriberRunDetail.status === "error" && <div className="error">{subscriberRunDetail.error}</div>}
        {subscriberRunDetail.status === "ok" && subscriberRunDetail.data && (
          <>
            {!subscriberRunDetail.data.ok ? (
              <div className="error">{String((subscriberRunDetail.data as any).error || "not found")}</div>
            ) : (
              <>
                <div className="muted">as_of: {subscriberRunDetail.data.run?.as_of ?? "n/a"}</div>
                <div className="muted">created_at: {subscriberRunDetail.data.run?.created_at ?? "n/a"}</div>
                <div className="muted">status: {subscriberRunDetail.data.run?.status ?? "n/a"}</div>
                <div className="muted">sent_at: {subscriberRunDetail.data.run?.sent_at ?? "—"}</div>
                <div className="muted" style={{ marginTop: 6 }}>
                  diff: {JSON.stringify((subscriberRunDetail.data.run?.policy as any)?.diff ?? {})}
                </div>
                {subscriberRunDetail.data.run?.status === "draft" ? (
                  <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
                    <button
                      className="btnSmall"
                      onClick={() => {
                        const runId = subscriberRunDetail.data?.run?.id;
                        if (!runId) return;
                        const lim = Number(subscriberSendLimit || "0");
                        setSubscriberOpsMsg("Sending…");
                        api
                          .sendSubscriberAlertRun(runId, Number.isFinite(lim) ? lim : 0)
                          .then((resp) => {
                            if (!resp.ok) {
                              setSubscriberOpsMsg(String((resp as any).error || "Send failed."));
                              return;
                            }
                            const r = resp.result;
                            setSubscriberOpsMsg(
                              `Sent. status=${resp.run?.status ?? r?.status} subs=${r?.subscribers_seen ?? 0} sent=${r?.sent ?? 0} failed=${r?.failed ?? 0} skipped=${r?.skipped ?? 0} changed=${r?.changed ?? true}`,
                            );
                            api.getSubscriberAlertRun(runId).then((data) => setSubscriberRunDetail({ status: "ok", data })).catch(() => { });
                            api.listSubscriberAlertRuns(5).then((data) => setSubscriberRuns({ status: "ok", data })).catch(() => { });
                          })
                          .catch((e) => setSubscriberOpsMsg(String(e)));
                      }}
                    >
                      Send Now
                    </button>
                    <div className="muted">Uses current “Send limit” above (0 = all).</div>
                  </div>
                ) : null}

                <div style={{ marginTop: 10 }}>
                  <div className="cardTitle">Items</div>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th>Action</th>
                        <th className="num">Score(1–10)</th>
                        <th className="num">Conf</th>
                        <th>Why</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(subscriberRunDetail.data.items ?? []).map((it) => (
                        <tr key={`${it.ticker}-${it.action}`}>
                          <td className="mono">{it.ticker}</td>
                          <td>{it.action}</td>
                          <td className="num">{scoreTo10(it.score, it.evidence as any)}</td>
                          <td className="num">{Math.round(it.confidence * 100)}%</td>
                          <td className="muted">{(it.why ?? []).slice(0, 2).join(" · ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div style={{ marginTop: 10 }}>
                  <div className="cardTitle">Deliveries</div>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Email</th>
                        <th>Status</th>
                        <th>Queued</th>
                        <th>Sent</th>
                        <th>Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(subscriberRunDetail.data.deliveries ?? []).map((d) => (
                        <tr key={`${d.email}-${d.delivery.queued_at}`}>
                          <td className="mono">{d.email}</td>
                          <td>{d.delivery.status}</td>
                          <td className="muted">{String(d.delivery.queued_at).replace("T", " ").slice(0, 19)}</td>
                          <td className="muted">{d.delivery.sent_at ? String(d.delivery.sent_at).replace("T", " ").slice(0, 19) : "—"}</td>
                          <td className="error">{d.delivery.error ?? ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </Drawer>
    </div>
  );
}
