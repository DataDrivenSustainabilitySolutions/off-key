import type { ActiveService } from "@/types/monitoring";
import type { TelemetryTypeData } from "@/types/charger";

/** The first of `services` that watches each recorded series, by the catalogue reading it records. */
export const buildSensorClaims = (
  series: Pick<TelemetryTypeData, "type" | "streamId">[],
  services: ActiveService[],
): Map<string, ActiveService> => {
  const claims = new Map<string, ActiveService>();
  for (const { type, streamId } of series) {
    const owner = streamId === undefined ? undefined : services.find(service => service.stream_ids.includes(streamId));
    if (owner) claims.set(type, owner);
  }
  return claims;
};
