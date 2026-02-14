import React, { useEffect, useMemo, useState } from "react";
import { api, type AdminMetrics, type Latest13FWhales, type LatestInsiderWhales, type WatchlistRows } from "./api";
import { Money, Percent } from "./format";
import { Drawer } from "./Drawer";

type LoadState<T> = { status: "idle" | "loading" | "error" | "ok"; data?: T; error?: string };

type Tab = "latest" | "runs";

export function App() {
  const [tab, setTab] = useState<Tab>("latest");
  const [metrics, setMetrics] = useState<LoadState<AdminMetrics>>({ status: "idle" });
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
  const avoidFresh = useMemo(() => {
    const rows = fresh.data?.rows ?? [];
    return rows.filter((r) => r.action === "avoid");
  }, [fresh.data]);

  useEffect(() => {
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

    setAlerts({ status: "loading" });
    api.latestAlerts(true)
      .then((data) => setAlerts({ status: "ok", data }))
      .catch((e) => setAlerts({ status: "error", error: String(e) }));
  }, []);

  useEffect(() => {
    if (tab !== "runs") return;
    setRuns({ status: "loading" });
    api.listSnapshotRuns()
      .then((data) => setRuns({ status: "ok", data: { runs: data.runs.map((r) => ({ id: r.id, kind: r.kind, as_of: r.as_of })) } }))
      .catch((e) => setRuns({ status: "error", error: String(e) }));
  }, [tab]);

  useEffect(() => {
    if (!selectedRun) return;
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

  return (
    <div className="page">
      <header className="header">
        <div>
          <div className="title">WealthPulse Admin</div>
          <div className="subtitle">Snapshots + whale signals (v0)</div>
        </div>
        <div className="tabs">
          <button className={tab === "latest" ? "tab active" : "tab"} onClick={() => setTab("latest")}>
            Latest
          </button>
          <button className={tab === "runs" ? "tab active" : "tab"} onClick={() => setTab("runs")}>
            Runs
          </button>
        </div>
      </header>

      {tab === "latest" && (
        <section className="grid gridLatest">
        <div className="card">
          <div className="cardTitle">Top Picks (v0)</div>
          <div className="muted">Score + Watch/Sell/Buy require corroboration (13F is delayed).</div>
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
                    <th className="num">Score</th>
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
                      <td className="num">{r.score}</td>
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
          <div className="muted">Primarily SC 13D/13G + Form 4 (fresh) with trend/volume confirmation.</div>
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
                    <th className="num">Score</th>
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
                      <td className="num">{r.score}</td>
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
                    <th className="num">Score</th>
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
                      <td className="num">{r.score}</td>
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

        <div className="card">
          <div className="cardTitle">Alerts</div>
          <div className="muted">Admin-only notifications from snapshots + watchlists.</div>
          {alerts.status === "loading" && <div className="muted">Loading…</div>}
          {alerts.status === "error" && <div className="error">{alerts.error}</div>}
          {alerts.status === "ok" && alerts.data && (
            <>
              {alerts.data.rows.length === 0 ? <div className="muted" style={{ marginTop: 8 }}>No unread alerts.</div> : null}
              <div className="alertList">
                {alerts.data.rows.slice(0, 12).map((a) => (
                  <div key={a.id} className="alertRow">
                    <div className="alertMain">
                      <div className="alertTitle">{a.title}</div>
                      <div className="muted">{a.body}</div>
                      <div className="muted">{a.created_at}</div>
                    </div>
                    <button
                      className="btnSmall"
                      onClick={() =>
                        api.ackAlert(a.id).then(() => {
                          setAlerts((prev) => {
                            if (prev.status !== "ok" || !prev.data) return prev;
                            return { status: "ok", data: { rows: prev.data.rows.filter((x) => x.id !== a.id) } };
                          });
                        })
                      }
                    >
                      Ack
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </section>
      )}

      {tab === "runs" && (
        <section className="grid">
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

      <Drawer
        title={selectedRec ? `${selectedRec.ticker} — ${selectedRec.action.toUpperCase()} (${selectedRec.score})` : ""}
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
    </div>
  );
}
