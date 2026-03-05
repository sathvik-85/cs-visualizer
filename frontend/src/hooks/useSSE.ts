import { useEffect, useRef, useState } from "react";
import type { SSEEvent, StepName, JobResult } from "../types";

interface SSEState {
  step: StepName;
  attempt: number;
  error: string | null;
  result: JobResult | null;
}

export function useSSE(jobId: string | null) {
  const [state, setState] = useState<SSEState>({
    step: "idle",
    attempt: 1,
    error: null,
    result: null,
  });
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!jobId) {
      setState({ step: "idle", attempt: 1, error: null, result: null });
      return;
    }

    setState({ step: "idle", attempt: 1, error: null, result: null });
    // In dev, bypass the Vite proxy and connect directly to the backend so
    // SSE frames are not buffered by the proxy's HTTP client layer.
    const base = import.meta.env.DEV ? "http://localhost:8000" : "";
    const es = new EventSource(`${base}/api/stream/${jobId}`);
    esRef.current = es;

    es.onmessage = (e: MessageEvent) => {
      try {
        const event: SSEEvent = JSON.parse(e.data);
        setState((prev) => ({
          ...prev,
          step: event.step,
          attempt: event.attempt ?? prev.attempt,
          error: event.error ?? null,
          result:
            event.step === "complete" && event.video_url && event.code
              ? { videoUrl: event.video_url, code: event.code }
              : prev.result,
        }));

        if (event.step === "complete" || event.step === "error") {
          es.close();
        }
      } catch {
        // ignore malformed events (heartbeat comments don't reach here)
      }
    };

    es.onerror = () => {
      setState((prev) => ({
        ...prev,
        step: "error",
        error: "Connection lost. Please try again.",
      }));
      es.close();
    };

    return () => {
      es.close();
    };
  }, [jobId]);

  return state;
}
