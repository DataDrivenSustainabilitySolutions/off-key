import type { ResolvedTheme } from "@/components/theme-provider";
import type { ChartThemeColors } from "@/lib/telemetry-chart";

const FALLBACK_COLORS: Record<ResolvedTheme, ChartThemeColors> = {
  light: {
    foreground: "#26303B",
    mutedForeground: "hsl(210, 10%, 45%)",
    border: "hsl(210, 15%, 88%)",
    popover: "#FFFFFF",
    popoverForeground: "#26303B",
    muted: "hsl(210, 15%, 97%)",
    primary: "#3A7E72",
  },
  dark: {
    foreground: "#E0E6EB",
    mutedForeground: "hsl(210, 10%, 62%)",
    border: "hsl(213, 12%, 25%)",
    popover: "hsl(213, 16%, 13%)",
    popoverForeground: "#E0E6EB",
    muted: "hsl(213, 14%, 16%)",
    primary: "#89BDAF",
  },
};

const TOKEN_NAMES = {
  foreground: "--foreground",
  mutedForeground: "--muted-foreground",
  border: "--border",
  popover: "--popover",
  popoverForeground: "--popover-foreground",
  muted: "--muted",
  primary: "--primary",
} as const;

export const resolveChartThemeColors = (
  resolvedTheme: ResolvedTheme,
  root: Element = document.documentElement,
): ChartThemeColors => {
  const styles = getComputedStyle(root);
  const fallback = FALLBACK_COLORS[resolvedTheme];
  const resolveColor = (key: keyof typeof TOKEN_NAMES): string => {
    const value = styles.getPropertyValue(TOKEN_NAMES[key]).trim();
    if (!value) return fallback[key];
    // The canvas accepts modern CSS colors, but ZRender's hover/gradient color
    // parser requires comma-separated channels. Use that syntax everywhere.
    if (value.includes(",")) return `hsl(${value})`;
    const [channels = "", alpha] = value.split("/");
    const components = channels.trim().split(/\s+/).join(", ");
    return alpha === undefined
      ? `hsl(${components})`
      : `hsla(${components}, ${alpha.trim()})`;
  };
  return {
    foreground: resolveColor("foreground"),
    mutedForeground: resolveColor("mutedForeground"),
    border: resolveColor("border"),
    popover: resolveColor("popover"),
    popoverForeground: resolveColor("popoverForeground"),
    muted: resolveColor("muted"),
    primary: resolveColor("primary"),
    alarmBoundary: resolvedTheme === "dark" ? "#f87171" : "#b91c1c",
    alarmFill: resolvedTheme === "dark"
      ? "rgba(248, 113, 113, 0.14)"
      : "rgba(185, 28, 28, 0.10)",
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
