import type { SystemDocument, SystemStream } from "@/types/system";
import type { ExplorerNode, NavigationIndex } from "@/domain/system/navigationIndex";
import type { Alarm } from "@/types/charger";

/** What a Details page shows: a device's readings, or a broker's readings without a device. */
export type ReadingSource = { kind: "device" | "broker"; id: string };

const sourceOf = (stream: SystemStream): ReadingSource =>
  stream.device_id ? { kind: "device", id: stream.device_id } : { kind: "broker", id: stream.broker_id };

export const detailsHref = (source: ReadingSource) =>
  source.kind === "device"
    ? `/details/${encodeURIComponent(source.id)}`
    : `/details/broker/${encodeURIComponent(source.id)}`;

/** A source's catalogue readings, and how to ask for their alarms and evidence. */
export function sourceReadings(document: SystemDocument | undefined, source: ReadingSource) {
  const readings = (document?.readings ?? []).filter(stream => source.kind === "device"
    ? stream.device_id === source.id
    : stream.broker_id === source.id && !stream.device_id);
  const scope: { deviceId: string } | { readingIds: string[] } = source.kind === "device"
    ? { deviceId: source.id }
    : { readingIds: readings.map(stream => stream.id) };
  return { readings, scope };
}

/** The catalogue name of a source, if the catalogue still has it. */
export function sourceLabel(document: SystemDocument | undefined, source: ReadingSource) {
  const items = source.kind === "device" ? document?.devices : document?.brokers;
  return items?.find(item => item.id === source.id)?.label;
}

/** The catalogue node that stands for a source, so that views can be scoped to it. */
export function sourceNode(index: NavigationIndex, source: ReadingSource): ExplorerNode | undefined {
  const nodes = (index.objectKeys.get(source.id) ?? []).flatMap(key => index.nodes.get(key) ?? []);
  return nodes.find(node => source.kind === "device" ? node.entityKind === "device" : node.kind === "connection");
}

/** Where an alarm's readings come from: its device, or the broker of readings without one. */
export function alarmSource(alarm: Alarm, document: SystemDocument | undefined): ReadingSource | undefined {
  if (alarm.device_id) return { kind: "device", id: alarm.device_id };
  const stream = document?.readings.find(item => alarm.reading_ids.includes(item.id));
  return stream && sourceOf(stream);
}

/** The one source behind a selection of readings, when there is exactly one. */
export function selectedSource(readingIds: readonly string[] | undefined, document: SystemDocument | undefined) {
  const chosen = new Set(readingIds);
  const sources = new Map((document?.readings ?? []).filter(stream => chosen.has(stream.id))
    .map(stream => { const source = sourceOf(stream); return [`${source.kind}:${source.id}`, source] as const; }));
  return sources.size === 1 ? [...sources.values()][0] : undefined;
}
