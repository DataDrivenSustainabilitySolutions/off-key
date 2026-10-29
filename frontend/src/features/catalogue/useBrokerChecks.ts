import { useCallback, useState } from "react";
import { systemApi } from "@/domain/system/systemApi";
import type { SystemConnectionCheck } from "@/types/system";

export type BrokerCheck = { pending: boolean; result?: SystemConnectionCheck; error?: string };

/** Checks run a few at a time; each holds a server worker for up to its timeout. */
const PARALLEL_CHECKS = 4;

/** The coarse colour of a check, matching the dot-and-label tones of broker states. */
export function checkTone(check?: BrokerCheck): "positive" | "warning" | "danger" | "neutral" {
  const status = check?.pending ? undefined : check?.result?.status;
  if (!status || status === "blocked") return "neutral";
  return status === "reachable" ? "positive" : status === "timeout" ? "warning" : "danger";
}

export const outcomes: Record<SystemConnectionCheck["status"], string> = {
  reachable: "Reachable",
  auth_rejected: "Login rejected",
  tls_error: "TLS problem",
  unreachable: "Unreachable",
  refused: "Refused",
  timeout: "No response",
  blocked: "Not checkable",
};

/** Why a finished check could not connect, or nothing when it could (or could not be judged). */
export function checkProblem(check?: BrokerCheck) {
  if (!check || check.pending || !["danger", "warning"].includes(checkTone(check)) && !check.error) return undefined;
  const status = check.result?.status;
  return check.result?.message ?? check.error ?? (status ? outcomes[status] : "Check failed");
}

/** Results live only while Sources is open: nothing is stored and no broker is subscribed. */
export function useBrokerChecks() {
  const [checks, setChecks] = useState<Record<string, BrokerCheck>>({});
  const check = useCallback(async (id: string) => {
    setChecks(current => ({ ...current, [id]: { ...current[id], pending: true, error: undefined } }));
    try {
      const result = await systemApi.checkConnection(id);
      setChecks(current => ({ ...current, [id]: { pending: false, result } }));
    } catch (error) {
      setChecks(current => ({ ...current, [id]: { pending: false,
        error: error instanceof Error && error.message ? error.message : "The check could not be run." } }));
    }
  }, []);
  const checkAll = useCallback(async (ids: string[]) => {
    const queue = [...ids];
    const next = async () => { for (let id = queue.shift(); id; id = queue.shift()) await check(id); };
    await Promise.all(Array.from({ length: Math.min(PARALLEL_CHECKS, queue.length) }, next));
  }, [check]);
  const running = Object.values(checks).some(item => item.pending);
  return { checks, check, checkAll, running };
}
