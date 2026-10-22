import { useMemo } from "react";
import { useTheme } from "@/components/theme-provider";
import { resolveChartThemeColors } from "@/lib/echarts-theme";

/** The resolved theme and its chart palette, recomputed only when the theme changes. */
export function useChartColors() {
  const { resolvedTheme } = useTheme();
  const colors = useMemo(() => resolveChartThemeColors(resolvedTheme), [resolvedTheme]);
  return { resolvedTheme, colors };
}
