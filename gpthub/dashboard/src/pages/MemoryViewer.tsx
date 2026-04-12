import { useEffect, useState, useCallback } from "react";

const PROXY = import.meta.env.VITE_PROXY_URL ?? "";

interface Memory {
  id: string;
  user_id: string;
  scope: string;
  content: string;
  source_chat: string | null;
  relevance: number;
  tag: string;
  importance: number;
  created_at: string;
}

type ScopeMode = "personal" | "team";

function fmtDate(s: string) {
  return new Date(s).toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

const TAG_STYLES: Record<string, { bg: string; color: string; emoji: string }> = {
  fact:       { bg: "rgba(96,165,250,.15)",  color: "#60a5fa", emoji: "📌" },
  skill:     { bg: "rgba(52,211,153,.15)",  color: "#34d399", emoji: "⚡" },
  preference: { bg: "rgba(251,191,36,.15)",  color: "#fbbf24", emoji: "⭐" },
  project:   { bg: "rgba(167,139,250,.15)", color: "#a78bfa", emoji: "📂" },
  context:   { bg: "rgba(244,114,182,.15)", color: "#f472b6", emoji: "🔗" },
};

function TagBadge({ tag }: { tag: string }) {
  const s = TAG_STYLES[tag] ?? TAG_STYLES.fact;
  return (
    <span style={{
      background: s.bg, color: s.color, borderRadius: 4,
      padding: "1px 6px", fontSize: 10, fontWeight: 600,
    }}>
      {s.emoji} {tag}
    </span>
  );
}

function ImportanceBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.round(value * 100));
  const color = pct >= 80 ? "#4ade80" : pct >= 60 ? "#facc15" : "#f87171";
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

/** Personal / Team scope toggle */
function ScopeToggle({
  value, onChange,
}: { value: ScopeMode; onChange: (v: ScopeMode) => void }) {
  const btn = (mode: ScopeMode, label: string, emoji: string) => (
    <button
      onClick={() => onChange(mode)}
      style={{
        flex: 1,
        padding: "6px 0",
        fontSize: 12,
        fontWeight: value === mode ? 600 : 400,
        borderRadius: 8,
        border: "none",
        cursor: "pointer",
        background: value === mode ? "var(--accent)" : "transparent",
        color: value === mode ? "#fff" : "var(--text-faint)",
        transition: "all .15s",
      }}
    >
      {emoji} {label}
    </button>
  );
  return (
    <div style={{
      display: "flex",
      background: "var(--surface2)",
      border: "1px solid var(--border)",
      borderRadius: 10,
      padding: 3,
      gap: 3,
      width: 220,
    }}>
      {btn("personal", "Личная", "👤")}
      {btn("team", "Командная", "👥")}
    </div>
  );
}

/** Add-to-team-memory form */
function AddTeamMemory({ onAdded }: { onAdded: () => void }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSaving(true);
    try {
      await fetch(`${PROXY}/api/memory`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text.trim(), scope: "team" }),
      });
      setText("");
      onAdded();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", gap: 8, marginTop: 8 }}>
      <input
        className="input-field"
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder="Добавить командное воспоминание…"
        style={{ flex: 1 }}
      />
      <button className="btn btn-primary" type="submit" disabled={saving || !text.trim()}>
        {saving ? "…" : "+ Добавить"}
      </button>
    </form>
  );
}

