import { useEffect, useId, useRef } from "react";
import { buildStripPills, lensOptics, locateOnStrip, STRIP, type StripOverlap, type StripPill, type StripRow } from "./anomaly-strip";
import "./anomaly-strip.css";

const SVG = "http://www.w3.org/2000/svg";
function shape(name: string, attributes: Record<string, string | number>, parent: Element) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return parent.appendChild(node);
}

type Props = {
  rows: readonly StripRow[]; domain?: readonly [number, number]; inset: { left: number; right: number };
  /** Pressing a colour names its monitor. Without it the strip only shows. */
  onPick?: (id: string) => void; onAim?: (id: string | undefined) => void;
};

/** When a monitor flagged an anomaly, on one line under the chart's time axis. The pointer is a lens:
 * what lies under it spreads out, and a stretch shared by several monitors resolves into one field each. */
export function AnomalyStrip({ rows, domain, inset, onPick, onAim }: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const input = useRef({ rows, domain, onPick, onAim });
  const redraw = useRef<() => void>(undefined);
  useEffect(() => { input.current = { rows, domain, onPick, onAim }; redraw.current?.(); }, [rows, domain, onPick, onAim]);

  useEffect(() => {
    const node = svg.current;
    if (!node) return;
    const still = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const lens = { at: 0, focus: 0, inside: false, touch: false, strength: 0, speed: 0, frame: 0, last: 0,
      lock: undefined as StripOverlap | undefined, slice: 0, aimed: undefined as string | undefined };
    let pills: StripPill[] = [], width = 0;

    const resolve = () => {
      const found = lens.inside ? locateOnStrip(pills, lens, width, lens.at) : { slice: 0 };
      lens.lock = found.lock; lens.slice = found.slice;
      const aimed = input.current.onPick ? found.row?.id : undefined;
      if (aimed === lens.aimed) return;
      lens.aimed = aimed;
      if (aimed && lens.touch && typeof navigator.vibrate === "function") navigator.vibrate(8);
      node.classList.toggle("an-strip--aim", !!aimed);
      input.current.onAim?.(aimed);
    };
    const paint = () => {
      node.replaceChildren();
      const { fish, bump } = lensOptics(lens, width), strength = Math.max(0, lens.strength), lift = lens.touch ? 20 : 0;
      const tall = (x: number) => STRIP.height + STRIP.grow * bump(x), middle = (x: number) => STRIP.height / 2 - lift * bump(x);
      const defs = shape("defs", {}, node);
      shape("rect", { class: "an-strip__track", x: 0, y: 4, width, height: 4, rx: 2 }, node);
      const near = (pill: StripPill) => Math.max(0, pill.left - lens.focus, lens.focus - pill.right);
      [...pills].sort((one, other) => near(other) - near(one)).forEach((pill, n) => {
        const inset = Math.min(4, (pill.right - pill.left) / 2 - 0.5), from = pill.left + inset, to = pill.right - inset;
        const steps = Math.max(1, Math.ceil((to - from) / 3));
        const xs = Array.from({ length: steps + 1 }, (_, step) => from + (to - from) * step / steps);
        const cap = (x: number) => Math.min(tall(x) / 2, inset * (1 + bump(x)));
        const top = xs.map(x => `${fish(x).toFixed(1)},${(middle(x) - tall(x) / 2).toFixed(1)}`);
        const bottom = xs.map(x => `${fish(x).toFixed(1)},${(middle(x) + tall(x) / 2).toFixed(1)}`).reverse();
        shape("path", { d: `M${top.join("L")}A${cap(to).toFixed(1)},${(tall(to) / 2).toFixed(1)} 0 0 1 ${bottom[0]}L${bottom.join("L")}`
          + `A${cap(from).toFixed(1)},${(tall(from) / 2).toFixed(1)} 0 0 1 ${top[0]}Z` }, shape("clipPath", { id: `${uid}-pill-${n}` }, defs));
        const group = shape("g", { "clip-path": `url(#${uid}-pill-${n})` }, node);
        pill.parts.forEach((part, at) => {
          const a = at ? fish(part.a) : fish(pill.left) - 12, b = at < pill.parts.length - 1 ? fish(part.b) : fish(pill.right) + 12;
          const count = part.members.length;
          if (count === 1) return void shape("rect", { x: a, y: -60, width: b - a, height: 140, fill: part.members[0]!.color }, group);
          // Stripes stand up into fields as the lens spreads the stretch out.
          const start = fish(part.a), spread = (fish(part.b) - start) / (part.b - part.a);
          const upright = part.overlap === lens.lock ? 0 : Math.max(0, Math.min(1, (spread - 1.15) / 1.5));
          const band = STRIP.stripe + ((fish(part.b) - start) / count - STRIP.stripe) * upright, id = `${uid}-stripes-${n}-${at}`;
          const pattern = shape("pattern", { id, x: start, y: -60, width: band * count, height: 140, patternUnits: "userSpaceOnUse",
            patternTransform: `rotate(${(45 * (1 - upright)).toFixed(1)} ${start.toFixed(1)} ${STRIP.height / 2})` }, defs);
          part.members.forEach((member, stripe) => shape("rect", { x: stripe * band, y: 0, width: band + 0.3, height: 140, fill: member.color }, pattern));
          shape("rect", { x: a, y: -60, width: b - a, height: 140, fill: `url(#${id})` }, group);
        });
        // The shared stretch under the pointer: one field per monitor, equal in size, and exactly what can be pressed.
        const lock = lens.lock;
        if (!lock || !pill.parts.some(part => part.overlap === lock)) return;
        const a = fish(lock.a), each = (fish(lock.b) - a) / lock.members.length;
        const fields = shape("g", { opacity: Math.min(1, strength * 1.5) }, group);
        lock.members.forEach((member, field) => shape("rect", { x: a + field * each - (field ? 0 : 0.5), y: -60, width: each + 0.5, height: 140, fill: member.color }, fields));
        if (input.current.onPick) shape("rect", { x: a + lens.slice * each, y: -60, width: each, height: 140, fill: "#fff", opacity: 0.22 }, fields);
      });
    };
    const tick = (now: number) => {
      const elapsed = Math.min(0.032, (now - (lens.last || now)) / 1000), target = lens.inside ? 1 : 0;
      lens.last = now;
      if (still) { lens.strength = target; lens.speed = 0; }
      else { lens.speed += (300 * (target - lens.strength) - 25 * lens.speed) * elapsed; lens.strength += lens.speed * elapsed; }
      resolve();
      const rest = lens.lock ? (lens.lock.a + lens.lock.b) / 2 : lens.at, gap = rest - lens.focus;
      lens.focus = still || Math.abs(gap) < 0.2 ? rest : lens.focus + gap * Math.min(1, elapsed * (lens.lock ? 14 : 40));
      resolve();
      paint();
      if (Math.abs(target - lens.strength) < 0.002 && Math.abs(lens.speed) < 0.02 && lens.focus === rest) {
        lens.strength = target; lens.frame = 0; lens.last = 0;
        return paint();
      }
      lens.frame = requestAnimationFrame(tick);
    };
    const wake = () => { if (!lens.frame) lens.frame = requestAnimationFrame(tick); };
    const rebuild = () => {
      width = node.clientWidth;
      const { rows, domain } = input.current;
      pills = domain ? buildStripPills(rows, domain, width) : [];
      lens.lock = undefined;
      resolve();
      paint();
    };
    redraw.current = rebuild;

    const place = (event: PointerEvent) => {
      lens.at = event.clientX - node.getBoundingClientRect().left;
      if (!lens.inside) lens.focus = lens.at;
      lens.inside = true; lens.touch = event.pointerType === "touch";
      wake();
    };
    const leave = () => { lens.inside = false; resolve(); wake(); };
    const down = (event: PointerEvent) => { place(event); if (lens.touch) node.setPointerCapture(event.pointerId); };
    const out = (event: PointerEvent) => { if (event.pointerType !== "touch") leave(); };
    // Letting go on a colour opens its monitor: a click with the mouse, lifting the finger on a phone.
    const up = (event: PointerEvent) => {
      resolve();
      const picked = lens.aimed;
      if (event.pointerType === "touch" || picked) leave();
      if (picked) input.current.onPick?.(picked);
    };
    const menu = (event: Event) => event.preventDefault();
    node.addEventListener("pointermove", place); node.addEventListener("pointerdown", down); node.addEventListener("pointerleave", out);
    node.addEventListener("pointercancel", leave); node.addEventListener("pointerup", up); node.addEventListener("contextmenu", menu);
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(rebuild);
    observer?.observe(node);
    rebuild();
    return () => {
      cancelAnimationFrame(lens.frame); observer?.disconnect(); redraw.current = undefined;
      node.removeEventListener("pointermove", place); node.removeEventListener("pointerdown", down); node.removeEventListener("pointerleave", out);
      node.removeEventListener("pointercancel", leave); node.removeEventListener("pointerup", up); node.removeEventListener("contextmenu", menu);
    };
  }, [uid]);

  const count = rows.reduce((total, row) => total + row.spans.length, 0);
  const label = count ? `Anomalies: ${rows.filter(row => row.spans.length).map(row => `${row.name} ${row.spans.length}`).join(", ")}` : "No anomalies in this history";
  return <div className="an-strip" style={{ paddingLeft: inset.left, paddingRight: inset.right }}>
    <svg ref={svg} role="img" aria-label={label} height={STRIP.height} />
  </div>;
}
