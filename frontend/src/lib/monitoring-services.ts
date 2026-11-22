import type { ActiveService } from "@/types/monitoring";
import type { TelemetryTypeData } from "@/types/charger";

/** A service that runs, reports itself operational and reported recently: its scores keep coming. */
export const isScoring = (service: Pick<ActiveService, "active" | "operational_status">) =>
  service.active && service.operational_status.stage === "operational" && !service.operational_status.is_stale;

/** The first of `services` that watches each recorded series, by the catalogue reading it records. */
export const buildSensorClaims = (
  series: Pick<TelemetryTypeData, "type">[],
  services: ActiveService[],
): Map<string, ActiveService> => {
  const claims = new Map<string, ActiveService>();
  for (const { type } of series) {
    const owner = services.find(service => service.reading_ids.includes(type));
    if (owner) claims.set(type, owner);
  }
  return claims;
};
