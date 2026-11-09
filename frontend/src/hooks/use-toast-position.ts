import { useEffect, useSyncExternalStore } from "react";
import type { ToastPosition } from "react-hot-toast";

/** Where toasts appear unless a mounted page asks for another place. */
const DEFAULT_POSITION: ToastPosition = "top-right";

// The most recently mounted page that asked for a place wins; leaving restores the one before.
const claims: { position: ToastPosition }[] = [];
const listeners = new Set<() => void>();
const current = () => claims[claims.length - 1]?.position ?? DEFAULT_POSITION;
const notify = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

/** The place the app's toasts appear now. */
export const useToastPosition = () => useSyncExternalStore(subscribe, current, () => DEFAULT_POSITION);

/** Move the app's toasts while this component is mounted, for pages whose own controls sit where toasts would. */
export function usePlaceToasts(position: ToastPosition | undefined) {
  useEffect(() => {
    if (!position) return;
    const claim = { position };
    claims.push(claim);
    notify();
    return () => {
      claims.splice(claims.indexOf(claim), 1);
      notify();
    };
  }, [position]);
}
