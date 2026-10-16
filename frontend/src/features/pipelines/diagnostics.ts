export type NodePass = {
  input: Record<string, number> | null;
  output: Record<string, number> | number | null;
  state: string;
  reason?: string;
};
export type PipelineState = {
  run_id: string;
  revision_id: string;
  fingerprint: string;
  captured_at: string;
  phase: string;
  sequence_number: number;
  nodes: Record<
    string,
    {
      state: string;
      learn_count: number;
      score_count: number;
      learn_time_ns: number;
      score_time_ns: number;
      ready: boolean;
      error?: string;
      learned_updates?: number;
      readiness_observed?: number | null;
      readiness_required?: number | null;
      readiness_reason?: string | null;
      blocked_by?: string[];
    }
  >;
  observation?: {
    sequence_number: number;
    timestamp: string;
    phase: string;
    input_timestamps: Record<string, string>;
    passes: {
      score: Record<string, NodePass>;
      learn: Record<string, NodePass>;
    };
  };
  adaptive_learning?: {
    state: string;
    model_updates: number;
    warmup_updates: number;
    warmup_required: number;
    ready: boolean;
    reason: string | null;
  };
  batch_training?: {
    state: string;
    training_samples: number;
    calibration_samples: number;
    frozen: boolean;
  };
  truncated: boolean;
  diagnostic_errors: number;
};
