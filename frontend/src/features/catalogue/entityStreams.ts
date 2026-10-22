import type { SystemDocument, SystemRuntime, SystemStream } from "./systemTypes";

/** Catalogue streams bound to one recorded entity, keyed by telemetry key. */
export const entityStreams = (
  document: SystemDocument | null | undefined,
  runtime: SystemRuntime | null | undefined,
  entityId: string,
): Map<string, SystemStream> =>
  new Map((document?.streams ?? []).flatMap(stream => {
    const binding = runtime?.bindings?.[stream.id];
    return binding?.entity_id === entityId ? [[binding.telemetry_key, stream] as const] : [];
  }));
