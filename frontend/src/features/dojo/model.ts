import type { InputSlot } from "@/types/pipelines.generated";
import type { DatasetSeriesView, LabelSuggestion, RunPromotion, RunSummary } from "@/types/dojo.generated";
import { templateHref } from "@/domain/monitoring/monitoringView";
import { featureName } from "../pipelines/slots";

export type ChartPoint = [number, number];

type Page<T, C> = { items: T[]; next_after?: C | null };

/** Read pages until the end or until ``limit`` items; ``truncated`` says which. */
export async function readPages<T, C>(fetch: (after: C | undefined) => Promise<Page<T, C>>, limit: number) {
  const items: T[] = [];
  let after: C | undefined;
  for (;;) {
    const page = await fetch(after);
    items.push(...page.items);
    if (page.next_after == null) return { items, truncated: false };
    if (items.length >= limit) return { items: items.slice(0, limit), truncated: true };
    after = page.next_after;
  }
}

/** Each input slot of a design, matched to a series of the dataset.
 *
 * A series named like the slot wins, then one with the slot's unit, then the
 * next series not used yet, so a design built on the same readings binds as is.
 */
export function suggestBindings(slots: InputSlot[], series: DatasetSeriesView[]): Record<string, string> {
  const used = new Set<string>();
  const bindings: Record<string, string> = {};
  const take = (slot: InputSlot, match: (item: DatasetSeriesView) => boolean) => {
    const found = series.find(item => !used.has(item.id) && match(item));
    if (!found) return false;
    used.add(found.id);
    bindings[slot.id] = found.id;
    return true;
  };
  const name = (value: string) => value.trim().toLocaleLowerCase();
  const pending = slots.filter(slot => !take(slot, item =>
    featureName(item.name) === slot.id || name(item.name) === name(slot.label)));
  const remaining = pending.filter(slot => !(slot.unit && take(slot, item => item.unit === slot.unit)));
  for (const slot of remaining) take(slot, () => true);
  return bindings;
}

export type Tone = "positive" | "warning" | "danger" | "neutral";

export function runState(run: Pick<RunSummary, "status" | "points_read" | "points_total">): { label: string; tone: Tone } {
  switch (run.status) {
    case "queued": return { label: "Waiting", tone: "neutral" };
    case "running": {
      const share = run.points_total ? Math.floor((run.points_read / run.points_total) * 100) : 0;
      return { label: `Running ${share}%`, tone: "warning" };
    }
    case "succeeded": return { label: "Finished", tone: "positive" };
    case "failed": return { label: "Failed", tone: "danger" };
    case "cancelled": return { label: "Cancelled", tone: "neutral" };
  }
}

export const isActive = (run: Pick<RunSummary, "status">) => run.status === "queued" || run.status === "running";

export const strategyLabel = (strategy: string) =>
  strategy === "static_baseline" ? "Static baseline" : strategy === "adaptive_stream" ? "Adaptive stream" : strategy;

/** A duration in the largest unit that keeps it readable: 45 s, 12 min, 3.5 h, 2.1 d. */
export function formatDuration(seconds: number | null | undefined) {
  if (seconds == null) return "–";
  const round = (value: number) => (value >= 10 ? Math.round(value) : Math.round(value * 10) / 10).toLocaleString();
  if (seconds < 60) return `${round(seconds)} s`;
  if (seconds < 3600) return `${round(seconds / 60)} min`;
  if (seconds < 86_400) return `${round(seconds / 3600)} h`;
  return `${round(seconds / 86_400)} d`;
}

export const formatRate = (value: number | null | undefined) =>
  value == null ? "–" : `${Math.round(value * 100)} %`;

export const formatPerDay = (value: number | null | undefined) =>
  value == null ? "–" : (value >= 10 ? Math.round(value) : Math.round(value * 100) / 100).toLocaleString();

const pad = (value: number) => String(value).padStart(2, "0");

/** An instant as the value of a datetime-local input, in the browser's zone. */
export function toLocalInput(value: string | number | Date) {
  const date = new Date(value);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${
    pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/** A datetime-local value back to an ISO instant; undefined when it is not one. */
export function fromLocalInput(value: string) {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

export function formatInstant(value: string | number | null | undefined, locale?: string) {
  if (value == null) return "–";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function formatSpan(start: string | null | undefined, end: string | null | undefined) {
  if (!start || !end) return "–";
  return `${formatInstant(start)} – ${formatInstant(end)}`;
}

export const runName = (run: Pick<RunSummary, "name" | "created_at">) => run.name || `Run of ${formatInstant(run.created_at)}`;

export const DATASET_TABS = [
  { id: "values", label: "Values and labels" },
  { id: "runs", label: "Runs" },
  { id: "compare", label: "Compare" },
] as const;
export type DatasetTab = typeof DATASET_TABS[number]["id"];
export const datasetTab = (value: string | null): DatasetTab =>
  DATASET_TABS.find(item => item.id === value)?.id ?? "values";

/** Monitoring opens the new template with each slot's recorded reading suggested. */
export const monitoringHandOff = (promotion: RunPromotion) => templateHref(promotion.pipeline_id,
  Object.fromEntries(promotion.bindings.flatMap(item => item.reading_id ? [[item.slot_id, item.reading_id]] : [])));

/** The note a suggested label gets when it is added as it is. */
export function suggestionNote(item: Pick<LabelSuggestion, "alarm_count">) {
  return item.alarm_count === 1 ? "Recorded alarm" : `${item.alarm_count.toLocaleString()} recorded alarms`;
}
