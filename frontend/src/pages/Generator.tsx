import { useState, useEffect, useRef } from "react";
import { PromptInput } from "../components/PromptInput";
import { ProgressTracker } from "../components/ProgressTracker";
import { VideoPlayer } from "../components/VideoPlayer";
import { CodeViewer } from "../components/CodeViewer";
import { useSSE } from "../hooks/useSSE";

const MODELS = [
  { id: "claude-sonnet-4-6",       label: "Claude Sonnet 4.6",   provider: "Anthropic", keyPrefix: "sk-ant-",  keyPlaceholder: "sk-ant-..." },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5",  provider: "Anthropic", keyPrefix: "sk-ant-",  keyPlaceholder: "sk-ant-..." },
  { id: "gemini-2.5-flash",        label: "Gemini 2.5 Flash",    provider: "Google",    keyPrefix: "AIzaSy",   keyPlaceholder: "AIzaSy..." },
  { id: "gemini-2.0-flash",        label: "Gemini 2.0 Flash",    provider: "Google",    keyPrefix: "AIzaSy",   keyPlaceholder: "AIzaSy..." },
  { id: "llama-3.3-70b-versatile", label: "Llama 3.3 70B (Free)", provider: "Groq",     keyPrefix: "gsk_",     keyPlaceholder: "gsk_... (free at console.groq.com)" },
];

const STORAGE_MODEL = "selected_model";
const STORAGE_KEY   = (modelId: string) => `api_key_${modelId}`;

export function Generator() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [keySaved, setKeySaved] = useState(false);
  const [email, setEmail] = useState(() => localStorage.getItem("notify_email") ?? "");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [selectedModelId, setSelectedModelId] = useState(
    () => localStorage.getItem(STORAGE_MODEL) ?? MODELS[0].id
  );
  const [keys, setKeys] = useState<Record<string, string>>(() => {
    const saved: Record<string, string> = {};
    MODELS.forEach(m => { saved[m.id] = localStorage.getItem(STORAGE_KEY(m.id)) ?? ""; });
    return saved;
  });

  const model = MODELS.find(m => m.id === selectedModelId) ?? MODELS[0];
  const apiKey = keys[model.id] ?? "";

  useEffect(() => {
    localStorage.setItem(STORAGE_MODEL, selectedModelId);
  }, [selectedModelId]);

  useEffect(() => {
    MODELS.forEach(m => {
      if (keys[m.id]) localStorage.setItem(STORAGE_KEY(m.id), keys[m.id]);
      else localStorage.removeItem(STORAGE_KEY(m.id));
    });
  }, [keys]);

  const { step, attempt, error, result } = useSSE(jobId);

  const handleSaveKey = () => {
    // keys are already stored via the useEffect, just flash confirmation
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setKeySaved(true);
    saveTimerRef.current = setTimeout(() => setKeySaved(false), 2000);
  };

  const handleEmailChange = (val: string) => {
    setEmail(val);
    if (val.trim()) localStorage.setItem("notify_email", val.trim());
    else localStorage.removeItem("notify_email");
  };

  const handleSubmit = async (topic: string) => {
    setBusy(true);
    setFetchError(null);
    setJobId(null);

    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (apiKey.trim()) headers["X-API-Key"] = apiKey.trim();
      headers["X-Model"] = model.id;
      headers["X-Provider"] = model.provider;

      const res = await fetch("/api/generate", {
        method: "POST",
        headers,
        body: JSON.stringify({ topic, notify_email: email.trim() || undefined }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server error ${res.status}`);
      }
      const data = await res.json();
      setJobId(data.job_id);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const isFinished = step === "complete" || step === "error";
  if (isFinished && busy) setBusy(false);

  return (
    <div className="generator">
      <header className="hero">
        <h1 className="hero-title">
          <span className="accent">CS</span> Visualizer
        </h1>
        <p className="hero-sub">
          Turn any CS concept into a beautiful 720p animation with voiceover
        </p>
      </header>

      <div className="model-config">
        <div className="model-select-row">
          <label className="config-label">Model</label>
          <select
            className="model-select"
            value={selectedModelId}
            onChange={e => setSelectedModelId(e.target.value)}
          >
            {MODELS.map(m => (
              <option key={m.id} value={m.id}>
                {m.label} — {m.provider}
              </option>
            ))}
          </select>
        </div>

        <div className="api-key-row">
          <label className="config-label">{model.provider} Key</label>
          <input
            type={showKey ? "text" : "password"}
            className="api-key-input"
            placeholder={model.keyPlaceholder}
            value={apiKey}
            onChange={e => setKeys(k => ({ ...k, [model.id]: e.target.value }))}
            spellCheck={false}
          />
          <button className="toggle-key-btn" onClick={() => setShowKey(v => !v)}>
            {showKey ? "Hide" : "Show"}
          </button>
          <button
            className={`save-key-btn${keySaved ? " saved" : ""}`}
            onClick={handleSaveKey}
          >
            {keySaved ? "Saved ✓" : "Save"}
          </button>
        </div>

        <div className="email-row">
          <label className="config-label">Notify Email</label>
          <input
            type="email"
            className="api-key-input"
            placeholder="you@example.com (optional — get emailed when done)"
            value={email}
            onChange={e => handleEmailChange(e.target.value)}
            spellCheck={false}
          />
        </div>
      </div>

      <PromptInput onSubmit={handleSubmit} disabled={busy} />

      {fetchError && (
        <div className="fetch-error">Generation failed — {fetchError}</div>
      )}

      {(busy || (step !== "idle" && step !== "complete")) && (
        <ProgressTracker step={step} attempt={attempt} error={error} />
      )}

      {result && (
        <div className="results">
          <VideoPlayer videoUrl={result.videoUrl} jobId={jobId!} />
          <CodeViewer code={result.code} />
        </div>
      )}
    </div>
  );
}
