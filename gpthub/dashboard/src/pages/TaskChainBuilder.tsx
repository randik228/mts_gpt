import { useState, useRef } from "react";

const PROXY = import.meta.env.VITE_PROXY_URL ?? "";

// ── Templates ──────────────────────────────────────────────────────────────

interface StepDef {
  type: "chat" | "transcribe" | "embed";
  model: string;
  input_template: string;
  output_key: string;
  system?: string;
}

interface Template {
  id: string;
  name: string;
  emoji: string;
  description: string;
  inputs: { key: string; label: string; placeholder: string; multiline?: boolean }[];
  steps: StepDef[];
}

const TEMPLATES: Template[] = [
  {
    id: "voice_to_code",
    name: "Голос в код",
    emoji: "🎙️",
    description: "Аудио → транскрипция → готовый код на Python",
    inputs: [
      { key: "audio_path", label: "Путь к аудиофайлу внутри контейнера", placeholder: "/app/data/audio.wav" },
    ],
    steps: [
      { type: "transcribe", model: "whisper-turbo-local",
        input_template: "{{audio_path}}", output_key: "transcription" },
      { type: "chat", model: "qwen3-coder-480b-a35b",
        input_template: "Напиши код на Python для следующей задачи:\n\n{{transcription}}",
        output_key: "code" },
      { type: "chat", model: "gpt-oss-20b",
        input_template: "Объясни следующий код простыми словами:\n\n```python\n{{code}}\n```",
        output_key: "explanation" },
    ],
  },
  {
    id: "doc_analyze",
    name: "Документ → Анализ",
    emoji: "📄",
    description: "Текст документа → глубокий анализ → краткое резюме",
    inputs: [
      { key: "document", label: "Текст документа", placeholder: "Вставьте текст документа…", multiline: true },
    ],
    steps: [
      { type: "chat", model: "deepseek-r1-distill-qwen-32b",
        input_template: "Проанализируй документ. Найди ключевые тезисы, противоречия и выводы:\n\n{{document}}",
        output_key: "analysis",
        system: "Ты аналитик. Рассуждай пошагово внутри <think>...</think>." },
      { type: "chat", model: "gpt-oss-20b",
        input_template: "На основе анализа составь краткое резюме (5–7 пунктов):\n\n{{analysis}}",
        output_key: "summary" },
    ],
  },
  {
    id: "image_to_code",
    name: "Картинка → Код",
    emoji: "🖼️",
    description: "Описание UI → архитектура → реализация на Python",
    inputs: [
      { key: "image_description", label: "Опишите изображение / UI / схему",
        placeholder: "Скриншот формы с полями: имя, email, кнопка «Отправить»…", multiline: true },
    ],
    steps: [
      { type: "chat", model: "gpt-oss-20b",
        input_template: "Что нужно реализовать?\n\n{{image_description}}",
        output_key: "requirements" },
      { type: "chat", model: "deepseek-r1-distill-qwen-32b",
        input_template: "Спланируй архитектуру реализации:\n\n{{requirements}}",
        output_key: "plan",
        system: "Ты архитектор. Рассуждай пошагово." },
      { type: "chat", model: "qwen3-coder-480b-a35b",
        input_template: "Реализуй план:\n\n{{plan}}\n\nТребования: {{requirements}}",
        output_key: "code" },
    ],
  },
  {
    id: "research_summary",
    name: "Тема → Исследование",
    emoji: "🔬",
    description: "Тема → детальное исследование → резюме на русском",
    inputs: [
      { key: "topic", label: "Тема для исследования", placeholder: "Квантовые вычисления в криптографии" },
    ],
    steps: [
      { type: "chat", model: "Qwen3-235B-A22B-Instruct-2507-FP8",
        input_template: "Проведи детальное исследование: {{topic}}\nОхвати историю, состояние, применение, перспективы.",
        output_key: "research" },
      { type: "chat", model: "gpt-oss-20b",
        input_template: "Сократи до 5 ключевых выводов на русском:\n\n{{research}}",
        output_key: "summary" },
    ],
  },
];

// ── SSE event types ────────────────────────────────────────────────────────

interface SseEvent {
  event: string;
  step?: number;
  total?: number;
  type?: string;
  model?: string;
  delta?: string;
  output_key?: string;
  output?: string;
  error?: string;
  context?: Record<string, string>;
}

interface LogLine { cls: string; text: string; }

// ── Step type badge ────────────────────────────────────────────────────────

const TYPE_COLOR: Record<string, string> = {
  chat:       "var(--blue)",
  transcribe: "var(--purple)",
  embed:      "var(--green)",
};

// ── Component ─────────────────────────────────────────────────────────────

