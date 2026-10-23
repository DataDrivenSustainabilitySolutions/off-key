import { color } from "echarts/core";
import { afterEach, describe, expect, it } from "vitest";
import { resolveChartThemeColors } from "@/features/charts/echarts-theme";

afterEach(() => document.documentElement.removeAttribute("style"));

describe("canvas chart theme colors", () => {
  it("converts the UI's HSL tokens to colors that both canvas drawing and hover transforms can parse", () => {
    document.documentElement.style.setProperty("--primary", "170 37% 36%");
    const colors = resolveChartThemeColors("light");
    expect(colors.primary).toBe("hsl(170, 37%, 36%)");
    expect(color.parse(colors.primary)).toEqual([58, 126, 114, 1]);
    expect(color.lift(colors.primary, -0.1)).toMatch(/^rgba?\(/);
  });

  it("preserves alpha channels and uses the approved palette when tokens are absent", () => {
    document.documentElement.style.setProperty("--muted", "213 14% 16% / 0.5");
    const light = resolveChartThemeColors("light"), dark = resolveChartThemeColors("dark");
    expect(light.primary).toBe("#3A7E72");
    expect(dark.primary).toBe("#89BDAF");
    expect(color.parse(dark.muted)?.[3]).toBe(0.5);
    for (const colors of [light, dark]) {
      for (const value of Object.values(colors)) expect(color.parse(value)).toBeDefined();
    }
  });
});
