import { useCallback, useEffect, useRef, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { clientLogger } from "@/lib/logger";

/** A catalogue device, a catalogue reading or a monitor, each by its id. */
export type FavouriteKind = "device" | "reading" | "monitor";
export type Favourite = { kind: FavouriteKind; id: string };
/** Favourites earlier versions kept in this browser, where a monitor was a "service". */
export type LegacyFavourite = { kind: "service" | "reading"; id: string };

const ENDPOINT = API_CONFIG.ENDPOINTS.FAVORITES;
const same = (left: Favourite) => (right: Favourite) => left.kind === right.kind && left.id === right.id;
const without = (items: Favourite[], item: Favourite) => items.filter(other => !same(item)(other));
const NONE: Favourite[] = [];

/**
 * The signed-in member's favourites, kept on the server so they follow the
 * account to every browser and agents see the same list. Favourites an earlier
 * version left in this browser are added to the account once, then dropped.
 */
export function useFavourites(account: string | number | null, legacy: LegacyFavourite[] | undefined, dropLegacy: () => void) {
  // Kept with the account they belong to, so another sign-in never shows them.
  type Owned = { account: string | number | null; items: Favourite[] };
  const [owned, setOwned] = useState<Owned>({ account: null, items: [] });
  const [error, setError] = useState("");
  const latest = useRef<Owned>(owned);
  const migration = useRef({ legacy, dropLegacy });
  useEffect(() => { migration.current = { legacy, dropLegacy }; }, [legacy, dropLegacy]);
  const update = useCallback((next: Owned) => { latest.current = next; setOwned(next); }, []);

  useEffect(() => {
    if (account === null) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const saved = await apiUtils.get<Favourite[]>(ENDPOINT, { signal: controller.signal });
        const { legacy, dropLegacy } = migration.current;
        const moved = (legacy ?? []).map(({ kind, id }): Favourite => ({ kind: kind === "service" ? "monitor" : kind, id }))
          .filter(item => !saved.some(same(item)));
        for (const item of moved) await apiUtils.post<Favourite>(ENDPOINT, item);
        if (controller.signal.aborted) return;
        if (legacy) dropLegacy();
        update({ account, items: [...saved.map(({ kind, id }) => ({ kind, id })), ...moved] });
        setError("");
      } catch (failure) {
        if (controller.signal.aborted) return;
        clientLogger.warn({ event: "favourites.load_failed", message: "Favourites could not be loaded", error: failure });
        setError("Favourites could not be loaded. Reload the page to try again.");
      }
    })();
    return () => controller.abort();
  }, [account, update]);

  const toggle = useCallback((kind: FavouriteKind, id: string) => {
    if (account === null) return;
    const item = { kind, id };
    const current = () => latest.current.account === account ? latest.current.items : [];
    const included = current().some(same(item));
    update({ account, items: included ? without(current(), item) : [...current(), item] });
    const request = included
      ? apiUtils.delete(`${ENDPOINT}?${new URLSearchParams(item)}`)
      : apiUtils.post<Favourite>(ENDPOINT, item);
    request.then(() => setError(""), (failure: unknown) => {
      clientLogger.warn({ event: "favourites.save_failed", message: "Favourite could not be saved", error: failure });
      setError("Your favourite could not be saved. Try again.");
      // Undo only this change; others made meanwhile stay.
      update({ account, items: included ? [...without(current(), item), item] : without(current(), item) });
    });
  }, [account, update]);

  return { favourites: owned.account === account ? owned.items : NONE, toggle, error };
}