export default function TaskChainBuilder() {
  const [selected, setSelected] = useState<Template>(TEMPLATES[0]);
  const [inputs,   setInputs]   = useState<Record<string, string>>({});
  const [running,  setRunning]  = useState(false);
  const [log,      setLog]      = useState<LogLine[]>([]);
  const [context,  setContext]  = useState<Record<string, string> | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  function appendLog(cls: string, text: string) {
    setLog(prev => [...prev, { cls, text }]);
    setTimeout(() => logRef.current?.scrollTo({ top: 1e9, behavior: "smooth" }), 30);
  }

  async function run() {
    const steps = selected.steps.map(s => ({ ...s }));
    setRunning(true);
    setLog([]);
    setContext(null);
    appendLog("log-chain", `▶ Запуск «${selected.name}» · ${steps.length} шагов`);

    try {
      const resp = await fetch(`${PROXY}/api/taskchain/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ steps, context: inputs }),
      });
      if (!resp.body) throw new Error("No response body");

      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") { appendLog("log-chain", "✅ Готово"); break; }
          let ev: SseEvent;
          try { ev = JSON.parse(raw); } catch { continue; }

          if (ev.event === "step_start") {
            appendLog("log-start",
              `\n[${(ev.step ?? 0) + 1}/${ev.total}] ${ev.type?.toUpperCase()} · ${ev.model}`);
          } else if (ev.event === "step_delta") {
            appendLog("log-delta", ev.delta ?? "");
          } else if (ev.event === "step_done") {
            appendLog("log-done", `\n✓ ${ev.output_key} · ${(ev.output ?? "").length} chars`);
          } else if (ev.event === "step_error") {
            appendLog("log-error", `\n✗ ${ev.error}`);
          } else if (ev.event === "chain_done") {
            setContext(ev.context ?? {});
          } else if (ev.event === "chain_error") {
            appendLog("log-error", `\n✗ Ошибка: ${ev.error}`);
          }
        }
      }
    } catch (e: unknown) {
      appendLog("log-error", `\n✗ ${String(e)}`);
    } finally {
      setRunning(false);
    }
  }

  function selectTemplate(t: Template) {
    setSelected(t);
    setInputs({});
    setLog([]);
    setContext(null);
  }

  // Check required inputs filled
  const allFilled = selected.inputs.every(inp => (inputs[inp.key] ?? "").trim().length > 0);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title"><span>Task Chain</span> Builder</h1>
      </div>

      {/* Template grid */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Выберите шаблон</div>
        </div>
        <div className="template-grid">
          {TEMPLATES.map(t => (
            <div key={t.id}
              className={`template-card ${selected.id === t.id ? "selected" : ""}`}
              onClick={() => selectTemplate(t)}
            >
              <div className="template-emoji">{t.emoji}</div>
              <div className="template-name">{t.name}</div>
              <div className="template-desc">{t.description}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Steps preview */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">{selected.name} · шаги</div>
          <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
            {selected.steps.length} шага
          </span>
        </div>
        <div className="steps-list">
          {selected.steps.map((s, i) => (
            <div key={i} className="step-row">
              <div className="step-num">{i + 1}</div>
              <div className="step-type" style={{ color: TYPE_COLOR[s.type] ?? "var(--text-dim)" }}>
                {s.type}
              </div>
              <div className="step-model">{s.model}</div>
              <span className="step-arrow">→</span>
              <span className="step-key">{s.output_key}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Inputs */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Входные данные</div>
        </div>
        {selected.inputs.map(inp => (
          <div key={inp.key} className="input-row">
            <label>{inp.label}</label>
            {inp.multiline ? (
              <textarea
                rows={4}
                value={inputs[inp.key] ?? ""}
                onChange={e => setInputs(prev => ({ ...prev, [inp.key]: e.target.value }))}
                placeholder={inp.placeholder}
              />
            ) : (
              <input
                type="text"
                value={inputs[inp.key] ?? ""}
                onChange={e => setInputs(prev => ({ ...prev, [inp.key]: e.target.value }))}
                placeholder={inp.placeholder}
              />
            )}
          </div>
        ))}
        <button
          className="btn btn-primary"
          onClick={run}
          disabled={running || !allFilled}
          style={{ marginTop: 4, minWidth: 180 }}
        >
          {running
            ? <><span style={{ animation: "mts-pulse 1s infinite" }}>⏳</span> Выполняется…</>
            : "▶ Запустить цепочку"}
        </button>
        {!allFilled && !running && (
          <span style={{ fontSize: 12, color: "var(--text-faint)", marginLeft: 12 }}>
            Заполните все поля
          </span>
        )}
      </div>

      {/* SSE log */}
      {(log.length > 0 || running) && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">Прогресс выполнения</div>
            {running && (
              <span style={{ fontSize: 12, color: "var(--red)", fontWeight: 600,
                             animation: "mts-pulse 1s ease-in-out infinite" }}>
                ● LIVE
              </span>
            )}
          </div>
          <div className="sse-log" ref={logRef}>
            {log.map((l, i) =>
              l.cls === "log-delta"
                ? <span key={i} className={l.cls}>{l.text}</span>
                : <div key={i} className={l.cls}>{l.text}</div>
            )}
            {running && <span style={{ color: "var(--red)", animation: "mts-pulse 0.8s infinite" }}>█</span>}
          </div>
        </div>
      )}

      {/* Results */}
      {context && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">Результаты</div>
            <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
              {Object.keys(context).length} переменных
            </span>
          </div>
          <div className="results-grid">
            {Object.entries(context).map(([key, value]) => (
              <div key={key} className="result-block">
                <div className="result-label">
                  <span>📦</span> {key}
                  <span style={{ marginLeft: "auto", fontWeight: 400, textTransform: "none",
                                 letterSpacing: 0, color: "var(--text-faint)" }}>
                    {value.length} chars
                  </span>
                </div>
                <pre className="result-pre">
                  {value.length > 2000 ? value.slice(0, 2000) + "\n…[truncated]" : value}
                </pre>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
