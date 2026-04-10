import { useEffect, useState, useCallback } from "react";

const PROXY = import.meta.env.VITE_PROXY_URL ?? "";

interface Memory {
  id: string;
  user_id: string;
  scope: string;
  content: string;
  source_chat: string | null;
  relevance: number;
  created_at: string;
}

function fmtDate(s: string) {
  return new Date(s).toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

function RelevanceBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.round(value * 100));
  const color = pct > 70 ? "#4ade80" : pct > 40 ? "#facc15" : "#f87171";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{
        width: 48, height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden",
      }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 11, color: "var(--text-faint)", fontVariantNumeric: "tabular-nums" }}>
        {value.toFixed(2)}
      </span>
    </div>
  );
}

export default function MemoryViewer() {
  const [userId,        setUserId]        = useState("default");
  const [inputId,       setInputId]       = useState("default");
  const [memories,      setMemories]      = useState<Memory[]>([]);
  const [query,         setQuery]         = useState("");
  const [searchResults, setSearchResults] = useState<string[] | null>(null);
  const [loading,       setLoading]       = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [deletingId,    setDeletingId]    = useState<string | null>(null);

  const load = useCallback(async (uid: string) => {
    setLoading(true);
    setSearchResults(null);
    try {
      const r = await fetch(`${PROXY}/api/memory?user_id=${encodeURIComponent(uid)}&limit=100`);
      setMemories(await r.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(userId); }, [userId, load]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearchLoading(true);
    fetch(`${PROXY}/api/memory/search?user_id=${encodeURIComponent(userId)}&query=${encodeURIComponent(query)}&top_k=5`)
      .then(r => r.json())
      .then(d => setSearchResults(d.results))
      .finally(() => setSearchLoading(false));
  }

  async function del(id: string) {
    setDeletingId(id);
    try {
      await fetch(`${PROXY}/api/memory/${id}`, { method: "DELETE" });
      setMemories(ms => ms.filter(m => m.id !== id));
    } finally {
      setDeletingId(null);
    }
  }

  async function deleteAll() {
    if (!confirm(`Удалить все ${memories.length} воспоминаний пользователя «${userId}»?`)) return;
    for (const m of memories) {
      await fetch(`${PROXY}/api/memory/${m.id}`, { method: "DELETE" });
    }
    setMemories([]);
  }

  const scopeGroups = memories.reduce<Record<string, number>>((acc, m) => {
    acc[m.scope] = (acc[m.scope] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title"><span>Memory</span> Viewer</h1>
      </div>

      {/* Stat tiles */}
      <div className="stat-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px,1fr))" }}>
        <div className="stat-tile">
          <div className="stat-tile-value red">{memories.length}</div>
          <div className="stat-tile-label">Воспоминаний</div>
        </div>
        {Object.entries(scopeGroups).map(([scope, cnt]) => (
          <div key={scope} className="stat-tile">
            <div className="stat-tile-value">{cnt}</div>
            <div className="stat-tile-label">scope: {scope}</div>
          </div>
        ))}
      </div>

      {/* User selector */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Пользователь</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="input-field"
            value={inputId}
            onChange={e => setInputId(e.target.value)}
            onKeyDown={e => e.key === "Enter" && setUserId(inputId)}
            placeholder="user_id"
          />
          <button className="btn btn-primary" onClick={() => setUserId(inputId)}>
            Загрузить
          </button>
          <button className="btn btn-ghost btn-icon" onClick={() => load(userId)} disabled={loading}
                  title="Обновить">
            ↻
          </button>
        </div>
      </div>

      {/* Semantic search */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Семантический поиск</div>
          {searchResults && (
            <button className="btn btn-ghost" style={{ fontSize: 12, padding: "4px 10px" }}
                    onClick={() => setSearchResults(null)}>
              × Сбросить
            </button>
          )}
        </div>
        <form onSubmit={handleSearch} style={{ display: "flex", gap: 8 }}>
          <input
            className="input-field"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Найти релевантные воспоминания по смыслу…"
          />
          <button className="btn btn-primary" type="submit"
                  disabled={searchLoading || !query.trim()}>
            {searchLoading ? "…" : "🔍 Найти"}
          </button>
        </form>

        {searchResults && (
          <div style={{ marginTop: 14 }}>
            {searchResults.length === 0 ? (
              <div className="empty" style={{ padding: "20px 0" }}>
                <div>Ничего не найдено</div>
              </div>
            ) : (
              searchResults.map((r, i) => (
                <div key={i} className="search-result">
                  <div className="search-result-num">{i + 1}</div>
                  <div>{r}</div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* Memory list */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">
            Воспоминания
            <span style={{ fontSize: 12, fontWeight: 400, color: "var(--text-faint)", marginLeft: 6 }}>
              {memories.length} · {userId}
            </span>
          </div>
          {memories.length > 0 && (
            <button className="btn btn-danger" onClick={deleteAll}
                    style={{ fontSize: 12, padding: "5px 12px" }}>
              🗑 Удалить все
            </button>
          )}
        </div>

        {loading ? (
          <div className="empty"><div>Загрузка…</div></div>
        ) : memories.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">🧠</div>
            <div>Нет воспоминаний</div>
            <div style={{ fontSize: 12 }}>Поговорите с моделью через OpenWebUI</div>
          </div>
        ) : (
          <div className="mem-list">
            {memories.map((m, i) => (
              <div key={m.id} className="mem-item">
                <div className="mem-num">{i + 1}</div>
                <div className="mem-body">
                  <div className="mem-content">{m.content}</div>
                  <div className="mem-meta">
                    <span>📁 {m.scope}</span>
                    <span><RelevanceBar value={m.relevance} /></span>
                    <span>🕐 {fmtDate(m.created_at)}</span>
                  </div>
                </div>
                <button
                  className="btn btn-danger btn-icon"
                  style={{ fontSize: 12, padding: "5px 9px", flexShrink: 0 }}
                  disabled={deletingId === m.id}
                  onClick={() => del(m.id)}
                >
                  {deletingId === m.id ? "…" : "✕"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
