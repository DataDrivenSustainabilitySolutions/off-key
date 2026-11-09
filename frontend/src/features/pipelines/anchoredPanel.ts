import { useLayoutEffect, useSyncExternalStore, type RefObject } from "react";

/** Narrower than this, step settings open as a bottom sheet instead of beside the card. */
const SHEET_QUERY = "(max-width: 680px)";
const subscribeSheet = (listener: () => void) => {
  const media = window.matchMedia(SHEET_QUERY);
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
};
const isSheet = () => window.matchMedia(SHEET_QUERY).matches;
/** Whether step settings open as a bottom sheet, which happens on a phone. */
export const useSettingsSheet = () => useSyncExternalStore(subscribeSheet, isSheet, () => false);

/** Room between the card and its settings, and between the settings and the canvas edge. */
const GAP = 12;

export type Box = { left: number; top: number; right: number; bottom: number };

const overlap = (a: Box, b: Box) =>
  Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
  * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));

/** Settings shorter than this are too cramped to use, so that side is not taken. */
const MIN_HEIGHT = 240;

/**
 * Where settings sit beside their card: below it, right of it, left of it or above it.
 * The side that covers nothing else wins, the tallest among those; when every side
 * covers some, the one covering least. Covering the card itself counts several times
 * over, so the settings never hide what they edit while another side has room. Below
 * comes first because a pipeline reads left to right, so its neighbours sit beside it.
 * `size.height` is the settings' height when given the whole area.
 */
export function placeBeside(card: Box, size: { width: number; height: number }, area: Box, others: Box[]) {
  const { width } = size;
  const room = area.bottom - area.top;
  const candidates = [
    { left: card.left, top: card.bottom + GAP, room: area.bottom - card.bottom - GAP },
    { left: card.right + GAP, top: card.top, room },
    { left: card.left - GAP - width, top: card.top, room },
    { left: card.left, bottom: card.top - GAP, room: card.top - GAP - area.top },
  ].filter((candidate, index) => index === 1 || candidate.room >= Math.min(MIN_HEIGHT, size.height))
    .map((candidate) => {
      const height = Math.min(size.height, candidate.room);
      const left = Math.max(area.left, Math.min(candidate.left, area.right - width));
      const wanted = candidate.top ?? candidate.bottom - height;
      const top = Math.max(area.top, Math.min(wanted, area.bottom - height));
      const box = { left, top, right: left + width, bottom: top + height };
      const covered = others.reduce((sum, other) => sum + overlap(box, other), 0) + 4 * overlap(box, card);
      return { left, top, height, covered };
    });
  const better = (a: typeof candidates[number], b: typeof candidates[number]) =>
    a.covered !== b.covered ? a.covered < b.covered : a.height > b.height;
  const best = candidates.reduce((winner, candidate) => (better(candidate, winner) ? candidate : winner));
  return { left: best.left, top: best.top, maxHeight: best.height };
}

/**
 * Keeps step settings beside the selected card as the canvas pans, zooms and the card
 * moves. The panel is placed by writing its style, since placing needs measured sizes.
 * `top` is how far the floating header reaches over the stage.
 */
export function useAnchoredPanel(
  enabled: boolean,
  stage: RefObject<HTMLElement | null>,
  panel: RefObject<HTMLElement | null>,
  selected: string | undefined,
  top: number,
) {
  useLayoutEffect(() => {
    const element = panel.current;
    const root = stage.current;
    if (!enabled || !element || !root || !selected) return;
    let frame = 0;
    const release = () => {
      element.removeAttribute("data-anchored");
      for (const property of ["left", "top", "max-height"]) element.style.removeProperty(property);
    };
    const place = () => {
      frame = 0;
      const nodes = [...root.querySelectorAll<HTMLElement>(".react-flow__node")];
      const card = nodes.find((node) => node.dataset.id === selected);
      if (!card) return release();
      const origin = root.getBoundingClientRect();
      const relative = (node: Element): Box => {
        const box = node.getBoundingClientRect();
        return { left: box.left - origin.left, top: box.top - origin.top, right: box.right - origin.left, bottom: box.bottom - origin.top };
      };
      const area = { left: GAP, top: Math.min(top + GAP, origin.height / 2), right: origin.width - GAP, bottom: origin.height - GAP };
      element.setAttribute("data-anchored", "true");
      element.style.setProperty("max-height", `${Math.max(0, area.bottom - area.top)}px`);
      const { width, height } = element.getBoundingClientRect();
      // Other cards and the zoom controls are what the settings should leave in view.
      const obstacles = [...nodes.filter((node) => node !== card), ...root.querySelectorAll(".react-flow__controls")];
      const spot = placeBeside(relative(card), { width, height }, area, obstacles.map(relative));
      element.style.setProperty("max-height", `${Math.floor(spot.maxHeight)}px`);
      element.style.setProperty("left", `${Math.round(spot.left)}px`);
      element.style.setProperty("top", `${Math.round(spot.top)}px`);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(place); };
    place();
    // Panning, zooming and dragging all rewrite a transform under the viewport.
    const viewport = root.querySelector(".react-flow__viewport");
    const moves = new MutationObserver(schedule);
    if (viewport) moves.observe(viewport, { attributes: true, attributeFilter: ["style"], subtree: true });
    const sizes = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(schedule);
    sizes?.observe(root);
    sizes?.observe(element);
    return () => {
      cancelAnimationFrame(frame);
      moves.disconnect();
      sizes?.disconnect();
      release();
    };
  }, [enabled, stage, panel, selected, top]);
}
