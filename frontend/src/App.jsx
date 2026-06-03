import { useState, useEffect, useCallback } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Area, AreaChart
} from "recharts";

const API = "http://localhost:8000/api/v1";

// ── Palette ───────────────────────────────────────────────────────────────────
const C = {
  bg: "#0a0e1a",
  surface: "#111827",
  card: "#1a2235",
  border: "#1e2d45",
  accent: "#00d4ff",
  green: "#00e676",
  red: "#ff4d6d",
  gold: "#ffc107",
  text: "#e2e8f0",
  muted: "#64748b",
  purple: "#a78bfa",
};

const badge = (cls) => ({
  stock: { bg: "#1a3a5c", color: "#60a5fa" },
  crypto: { bg: "#1a2e1a", color: "#4ade80" },
  bond: { bg: "#2d2010", color: "#fbbf24" },
  commodity: { bg: "#2d1a10", color: "#fb923c" },
  etf: { bg: "#1a1a3a", color: "#a78bfa" },
  forex: { bg: "#1a2d2d", color: "#2dd4bf" },
}[cls] || { bg: "#1a1a1a", color: "#94a3b8" });

// ── Tiny helpers ──────────────────────────────────────────────────────────────
const fmt = (n, d = 2) => n == null ? "—" : Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (n) => n == null ? "—" : `${n > 0 ? "+" : ""}${fmt(n)}%`;
const pctColor = (n) => n == null ? C.muted : n > 0 ? C.green : n < 0 ? C.red : C.text;

async function apiFetch(path) {
  try {
    const r = await fetch(`${API}${path}`);
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

// ── Components ────────────────────────────────────────────────────────────────

function Pill({ cls }) {
  const s = badge(cls);
  return (
    <span style={{
      background: s.bg, color: s.color, border: `1px solid ${s.color}22`,
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      textTransform: "uppercase", letterSpacing: "0.05em",
    }}>{cls}</span>
  );
}

function Card({ children, style = {} }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 10, padding: 20, ...style,
    }}>{children}</div>
  );
}

