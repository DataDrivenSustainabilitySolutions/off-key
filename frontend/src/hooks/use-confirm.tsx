import { useCallback, useState } from "react";
import { ConfirmDialog, type ConfirmOptions } from "@/components/ConfirmDialog";

/** Ask before an action: `if (!await confirm({...})) return;`, with the returned element rendered once. */
export function useConfirm() {
  const [request, setRequest] = useState<(ConfirmOptions & { resolve: (value: boolean) => void }) | null>(null);
  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>(resolve => setRequest({ ...options, resolve })), []);
  const settle = (value: boolean) => { request?.resolve(value); setRequest(null); };
  const element = request && <ConfirmDialog open {...request} onConfirm={() => settle(true)} onCancel={() => settle(false)} />;
  return [confirm, element] as const;
}
