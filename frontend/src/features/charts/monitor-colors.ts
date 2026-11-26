const LIGHT = ["#a86400", "#7c3aed", "#c026a3", "#5d7a0a", "#c8372d"];
const DARK = ["#fbbf24", "#a78bfa", "#f472b6", "#a3e635", "#f87171"];

/** One colour per monitor of a reading, from a palette of five handed out in the order of the monitors' ids. */
export function monitorColors(monitorIds: readonly string[], dark: boolean): Map<string, string> {
  const palette = dark ? DARK : LIGHT;
  return new Map([...new Set(monitorIds)].sort().map((id, index) => [id, palette[index % palette.length]!]));
}
