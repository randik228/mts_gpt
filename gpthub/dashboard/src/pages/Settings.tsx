import { useState, useEffect } from "react";

const PROXY = import.meta.env.VITE_PROXY_URL || "";

export default function Settings() {
  const [apiKeyMasked, setApiKeyMasked] = useState("");
  const [apiKeySet, setApiKeySet] = useState(false);
  const [apiBase, setApiBase] = useState("");
  const [newKey, setNewKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${PROXY}/api/settings`);
        const data = await r.json();
        setApiKeyMasked(data.api_key_masked || "");
        setApiKeySet(data.api_key_set || false);
        setApiBase(data.api_base || "");
      } catch {
        setMsg("Failed to load settings");
      }
    })();
  }, []);

  const handleSave = async () => {
    if (!newKey.trim()) return;
    setSaving(true);
    setMsg("");
    try {
      const r = await fetch(`${PROXY}/api/settings/api-key`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: newKey.trim() }),
      });
      const data = await r.json();
      if (r.ok) {
        setApiKeyMasked(data.api_key_masked || "");
        setApiKeySet(true);
        setNewKey("");
        setMsg("API key updated successfully");
      } else {
        setMsg(data.detail || "Failed to update");
      }
    } catch {
      setMsg("Network error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 600, margin: "0 auto" }}>
      <h2>Settings</h2>

      <div className="card" style={{ padding: 24, marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>MWS API Key</h3>
        <p style={{ color: "#999", fontSize: 14 }}>
          API key is stored as an environment variable and never exposed in the repository.
          You can update it here at runtime.
        </p>

        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 4, fontWeight: 600 }}>
            Current key:
          </label>
          <code style={{
            background: "#1a1a2e",
            padding: "8px 12px",
            borderRadius: 6,
            display: "inline-block",
            color: apiKeySet ? "#4ade80" : "#ef4444",
          }}>
            {apiKeySet ? apiKeyMasked : "Not set"}
          </code>
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 4, fontWeight: 600 }}>
            API Base URL:
          </label>
          <code style={{
            background: "#1a1a2e",
            padding: "8px 12px",
            borderRadius: 6,
            display: "inline-block",
          }}>
            {apiBase || "Not configured"}
          </code>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="password"
            className="input-field"
            placeholder="Enter new API key..."
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSave()}
            style={{ flex: 1 }}
          />
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving || !newKey.trim()}
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>

        {msg && (
          <p style={{
            marginTop: 8,
            color: msg.includes("success") ? "#4ade80" : "#ef4444",
            fontSize: 14,
          }}>
            {msg}
          </p>
        )}
      </div>

      <div className="card" style={{ padding: 24 }}>
        <h3 style={{ marginTop: 0 }}>Instructions</h3>
        <p style={{ color: "#999", fontSize: 14, lineHeight: 1.6 }}>
          1. Get your API key from <a href="https://api.gpt.mws.ru" target="_blank" style={{ color: "#60a5fa" }}>api.gpt.mws.ru</a><br />
          2. Paste it in the field above and click Save<br />
          3. The key is persisted across container restarts<br />
          4. For initial setup, you can also set it via <code>.env</code> file: <code>MWS_API_KEY=your_key</code><br />
          5. The key is <strong>never</strong> stored in the git repository
        </p>
      </div>
    </div>
  );
}
