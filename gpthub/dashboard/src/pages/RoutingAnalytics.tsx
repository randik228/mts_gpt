import { useEffect, useState, useCallback } from "react";

const PROXY = import.meta.env.VITE_PROXY_URL ?? "";

interface Decision {
  id: string;
  ts: number;
  user_id: string;
  requested: string;
  routed_to: string;
  method: string;
  reason: string;
  latency_ms: number | null;
}

interface ModelStat {
  model: string;
  calls: number;
  avg_latency_ms: number | null;
  keyword_hits: number;
  embedding_hits: number;
  multimodal_hits: number;
  last_used: number;
}

function MethodBadge({ method }: { method: string }) {
  return <span className={`badge badge-${method}`}>{method}</span>;
}

function fmt(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString("ru-RU", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function shortModel(m: string) {
  return m.length > 26 ? m.slice(0, 24) + "…" : m;
}

function latencyColor(ms: number) {
  if (ms < 1000) return "#4ade80";
  if (ms < 3000) return "#facc15";
  return "#f87171";
}

export default function RoutingAnalytics() {
  const [stats, setStats]         = useState<ModelStat[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading]     = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${PROXY}/api/analytics/routing?limit=100`);
      const d = await r.json();
      setStats(d.stats ?? []);
      setDecisions(d.decisions ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [load]);

  const maxCalls = stats.reduce((m, s) => Math.max(m, s.calls), 1);
  const total    = stats.reduce((s, x) => s + x.calls, 0);
  const avgLat   = (() => {
    const valid = stats.filter(s => s.avg_latency_ms != null);
    if (!valid.length) return null;
    return Math.round(valid.reduce((s, x) => s + x.avg_latency_ms!, 0) / valid.length);
  })();
  const topModel = stats[0]?.model ?? "—";

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title"><span>Routing</span> Analytics</h1>
        <button className="btn btn-ghost" onClick={load} disabled={loading} style={{ marginLeft: "auto" }}>
          {loading ? "↻" : "↻ Обновить"}
        </button>
        <span className="page-meta">авто-обновление 10 с</span>
      </div>

      {/* Stat tiles */}
      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-tile-value red">{total}</div>
          <div className="stat-tile-label">Всего вызовов</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-value">{stats.length}</div>
          <div className="stat-tile-label">Моделей активно</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-value" style={{ fontSize: 18, letterSpacing: -0.3 }}>
            {avgLat != null ? `${avgLat} ms` : "—"}
          </div>
          <div className="stat-tile-label">Avg latency</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-value" style={{ fontSize: 14, letterSpacing: -0.3, marginTop: 4 }}>
            {shortModel(topModel)}
          </div>
          <div className="stat-tile-label">Топ модель</div>
        </div>
      </div>

      {/* Bar chart */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Вызовы по моделям</div>
        </div>
        {stats.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">📭</div>
            <div>Нет данных — отправьте сообщение через OpenWebUI</div>
          </div>
        ) : (
          stats.map((s) => (
            <div key={s.model} className="bar-row" title={s.model}>
              <span className="bar-label">{shortModel(s.model)}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(s.calls / maxCalls) * 100}%` }} />
              </div>
              <span className="bar-count">{s.calls}</span>
            </div>
          ))
        )}
      </div>

      {/* Stats table */}
      {stats.length > 0 && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">Детали по моделям</div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Модель</th>
                  <th>Вызовов</th>
                  <th>Avg latency</th>
                  <th>Keyword</th>
                  <th>Embedding</th>
                  <th>Multimodal</th>
                </tr>
              </thead>
              <tbody>
                {stats.map((s) => (
                  <tr key={s.model}>
                    <td style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text-dim)" }}>
                      {s.model}
                    </td>
                    <td><strong style={{ color: "var(--text)" }}>{s.calls}</strong></td>
                    <td style={{
                      color: s.avg_latency_ms != null ? latencyColor(s.avg_latency_ms) : "var(--text-faint)",
                      fontWeight: 600,
                    }}>
                      {s.avg_latency_ms != null ? `${Math.round(s.avg_latency_ms)} ms` : "—"}
                    </td>
                    <td style={{ color: s.keyword_hits ? "#60a5fa" : "var(--text-faint)" }}>
                      {s.keyword_hits || "—"}
                    </td>
                    <td style={{ color: s.embedding_hits ? "#4ade80" : "var(--text-faint)" }}>
                      {s.embedding_hits || "—"}
                    </td>
                    <td style={{ color: s.multimodal_hits ? "var(--purple)" : "var(--text-faint)" }}>
                      {s.multimodal_hits || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent decisions */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Последние решения роутера</div>
          <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
            показаны последние {Math.min(decisions.length, 50)}
          </span>
        </div>
        {decisions.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">🕐</div>
            <div>История пуста</div>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Запрошено</th>
                  <th>→ Выбрано</th>
                  <th>Метод</th>
                  <th>Причина</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                {decisions.slice(0, 50).map((d) => (
                  <tr key={d.id}>
                    <td style={{ color: "var(--text-faint)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                      {fmt(d.ts)}
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text-dim)" }}>
                      {d.requested}
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text)" }}>
                      {shortModel(d.routed_to)}
                    </td>
                    <td><MethodBadge method={d.method} /></td>
                    <td style={{ color: "var(--text-faint)", fontSize: 12, maxWidth: 200 }}>
                      {d.reason}
                    </td>
                    <td style={{
                      fontVariantNumeric: "tabular-nums",
                      color: d.latency_ms != null ? latencyColor(d.latency_ms) : "var(--text-faint)",
                      fontWeight: 600,
                    }}>
                      {d.latency_ms != null ? `${Math.round(d.latency_ms)} ms` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
