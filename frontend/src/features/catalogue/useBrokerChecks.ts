import { useCallback, useState } from "react";
import { systemApi } from "@/domain/system/systemApi";
import type { SystemConnectionCheck } from "@/types/system";

export type BrokerCheck = { pending: boolean; result?: SystemConnectionCheck; error?: string };

/** Checks run a few at a time; each holds a server worker for up to its timeout. */
const PARALLEL_CHECKS = 4;

/** Results stay in this page only: nothing is stored and no broker is subscribed. */
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