export default function MemoryViewer() {
  const [scopeMode,     setScopeMode]     = useState<ScopeMode>("personal");
  const [userId,        setUserId]        = useState("");
  const [inputId,       setInputId]       = useState("");
  const [knownUsers,    setKnownUsers]    = useState<string[]>([]);
  const [memories,      setMemories]      = useState<Memory[]>([]);
  const [query,         setQuery]         = useState("");
  const [searchResults, setSearchResults] = useState<string[] | null>(null);
  const [loading,       setLoading]       = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [deletingId,    setDeletingId]    = useState<string | null>(null);

  const load = useCallback(async (uid: string, mode: ScopeMode) => {
    setLoading(true);
    setSearchResults(null);
    try {
      const url = mode === "team"
        ? `${PROXY}/api/memory?scope=team&limit=200`
        : `${PROXY}/api/memory?user_id=${encodeURIComponent(uid)}&scope=personal&limit=100`;
      const r = await fetch(url);
      const data = await r.json();
      setMemories(Array.isArray(data) ? data : []);
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-detect first available user on mount
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${PROXY}/api/memory/users`);
        const data = await r.json();
        const users: string[] = data.users ?? [];
        setKnownUsers(users);
        if (users.length > 0) {
          setUserId(users[0]);
          setInputId(users[0]);
        } else {
          setUserId("default");
          setInputId("default");
        }
      } catch {
        setUserId("default");
        setInputId("default");
      }
    })();
  }, []);

  useEffect(() => { if (userId) load(userId, scopeMode); }, [userId, scopeMode, load]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearchLoading(true);
    fetch(
      `${PROXY}/api/memory/search?user_id=${encodeURIComponent(userId)}` +
      `&query=${encodeURIComponent(query)}&top_k=5&include_team=true`
    )
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

  const [deletingAll, setDeletingAll] = useState(false);

  async function deleteAll() {
    setDeletingAll(true);
    try {
      const scope = scopeMode === "team" ? "&scope=team" : "";
      const res = await fetch(
        `${PROXY}/api/memory?user_id=${encodeURIComponent(userId)}${scope}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        setMemories([]);
      } else {
        console.error("deleteAll response:", res.status, await res.text());
      }
    } catch (e) {
      console.error("deleteAll failed:", e);
    } finally {
      setDeletingAll(false);
    }
  }

  const scopeGroups = memories.reduce<Record<string, number>>((acc, m) => {
    acc[m.scope] = (acc[m.scope] ?? 0) + 1;
    return acc;
  }, {});

  const tagGroups = memories.reduce<Record<string, number>>((acc, m) => {
    const tag = m.tag ?? "fact";
    acc[tag] = (acc[tag] ?? 0) + 1;
    return acc;
  }, {});

  const isTeam = scopeMode === "team";

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
        {Object.entries(tagGroups).map(([tag, cnt]) => {
          const s = TAG_STYLES[tag] ?? TAG_STYLES.fact;
          return (
            <div key={tag} className="stat-tile">
              <div className="stat-tile-value" style={{ color: s.color }}>{cnt}</div>
              <div className="stat-tile-label">{s.emoji} {tag}</div>
            </div>
          );
        })}
      </div>

      {/* Scope + User selector */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Хранилище</div>
          <ScopeToggle value={scopeMode} onChange={mode => { setScopeMode(mode); }} />
        </div>

        {/* Personal: show user_id input */}
        {!isTeam && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            {knownUsers.length > 0 ? (
              <select
                className="input-field"
                value={userId}
                onChange={e => { setUserId(e.target.value); setInputId(e.target.value); }}
                style={{ flex: 1 }}
              >
                {knownUsers.map(u => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            ) : (
              <input
                className="input-field"
                value={inputId}
                onChange={e => setInputId(e.target.value)}
                onKeyDown={e => e.key === "Enter" && setUserId(inputId)}
                placeholder="user_id"
                style={{ flex: 1 }}
              />
            )}
            <button className="btn btn-ghost btn-icon" onClick={() => load(userId, scopeMode)}
                    disabled={loading} title="Обновить">
              ↻
            </button>
          </div>
        )}

        {/* Team: show refresh + add form */}
        {isTeam && (
          <div style={{ marginTop: 4 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
                Командные воспоминания доступны всем пользователям при поиске
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => load(userId, scopeMode)}
                      disabled={loading} title="Обновить">
                ↻
              </button>
            </div>
            <AddTeamMemory onAdded={() => load(userId, scopeMode)} />
          </div>
        )}
      </div>

      {/* Semantic search */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">
            Семантический поиск
            <span style={{ fontSize: 11, color: "var(--text-faint)", marginLeft: 6, fontWeight: 400 }}>
              личная + командная память
            </span>
          </div>
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
            {isTeam ? "👥 Командная память" : "👤 Личная память"}
            <span style={{ fontSize: 12, fontWeight: 400, color: "var(--text-faint)", marginLeft: 6 }}>
              {memories.length}{!isTeam && ` · ${userId}`}
            </span>
          </div>
          {memories.length > 0 && (
            <button className="btn btn-danger" onClick={deleteAll}
                    disabled={deletingAll}
                    style={{ fontSize: 12, padding: "5px 12px" }}>
              {deletingAll ? "⏳ Удаление..." : "🗑 Удалить все"}
            </button>
          )}
        </div>

        {loading ? (
          <div className="empty"><div>Загрузка…</div></div>
        ) : memories.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">🧠</div>
            <div>
              {isTeam
                ? "Нет командных воспоминаний"
                : "Нет воспоминаний"}
            </div>
            <div style={{ fontSize: 12 }}>
              {isTeam
                ? "Добавьте через форму выше"
                : "Поговорите с моделью через OpenWebUI"}
            </div>
          </div>
        ) : (
          <div className="mem-list">
            {memories.map((m, i) => (
              <div key={m.id} className="mem-item">
                <div className="mem-num">{i + 1}</div>
                <div className="mem-body">
                  <div className="mem-content">{m.content}</div>
                  <div className="mem-meta">
                    <TagBadge tag={m.tag ?? "fact"} />
                    <span
                      style={{
                        background: m.scope === "team"
                          ? "rgba(96,165,250,.15)"
                          : "rgba(167,139,250,.1)",
                        color: m.scope === "team" ? "#60a5fa" : "#a78bfa",
                        borderRadius: 4,
                        padding: "1px 6px",
                        fontSize: 10,
                        fontWeight: 600,
                      }}
                    >
                      {m.scope === "team" ? "👥 team" : "👤 personal"}
                    </span>
                    <span><ImportanceBar value={m.importance ?? m.relevance} /></span>
                    <span>🕐 {fmtDate(m.created_at)}</span>
                    {m.user_id && m.scope === "team" && (
                      <span style={{ fontSize: 10, color: "var(--text-faint)" }}>
                        от: {m.user_id === "__team__" ? "команда" : m.user_id}
                      </span>
                    )}
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
