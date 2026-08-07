import type { ResolvedTheme } from "@/components/theme-provider";
import type { ChartThemeColors } from "@/lib/telemetry-chart";

const FALLBACK_COLORS: Record<ResolvedTheme, ChartThemeColors> = {
  light: {
    foreground: "hsl(220 24% 12%)",
    mutedForeground: "hsl(218 10% 44%)",
    border: "hsl(216 18% 88%)",
    popover: "hsl(0 0% 100%)",
    popoverForeground: "hsl(222 18% 10%)",
    muted: "hsl(214 22% 95%)",
    primary: "hsl(173 80% 32%)",
  },
  dark: {
    foreground: "hsl(210 12% 94%)",
    mutedForeground: "hsl(220 8% 72%)",
    border: "hsl(220 8% 24%)",
    popover: "hsl(220 7% 15%)",
    popoverForeground: "hsl(210 12% 94%)",
    muted: "hsl(220 8% 19%)",
    primary: "hsl(173 70% 42%)",
  },
};

const TOKEN_NAMES: Record<keyof ChartThemeColors, string> = {
  foreground: "--foreground",
  mutedForeground: "--muted-foreground",
  border: "--border",
  popover: "--popover",
  popoverForeground: "--popover-foreground",
  muted: "--muted",
  primary: "--primary",
};

export const resolveChartThemeColors = (
  resolvedTheme: ResolvedTheme,
  root: Element = document.documentElement,
): ChartThemeColors => {
  const styles = getComputedStyle(root);
  const fallback = FALLBACK_COLORS[resolvedTheme];
  const resolveColor = (key: keyof ChartThemeColors): string => {
    const value = styles.getPropertyValue(TOKEN_NAMES[key]).trim();
    return value ? `hsl(${value})` : fallback[key];
  };
  return {
    foreground: resolveColor("foreground"),
    mutedForeground: resolveColor("mutedForeground"),
    border: resolveColor("border"),
    popover: resolveColor("popover"),
    popoverForeground: resolveColor("popoverForeground"),
    muted: resolveColor("muted"),
    primary: resolveColor("primary"),
  };
};

export const createEChartsTheme = (colors: ChartThemeColors) => ({
  backgroundColor: "transparent",
  textStyle: { color: colors.foreground },
  legend: { textStyle: { color: colors.foreground } },
  timeAxis: {
    axisLine: { lineStyle: { color: colors.border } },
    axisLabel: { color: colors.mutedForeground },
    splitLine: { lineStyle: { color: colors.border } },
  },
  valueAxis: {
    axisLine: { lineStyle: { color: colors.border } },
    axisLabel: { color: colors.mutedForeground },
    splitLine: { lineStyle: { color: colors.border } },
  },
  logAxis: {
    axisLine: { lineStyle: { color: colors.border } },
    axisLabel: { color: colors.mutedForeground },
    splitLine: { lineStyle: { color: colors.border } },
  },
  tooltip: {
    backgroundColor: colors.popover,
    borderColor: colors.border,
    textStyle: { color: colors.popoverForeground },
  },
  dataZoom: {
    borderColor: colors.border,
    backgroundColor: colors.muted,
  },
});
