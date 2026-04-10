import { useEffect, useState, useCallback } from "react";

const PROXY = import.meta.env.VITE_PROXY_URL ?? "";

interface Model {
  id: string;
  role: string;
  speed_tps: number | null;
  price_per_1k: number | null;
  supports_vision: boolean;
  supports_audio: boolean;
  supports_image_gen: boolean;
}

interface VirtualModel {
  id: string;
  maps_to: string;
  description: string;
}

const ROLE_LABELS: Record<string, { label: string; color: string }> = {
  default:        { label: "Основная",     color: "#E30611" },
  general:        { label: "Общая",        color: "#9ca3af" },
  general_fast:   { label: "Быстрая",      color: "#4ade80" },
  general_large:  { label: "Большая",      color: "#60a5fa" },
  code:           { label: "Код",          color: "#38bdf8" },
  reasoning:      { label: "Рассуждение",  color: "#a78bfa" },
  reasoning_alt:  { label: "Рассуждение",  color: "#a78bfa" },
  complex:        { label: "Сложная",      color: "#f472b6" },
  vision:         { label: "Зрение",       color: "#fb923c" },
  vision_alt:     { label: "Зрение",       color: "#fb923c" },
  audio:          { label: "Аудио",        color: "#34d399" },
  audio_alt:      { label: "Аудио",        color: "#34d399" },
  image_gen:      { label: "Генерация",    color: "#fbbf24" },
  image_gen_alt:  { label: "Генерация",    color: "#fbbf24" },
  embeddings:     { label: "Эмбеддинг",    color: "#94a3b8" },
  llama:          { label: "Llama",        color: "#818cf8" },
  llama_fast:     { label: "Llama",        color: "#818cf8" },
  kimi:           { label: "Kimi",         color: "#2dd4bf" },
  glm:            { label: "GLM",          color: "#c084fc" },
  gemma:          { label: "Gemma",        color: "#fb7185" },
  mts:            { label: "MTS",          color: "#E30611" },
  mws_alpha:      { label: "MWS Alpha",   color: "#f59e0b" },
};

function RoleBadge({ role }: { role: string }) {
  const info = ROLE_LABELS[role] ?? { label: role, color: "#6b7280" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600,
      background: `${info.color}18`, color: info.color, letterSpacing: 0.3,
      textTransform: "uppercase",
    }}>
      {info.label}
    </span>
  );
}

function Caps({ vision, audio, image_gen }: { vision: boolean; audio: boolean; image_gen: boolean }) {
  const caps: string[] = [];
  if (vision) caps.push("👁 Vision");
  if (audio) caps.push("🎙 Audio");
  if (image_gen) caps.push("🎨 Image");
  if (!caps.length) return <span style={{ color: "var(--text-faint)" }}>—</span>;
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {caps.map(c => (
        <span key={c} style={{
          fontSize: 11, padding: "1px 7px", borderRadius: 12,
          background: "var(--bg-elevated)", color: "var(--text-dim)",
          border: "1px solid var(--border)",
        }}>{c}</span>
      ))}
    </div>
  );
}

export default function ModelCatalog() {
  const [models, setModels]     = useState<Model[]>([]);
  const [virtuals, setVirtuals] = useState<VirtualModel[]>([]);
  const [loading, setLoading]   = useState(true);
  const [filter, setFilter]     = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${PROXY}/api/models/catalog`);
      const d = await r.json();
      setModels(d.models ?? []);
      setVirtuals(d.virtual ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = models.filter(m => {
    if (!filter) return true;
    const q = filter.toLowerCase();
    return m.id.toLowerCase().includes(q) || m.role.toLowerCase().includes(q);
  });

  const categories = [
    { key: "text",  label: "Текстовые модели", test: (m: Model) => !m.supports_vision && !m.supports_audio && !m.supports_image_gen && m.role !== "embeddings" },
    { key: "multi", label: "Мультимодальные", test: (m: Model) => m.supports_vision || m.supports_audio || m.supports_image_gen },
    { key: "embed", label: "Эмбеддинги", test: (m: Model) => m.role === "embeddings" },
  ];

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title"><span>Model</span> Catalog</h1>
        <button className="btn btn-ghost" onClick={load} disabled={loading} style={{ marginLeft: "auto" }}>
          {loading ? "↻" : "↻ Обновить"}
        </button>
      </div>

      {/* Stat tiles */}
      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-tile-value red">{models.length}</div>
          <div className="stat-tile-label">Моделей доступно</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-value">{virtuals.length}</div>
          <div className="stat-tile-label">Virtual aliases</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-value">{models.filter(m => m.supports_vision).length}</div>
          <div className="stat-tile-label">Vision</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-value">{models.filter(m => m.supports_audio).length}</div>
          <div className="stat-tile-label">Audio</div>
        </div>
      </div>

      {/* Virtual model aliases */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Virtual Aliases (Smart Router)</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
          {virtuals.map(v => (
            <div key={v.id} style={{
              background: "var(--bg-elevated)", borderRadius: "var(--r)",
              padding: "14px 16px", border: "1px solid var(--border)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{
                  fontFamily: "monospace", fontWeight: 700, fontSize: 14,
                  color: v.id === "auto" ? "var(--red)" : "var(--text)",
                }}>{v.id}</span>
                {v.id === "auto" && (
                  <span style={{
                    fontSize: 9, fontWeight: 700, textTransform: "uppercase",
                    background: "var(--red)", color: "#fff",
                    padding: "1px 6px", borderRadius: 10, letterSpacing: 0.5,
                  }}>smart</span>
                )}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-faint)", marginBottom: 6, lineHeight: 1.4 }}>
                {v.description}
              </div>
              <div style={{
                fontSize: 11, fontFamily: "monospace", color: "var(--text-dim)",
                background: "var(--bg-card)", padding: "3px 8px", borderRadius: 6,
                display: "inline-block",
              }}>
                → {v.maps_to}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Search */}
      <div style={{ marginBottom: 16 }}>
        <input
          className="input-field"
          placeholder="Поиск по имени или роли модели…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{ maxWidth: 400 }}
        />
      </div>

      {/* Model tables by category */}
      {categories.map(cat => {
        const items = filtered.filter(cat.test);
        if (!items.length) return null;
        return (
          <div key={cat.key} className="card">
            <div className="card-header">
              <div className="card-title">{cat.label}</div>
              <span style={{ fontSize: 12, color: "var(--text-faint)" }}>{items.length} моделей</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Модель</th>
                    <th>Роль</th>
                    <th>Скорость</th>
                    <th>Цена / 1K</th>
                    <th>Возможности</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(m => (
                    <tr key={m.id}>
                      <td>
                        <span style={{ fontFamily: "monospace", fontSize: 12.5, color: "var(--text)" }}>
                          {m.id}
                        </span>
                      </td>
                      <td><RoleBadge role={m.role} /></td>
                      <td style={{
                        fontVariantNumeric: "tabular-nums", fontWeight: 600,
                        color: m.speed_tps ? (m.speed_tps > 5000 ? "#4ade80" : "#facc15") : "var(--text-faint)",
                      }}>
                        {m.speed_tps ? `${m.speed_tps} tps` : "—"}
                      </td>
                      <td style={{
                        fontVariantNumeric: "tabular-nums",
                        color: m.price_per_1k != null ? "var(--text)" : "var(--text-faint)",
                      }}>
                        {m.price_per_1k != null ? `₽${m.price_per_1k.toFixed(2)}` : "—"}
                      </td>
                      <td>
                        <Caps
                          vision={m.supports_vision}
                          audio={m.supports_audio}
                          image_gen={m.supports_image_gen}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
