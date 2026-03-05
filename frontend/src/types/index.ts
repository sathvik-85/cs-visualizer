export type StepName =
  | "idle"
  | "generating_scene_graph"
  | "computing_layout"
  | "generating_code"
  | "validating_code"
  | "rendering"
  | "repair"
  | "rate_limited"
  | "adding_audio"
  | "complete"
  | "error";

export interface SSEEvent {
  step: StepName;
  attempt?: number;
  error?: string;
  video_url?: string;
  code?: string;
}

export interface JobResult {
  videoUrl: string;
  code: string;
}
