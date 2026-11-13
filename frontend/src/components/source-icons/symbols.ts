import { createLucideIcon } from "lucide-react";

// Lucide's 24 px grid, rounded ends/joins and 2 px stroke. Keep only the
// identifying silhouette: these also have to read at 14–16 px in a list.
export const Device = createLucideIcon("Device", [
  ["rect", { x: "4", y: "4", width: "16", height: "16", rx: "2", key: "chip" }],
  ["path", { d: "M8 2v2m8-2v2M8 20v2m8-2v2M2 8h2m-2 8h2M20 8h2m-2 8h2", key: "pins" }],
]);

export const Pump = createLucideIcon("Pump", [
  ["circle", { cx: "12", cy: "12", r: "7", key: "housing" }],
  ["path", { d: "M2 12h3M12 5V2h8", key: "pipes" }],
  ["path", { d: "m10 9 4 3-4 3", key: "impeller" }],
]);

export const Valve = createLucideIcon("Valve", [
  ["path", { d: "M5 9v10l14-10v10ZM2 14h3m14 0h3", key: "body" }],
  ["path", { d: "M12 14V4M8 4h8", key: "handle" }],
]);

export const Motor = createLucideIcon("Motor", [
  ["rect", { x: "4", y: "7", width: "14", height: "10", rx: "2", key: "housing" }],
  ["path", { d: "M8 7V4h6v3M18 12h4M8 17v3h6v-3", key: "fittings" }],
]);

export const Oscillation = createLucideIcon("Oscillation", [
  ["path", { d: "M2 12C5 12 5 4 8 4s5 16 8 16 3-8 6-8", key: "wave" }],
]);
