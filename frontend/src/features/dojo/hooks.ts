import { epochMilliseconds } from "@/lib/timestamps";
import { useEffect, useState } from "react";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetPoint, DatasetSeriesView, RunResult } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { readPages, type ChartPoint } from "./model";

/** At most this many values per series are drawn; the chart says when it stops early. */
export const CHART_POINTS = 50_000;
const ALARM_MARKS = 20_000;

export type LoadedSeries = { points: ChartPoint[]; truncated: boolean };

/** The values of the chosen series, loaded once per series and kept while the dataset is open. */
export function useSeriesPoints(datasetId: string, series: DatasetSeriesView[]) {
  const [loaded, setLoaded] = useState<Record<string, LoadedSeries>>({});
  const [error, setError] = useState("");
  const missing = series.filter(item => !loaded[item.id]).map(item => item.id).join(",");
  useEffect(() => {
    if (!missing) return;
    const controller = new AbortController();
    void Promise.all(missing.split(",").map(async id => {
      const { items, truncated } = await readPages<DatasetPoint, string>(after => dojoApi.points(datasetId, id,
        { after, limit: DOJO_LIMITS.pointsPage }, controller.signal), CHART_POINTS);
      return [id, { points: items.map(item => [epochMilliseconds(item.timestamp), item.value] as ChartPoint), truncated }] as const;
    })).then(entries => {
      if (!controller.signal.aborted) { setLoaded(previous => ({ ...previous, ...Object.fromEntries(entries) })); setError(""); }
    }).catch(reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [datasetId, missing]);
  return { loaded, error, loading: !!missing && !error };
}

export type LoadedAlarms = { times: number[]; truncated: boolean };

/** When each run alarmed, for marking alarms beside the values. */
export function useRunAlarms(runIds: string[]) {
  const [loaded, setLoaded] = useState<Record<string, LoadedAlarms>>({});
  const [error, setError] = useState("");
  const missing = runIds.filter(id => !loaded[id]).join(",");
  useEffect(() => {
    if (!missing) return;
    const controller = new AbortController();
    void Promise.all(missing.split(",").map(async id => {
      const { items, truncated } = await readPages<RunResult, number>(after => dojoApi.results(id,
        { after, alarm: true, limit: DOJO_LIMITS.resultsPage }, controller.signal), ALARM_MARKS);
      return [id, { times: items.map(item => epochMilliseconds(item.timestamp)), truncated }] as const;
    })).then(entries => {
      if (!controller.signal.aborted) { setLoaded(previous => ({ ...previous, ...Object.fromEntries(entries) })); setError(""); }
    }).catch(reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [missing]);
  return { loaded, error, loading: !!missing && !error };
}
