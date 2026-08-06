import { useCallback, useMemo, useRef, useState } from "react";

import {
  areChartNavigationStatesEqual,
  DEFAULT_CHART_NAVIGATION,
  type ChartNavigationState,
} from "@/lib/telemetry-chart";
import type { TelemetryTypeData } from "@/types/charger";
import type { MonitoringChartEvidence } from "@/types/monitoring";

const CHART_LINK_PREFERENCE_KEY = "off-key:details:chart-navigation";

const readChartLinkPreference = (): boolean => {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(CHART_LINK_PREFERENCE_KEY) === "linked";
  } catch {
    return false;
  }
};

const writeChartLinkPreference = (linked: boolean): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      CHART_LINK_PREFERENCE_KEY,
      linked ? "linked" : "independent",
    );
  } catch {
    // Storage can be unavailable in privacy-restricted browsing contexts.
  }
};

const getTimelineExtent = (
  telemetryData: TelemetryTypeData[],
  evidence: MonitoringChartEvidence[],
): readonly [number, number] | undefined => {
  let startMs = Number.POSITIVE_INFINITY;
  let endMs = Number.NEGATIVE_INFINITY;
  const telemetryTimesByType = new Map<string, Set<number>>();
  const includeTime = (time: number) => {
    if (!Number.isFinite(time)) return;
    startMs = Math.min(startMs, time);
    endMs = Math.max(endMs, time);
  };
  telemetryData.forEach((series) => {
    const times = telemetryTimesByType.get(series.type) ?? new Set<number>();
    series.data.forEach((point) => {
      const time = Date.parse(point.timestamp);
      if (!Number.isFinite(time)) return;
      times.add(time);
      includeTime(time);
    });
    telemetryTimesByType.set(series.type, times);
  });
  evidence.forEach((item) => {
    Object.entries(item.input_timestamps).forEach(([sensor, timestamp]) => {
      const time = Date.parse(timestamp);
      if (telemetryTimesByType.get(sensor)?.has(time)) includeTime(time);
    });
  });

  return Number.isFinite(startMs) && Number.isFinite(endMs)
    ? [startMs, endMs]
    : undefined;
};

const applyTimeRangeToExtent = (
  extent: readonly [number, number] | undefined,
  navigation: ChartNavigationState,
): readonly [number, number] | undefined => {
  const startMs = navigation.range.fromMs ?? extent?.[0];
  const endMs = navigation.range.toMs ?? extent?.[1];
  if (startMs === undefined || endMs === undefined || endMs < startMs) {
    return undefined;
  }
  return startMs === endMs
    ? [startMs - 30_000, endMs + 30_000]
    : [startMs, endMs];
};

interface LinkedChartNavigation {
  chartsLinked: boolean;
  linkedTimelineExtent?: readonly [startMs: number, endMs: number];
  getNavigationState: (telemetryType: string) => ChartNavigationState;
  handleNavigationStateChange: (
    telemetryType: string,
    nextState: ChartNavigationState,
  ) => void;
  toggleChartLink: () => void;
}

export const useLinkedChartNavigation = (
  telemetryData: TelemetryTypeData[],
  evidence: MonitoringChartEvidence[],
): LinkedChartNavigation => {
  const [chartsLinked, setChartsLinked] = useState(readChartLinkPreference);
  const [linkedNavigationState, setLinkedNavigationState] =
    useState<ChartNavigationState>(DEFAULT_CHART_NAVIGATION);
  const [navigationByTelemetry, setNavigationByTelemetry] = useState<
    Record<string, ChartNavigationState>
  >({});
  const latestNavigationState = useRef<ChartNavigationState>(
    DEFAULT_CHART_NAVIGATION,
  );

  const fullTimelineExtent = useMemo(
    () => getTimelineExtent(telemetryData, evidence),
    [evidence, telemetryData],
  );
  const linkedTimelineExtent = useMemo(
    () => applyTimeRangeToExtent(fullTimelineExtent, linkedNavigationState),
    [fullTimelineExtent, linkedNavigationState],
  );
  const handleNavigationStateChange = useCallback(
    (telemetryType: string, nextState: ChartNavigationState) => {
      latestNavigationState.current = nextState;
      if (chartsLinked) {
        setLinkedNavigationState((current) =>
          areChartNavigationStatesEqual(current, nextState) ? current : nextState,
        );
        return;
      }
      setNavigationByTelemetry((current) => {
        const currentState = current[telemetryType] ?? DEFAULT_CHART_NAVIGATION;
        return areChartNavigationStatesEqual(currentState, nextState)
          ? current
          : { ...current, [telemetryType]: nextState };
      });
    },
    [chartsLinked],
  );
  const getNavigationState = useCallback(
    (telemetryType: string): ChartNavigationState =>
      chartsLinked
        ? linkedNavigationState
        : navigationByTelemetry[telemetryType] ?? DEFAULT_CHART_NAVIGATION,
    [chartsLinked, linkedNavigationState, navigationByTelemetry],
  );
  const toggleChartLink = useCallback(() => {
    const nextLinked = !chartsLinked;
    const adoptedState = nextLinked
      ? latestNavigationState.current
      : linkedNavigationState;
    if (nextLinked) setLinkedNavigationState(adoptedState);
    setNavigationByTelemetry((current) => {
      const next = { ...current };
      telemetryData.forEach(({ type }) => {
        next[type] = adoptedState;
      });
      return next;
    });
    setChartsLinked(nextLinked);
    writeChartLinkPreference(nextLinked);
  }, [chartsLinked, linkedNavigationState, telemetryData]);

  return {
    chartsLinked,
    linkedTimelineExtent,
    getNavigationState,
    handleNavigationStateChange,
    toggleChartLink,
  };
};