function StatBox({ label, value, color = C.text, prefix = "" }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>{label}</div>
      <div style={{ color, fontSize: 20, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{prefix}{value}</div>
    </div>
  );
}

// ── ASSET LIST ────────────────────────────────────────────────────────────────
function AssetList({ onSelect, selectedId }) {
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    apiFetch("/assets/?limit=50").then(d => {
      setAssets(d || []);
      setLoading(false);
    });
  }, []);

  const visible = assets.filter(a =>
    a.symbol.toLowerCase().includes(filter.toLowerCase()) ||
    a.description.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ width: 6, height: 20, background: C.accent, borderRadius: 3 }} />
        <span style={{ color: C.text, fontWeight: 700, fontSize: 14 }}>Assets</span>
        <span style={{
          marginLeft: "auto", background: `${C.accent}22`, color: C.accent,
          padding: "2px 8px", borderRadius: 12, fontSize: 12, fontWeight: 600,
        }}>{assets.length}</span>
      </div>
      <input
        value={filter} onChange={e => setFilter(e.target.value)}
        placeholder="Search symbol or name…"
        style={{
          background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6,
          padding: "7px 12px", color: C.text, fontSize: 13, outline: "none", width: "100%",
          boxSizing: "border-box",
        }}
      />
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading ? (
          <div style={{ color: C.muted, textAlign: "center", paddingTop: 40 }}>Loading…</div>
        ) : visible.map(a => (
          <div
            key={a.asset_id}
            onClick={() => onSelect(a)}
            style={{
              padding: "10px 12px", borderRadius: 8, cursor: "pointer", marginBottom: 4,
              background: selectedId === a.asset_id ? `${C.accent}15` : "transparent",
              border: `1px solid ${selectedId === a.asset_id ? C.accent + "60" : "transparent"}`,
              transition: "all 0.15s",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span style={{ color: C.text, fontWeight: 700, fontSize: 14 }}>{a.symbol}</span>
              <Pill cls={a.asset_class} />
              <span style={{ marginLeft: "auto", color: C.muted, fontSize: 11 }}>{a.region}</span>
            </div>
            <div style={{ color: C.muted, fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {a.description}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── PRICE CHART ───────────────────────────────────────────────────────────────
function PriceChart({ assetId, sourceId }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState(90);

  useEffect(() => {
    if (!assetId || !sourceId) return;
    setLoading(true);
    const from = new Date(Date.now() - range * 86400000).toISOString().slice(0, 10);
    apiFetch(`/timeseries/?asset_id=${assetId}&source_id=${sourceId}&from_date=${from}&limit=500`)
      .then(d => {
        if (d?.data) {
          setData(d.data.map(p => ({
            date: new Date(p.series_date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
            close: p.close,
            open: p.open,
            high: p.high,
            low: p.low,
            volume: p.volume,
          })));
        }
        setLoading(false);
      });
  }, [assetId, sourceId, range]);

  if (!assetId) return <div style={{ color: C.muted, textAlign: "center", paddingTop: 60 }}>Select an asset</div>;

  const minClose = Math.min(...data.map(d => d.close).filter(Boolean));
  const maxClose = Math.max(...data.map(d => d.close).filter(Boolean));
  const latest = data[data.length - 1]?.close;
  const first = data[0]?.close;
  const chg = first ? (latest - first) / first * 100 : null;
  const isUp = chg >= 0;

  return (
    <div style={{ height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {[30, 90, 180, 365].map(d => (
            <button key={d} onClick={() => setRange(d)} style={{
              background: range === d ? C.accent : C.surface,
              color: range === d ? C.bg : C.muted,
              border: `1px solid ${range === d ? C.accent : C.border}`,
              borderRadius: 5, padding: "3px 10px", cursor: "pointer", fontSize: 12, fontWeight: 600,
            }}>{d}d</button>
          ))}
        </div>
        {chg != null && (
          <span style={{ marginLeft: "auto", color: pctColor(chg), fontWeight: 700, fontSize: 16 }}>
            {isUp ? "▲" : "▼"} {pct(chg)}
          </span>
        )}
      </div>
      {loading ? (
        <div style={{ color: C.muted, textAlign: "center", paddingTop: 80 }}>Loading chart…</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
            <defs>
              <linearGradient id="closeGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={isUp ? C.green : C.red} stopOpacity={0.3} />
                <stop offset="95%" stopColor={isUp ? C.green : C.red} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
            <XAxis dataKey="date" tick={{ fill: C.muted, fontSize: 10 }} tickLine={false} axisLine={false}
              interval={Math.floor(data.length / 6)} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: C.muted, fontSize: 10 }} tickLine={false}
              axisLine={false} tickFormatter={v => `$${fmt(v, 0)}`} width={65} />
            <Tooltip
              contentStyle={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8 }}
              labelStyle={{ color: C.muted, fontSize: 11 }}
              formatter={(v) => [`$${fmt(v)}`, "Close"]}
            />
            <Area type="monotone" dataKey="close" stroke={isUp ? C.green : C.red}
              fill="url(#closeGrad)" strokeWidth={2} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── STATS PANEL ───────────────────────────────────────────────────────────────
function StatsPanel({ assetId, sourceId }) {
  const [stats, setStats] = useState(null);
  const [forecast, setForecast] = useState(null);

  useEffect(() => {
    if (!assetId || !sourceId) return;
    setStats(null); setForecast(null);
    apiFetch(`/analytics/stats?asset_id=${assetId}&source_id=${sourceId}`).then(setStats);
    apiFetch(`/analytics/forecast?asset_id=${assetId}&source_id=${sourceId}&horizon_days=5`).then(setForecast);
  }, [assetId, sourceId]);

  if (!assetId) return null;
  if (!stats) return <div style={{ color: C.muted, fontSize: 13 }}>Loading stats…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card>
        <div style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 14 }}>Performance Summary</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <StatBox label="Avg Close" value={`$${fmt(stats.avg_close)}`} color={C.accent} />
          <StatBox label="Min Close" value={`$${fmt(stats.min_close)}`} color={C.red} />
          <StatBox label="Max Close" value={`$${fmt(stats.max_close)}`} color={C.green} />
          <StatBox label="Std Dev" value={`$${fmt(stats.std_close)}`} color={C.gold} />
          <StatBox label="Change" value={pct(stats.price_change_pct)} color={pctColor(stats.price_change_pct)} />
          <StatBox label="Records" value={stats.count?.toLocaleString()} color={C.purple} />
        </div>
      </Card>

      {forecast && forecast.forecast?.length > 0 && (
        <Card>
          <div style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 12 }}>
            5-Day Forecast
            <span style={{ marginLeft: 8, color: C.accent, fontSize: 10 }}>LINEAR REGRESSION</span>
          </div>
          <div style={{ color: C.muted, fontSize: 12, marginBottom: 10 }}>
            Last known: <span style={{ color: C.text, fontWeight: 600 }}>${fmt(forecast.last_known_close)}</span>
          </div>
          <ResponsiveContainer width="100%" height={120}>
            <AreaChart data={forecast.forecast.map(p => ({
              date: new Date(p.date).toLocaleDateString("en-US", { weekday: "short" }),
              predicted: p.predicted_close,
              lower: p.lower_bound,
              upper: p.upper_bound,
            }))}>
              <defs>
                <linearGradient id="fcastGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={C.purple} stopOpacity={0.4} />
                  <stop offset="95%" stopColor={C.purple} stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
              <XAxis dataKey="date" tick={{ fill: C.muted, fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis domain={["auto", "auto"]} tick={{ fill: C.muted, fontSize: 10 }} tickLine={false}
                axisLine={false} tickFormatter={v => `$${fmt(v, 0)}`} width={60} />
              <Tooltip contentStyle={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8 }}
                labelStyle={{ color: C.muted, fontSize: 11 }}
                formatter={(v, n) => [`$${fmt(v)}`, n === "predicted" ? "Forecast" : n]} />
              <Area type="monotone" dataKey="predicted" stroke={C.purple} fill="url(#fcastGrad)" strokeWidth={2} dot={true} />
            </AreaChart>
          </ResponsiveContainer>
          <div style={{ display: "flex", gap: 12, marginTop: 10 }}>
            {forecast.forecast.map((p, i) => (
              <div key={i} style={{ flex: 1, textAlign: "center" }}>
                <div style={{ color: C.muted, fontSize: 10 }}>{new Date(p.date).toLocaleDateString("en-US", { weekday: "short" })}</div>
                <div style={{ color: C.purple, fontWeight: 700, fontSize: 13 }}>${fmt(p.predicted_close)}</div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

// ── LLM CHAT ─────────────────────────────────────────────────────────────────
function ChatPanel() {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Hello! I'm the Acme Financial Assistant. Ask me about assets, prices, trends, or forecasts." }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg = { role: "user", content: input };
    const newMsgs = [...messages, userMsg];
    setMessages(newMsgs);
    setInput("");
    setLoading(true);

    const userMessages = newMsgs.filter(m => m.role !== "assistant" || newMsgs.indexOf(m) > 0);
    const res = await apiFetch("/assistant/chat");
    // Chat needs POST — use fetch directly
    try {
      const r = await fetch(`${API}/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: newMsgs.slice(1) }), // skip initial assistant msg
      });
      if (r.ok) {
        const d = await r.json();
        setMessages(prev => [...prev, { role: "assistant", content: d.reply }]);
      } else {
        setMessages(prev => [...prev, { role: "assistant", content: "⚠️ API error. Is the backend running? Set ANTHROPIC_API_KEY in .env to enable the assistant." }]);
      }
    } catch {
      setMessages(prev => [...prev, { role: "assistant", content: "⚠️ Cannot reach the backend. Start it with `docker-compose up`." }]);
    }
    setLoading(false);
  };

  const suggestions = [
    "What stocks are available?",
    "Show me AAPL statistics",
    "Forecast TSLA for 5 days",
    "Compare AAPL and MSFT",
  ];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: C.green, boxShadow: `0 0 8px ${C.green}` }} />
        <span style={{ color: C.text, fontWeight: 700, fontSize: 13 }}>AI Financial Assistant</span>
        <span style={{ color: C.muted, fontSize: 11 }}>via MCP + Claude</span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, paddingRight: 4 }}>
        {messages.map((m, i) => (
          <div key={i} style={{
            display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start",
          }}>
            <div style={{
              maxWidth: "85%", padding: "10px 14px", borderRadius: m.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
              background: m.role === "user" ? `${C.accent}25` : C.surface,
              border: `1px solid ${m.role === "user" ? C.accent + "40" : C.border}`,
              color: C.text, fontSize: 13, lineHeight: 1.6,
            }}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display: "flex" }}>
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: "14px 14px 14px 4px", padding: "10px 16px" }}>
              <span style={{ color: C.muted, fontSize: 13 }}>Thinking</span>
              <span style={{ color: C.accent, animation: "blink 1s infinite" }}>…</span>
            </div>
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10, marginBottom: 8 }}>
        {suggestions.map(s => (
          <button key={s} onClick={() => setInput(s)} style={{
            background: "transparent", border: `1px solid ${C.border}`, borderRadius: 20,
            color: C.muted, padding: "3px 10px", cursor: "pointer", fontSize: 11,
            transition: "all 0.15s",
          }} onMouseOver={e => e.target.style.borderColor = C.accent}
            onMouseOut={e => e.target.style.borderColor = C.border}>{s}</button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
          placeholder="Ask about any asset…"
          style={{
            flex: 1, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
            padding: "10px 14px", color: C.text, fontSize: 13, outline: "none",
          }}
        />
        <button onClick={send} disabled={loading} style={{
          background: C.accent, color: C.bg, border: "none", borderRadius: 8,
          padding: "10px 18px", cursor: "pointer", fontWeight: 700, fontSize: 13,
          opacity: loading ? 0.5 : 1,
        }}>Send</button>
      </div>
    </div>
  );
}

// ── SOURCE SELECTOR ───────────────────────────────────────────────────────────
function SourceSelector({ selectedSource, onSelect }) {
  const [sources, setSources] = useState([]);

  useEffect(() => {
    apiFetch("/sources/?limit=20").then(d => {
      if (d) { setSources(d); if (d.length > 0) onSelect(d[0]); }
    });
  }, []);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ color: C.muted, fontSize: 12 }}>Source:</span>
      {sources.map(s => (
        <button key={s.source_id} onClick={() => onSelect(s)} style={{
          background: selectedSource?.source_id === s.source_id ? `${C.gold}20` : "transparent",
          color: selectedSource?.source_id === s.source_id ? C.gold : C.muted,
          border: `1px solid ${selectedSource?.source_id === s.source_id ? C.gold + "60" : C.border}`,
          borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12, fontWeight: 600,
        }}>{s.provider_name}</button>
      ))}
    </div>
  );
}

// ── MAIN APP ──────────────────────────────────────────────────────────────────
export default function App() {
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [selectedSource, setSelectedSource] = useState(null);
  const [activeTab, setActiveTab] = useState("chart");

  const tabs = [
    { id: "chart", label: "Chart & Stats" },
    { id: "assistant", label: "AI Assistant" },
  ];

  return (
    <div style={{
      background: C.bg, minHeight: "100vh", fontFamily: "'Inter', system-ui, sans-serif",
      color: C.text, display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        background: C.surface, borderBottom: `1px solid ${C.border}`,
        padding: "0 24px", height: 56, display: "flex", alignItems: "center", gap: 20,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 28, height: 28, background: `linear-gradient(135deg, ${C.accent}, ${C.purple})`,
            borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14, fontWeight: 900, color: C.bg,
          }}>A</div>
          <span style={{ fontWeight: 800, fontSize: 16, letterSpacing: "-0.02em" }}>Acme</span>
          <span style={{ color: C.muted, fontWeight: 400, fontSize: 14 }}>Financial DWH</span>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
              background: activeTab === t.id ? `${C.accent}15` : "transparent",
              color: activeTab === t.id ? C.accent : C.muted,
              border: `1px solid ${activeTab === t.id ? C.accent + "40" : "transparent"}`,
              borderRadius: 7, padding: "6px 14px", cursor: "pointer", fontSize: 13, fontWeight: 600,
            }}>{t.label}</button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Sidebar */}
        <div style={{
          width: 280, background: C.surface, borderRight: `1px solid ${C.border}`,
          padding: 16, overflowY: "auto", flexShrink: 0,
        }}>
          <AssetList onSelect={setSelectedAsset} selectedId={selectedAsset?.asset_id} />
        </div>

        {/* Main */}
        <div style={{ flex: 1, padding: 20, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16 }}>
          {activeTab === "chart" && (
            <>
              {selectedAsset && (
                <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 22, fontWeight: 800 }}>{selectedAsset.symbol}</span>
                  <Pill cls={selectedAsset.asset_class} />
                  <span style={{ color: C.muted, fontSize: 14 }}>{selectedAsset.description}</span>
                  <div style={{ marginLeft: "auto" }}>
                    <SourceSelector selectedSource={selectedSource} onSelect={setSelectedSource} />
                  </div>
                </div>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, flex: 1 }}>
                <Card style={{ minHeight: 340 }}>
                  <PriceChart
                    assetId={selectedAsset?.asset_id}
                    sourceId={selectedSource?.source_id}
                  />
                </Card>
                <div>
                  <StatsPanel
                    assetId={selectedAsset?.asset_id}
                    sourceId={selectedSource?.source_id}
                  />
                </div>
              </div>
              {!selectedAsset && (
                <div style={{
                  flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                  flexDirection: "column", gap: 12, color: C.muted,
                }}>
                  <div style={{ fontSize: 48 }}>📊</div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: C.text }}>Select an asset to begin</div>
                  <div style={{ fontSize: 14 }}>Choose from the sidebar to explore price history and forecasts</div>
                </div>
              )}
            </>
          )}

          {activeTab === "assistant" && (
            <Card style={{ flex: 1, minHeight: 500 }}>
              <ChatPanel />
            </Card>
          )}
        </div>
      </div>

      <style>{`
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${C.border}; border-radius: 3px; }
        input::placeholder { color: ${C.muted}; }
        @keyframes blink { 0%, 100% { opacity: 1 } 50% { opacity: 0.3 } }
      `}</style>
    </div>
  );
}
