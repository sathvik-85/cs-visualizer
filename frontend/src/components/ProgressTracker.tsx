import type { StepName } from "../types";

interface Step {
  id: StepName;
  label: string;
}

const STEPS: Step[] = [
  { id: "generating_code", label: "Generating Code" },
  { id: "validating_code", label: "Validating" },
  { id: "rendering", label: "Rendering" },
  { id: "adding_audio", label: "Adding Voiceover" },
  { id: "complete", label: "Done" },
];

function stepIndex(step: StepName): number {
  const idx = STEPS.findIndex((s) => s.id === step);
  return idx === -1 ? -1 : idx;
}

interface Props {
  step: StepName;
  attempt: number;
  error: string | null;
}

export function ProgressTracker({ step, attempt, error }: Props) {
  if (step === "complete") return null;

  // Map layout-engine sub-steps onto the visible "Generating Code" step
  const normalizedStep: StepName =
    step === "generating_scene_graph" || step === "computing_layout"
      ? "generating_code"
      : step;

  const current = normalizedStep === "idle"
    ? -1
    : stepIndex(normalizedStep === "repair" ? "rendering" : normalizedStep === "rate_limited" ? "generating_code" : normalizedStep);

  return (
    <div className="progress-tracker">
      <div className="steps-row">
        {STEPS.map((s, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <div key={s.id} className={`step ${done ? "done" : ""} ${active ? "active" : ""}`}>
              <div className="step-dot">
                {done ? "✓" : active ? <span className="spinner" /> : i + 1}
              </div>
              <div className="step-label">{s.label}</div>
              {i < STEPS.length - 1 && <div className={`step-line ${done ? "done" : ""}`} />}
            </div>
          );
        })}
      </div>

      {step === "rendering" && attempt > 1 && (
        <p className="repair-notice">Self-healing attempt {attempt} of 3…</p>
      )}
      {step === "repair" && (
        <p className="repair-notice">Fixing errors, retrying (attempt {attempt})…</p>
      )}
      {step === "rate_limited" && error && (
        <p className="repair-notice" style={{color: "#4A90D9"}}>{error}</p>
      )}
      {step === "error" && error && (
        <div className="error-box">
          <strong>Generation failed</strong>
          <pre>{error}</pre>
        </div>
      )}
    </div>
  );
}
