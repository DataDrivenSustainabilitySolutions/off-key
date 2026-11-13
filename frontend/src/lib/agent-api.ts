import { apiUtils } from "./api-client";

/** What a key may start: nothing, monitors in shadow, which raise no alarm, or live monitors. */
export type AgentStarts = "nothing" | "shadow" | "live";

/** An agent that signs in with a key in place of a password. */
export interface Agent {
  id: number;
  name: string;
  /** The last characters of the key, to tell keys apart. The key itself is shown once. */
  key_hint: string;
  /** What the key may start. Every key designs, tests and proposes. */
  starts: AgentStarts;
  /** The member who created the key. */
  created_by: string | null;
  created_at: string;
}

export const getAgents = () => apiUtils.get<Agent[]>("/v1/agents");
export const createAgent = (name: string, starts: AgentStarts) =>
  apiUtils.post<Agent & { key: string }>("/v1/agents", { name, starts });
export const updateAgent = (agentId: number, starts: AgentStarts) =>
  apiUtils.patch<Agent>(`/v1/agents/${agentId}`, { starts });
export const revokeAgent = (agentId: number) => apiUtils.delete<void>(`/v1/agents/${agentId}`);
