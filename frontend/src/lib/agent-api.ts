import { apiUtils } from "./api-client";

/** An agent that signs in with a key in place of a password. */
export interface Agent {
  id: number;
  name: string;
  /** The last characters of the key, to tell keys apart. The key itself is shown once. */
  key_hint: string;
  /** Whether the key may start monitoring services. Every key designs, tests and proposes. */
  may_start: boolean;
  /** The member who created the key. */
  created_by: string | null;
  created_at: string;
}

export const getAgents = () => apiUtils.get<Agent[]>("/v1/agents");
export const createAgent = (name: string, mayStart: boolean) =>
  apiUtils.post<Agent & { key: string }>("/v1/agents", { name, may_start: mayStart });
export const updateAgent = (agentId: number, mayStart: boolean) =>
  apiUtils.patch<Agent>(`/v1/agents/${agentId}`, { may_start: mayStart });
export const revokeAgent = (agentId: number) => apiUtils.delete<void>(`/v1/agents/${agentId}`);
