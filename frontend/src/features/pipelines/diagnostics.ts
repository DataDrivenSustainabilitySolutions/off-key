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
  truncated: boolean;
  diagnostic_errors: number;
};
