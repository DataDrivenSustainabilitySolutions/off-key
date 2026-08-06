import type { ActiveService } from "@/types/monitoring";

export const mqttFiltersOverlap = (left: string, right: string): boolean => {
  const leftParts = left.trim().split("/");
  const rightParts = right.trim().split("/");
  let index = 0;
  while (index < leftParts.length && index < rightParts.length) {
    if (leftParts[index] === "#" || rightParts[index] === "#") return true;
    if (
      leftParts[index] !== "+" &&
      rightParts[index] !== "+" &&
      leftParts[index] !== rightParts[index]
    ) {
      return false;
    }
    index += 1;
  }
  if (index === leftParts.length && index === rightParts.length) return true;
  if (index < leftParts.length) {
    return index === leftParts.length - 1 && leftParts[index] === "#";
  }
  return index === rightParts.length - 1 && rightParts[index] === "#";
};

export const buildSensorClaims = (
  chargerId: string,
  sensorTypes: string[],
  services: ActiveService[],
): Map<string, ActiveService> => {
  const claims = new Map<string, ActiveService>();
  for (const sensor of sensorTypes) {
    const concreteTopic = `charger/${chargerId}/live-telemetry/${sensor}`;
    const owner = services.find((service) =>
      (service.mqtt_topics ?? []).some((topic) =>
        mqttFiltersOverlap(topic, concreteTopic),
      ),
    );
    if (owner) claims.set(sensor, owner);
  }
  return claims;
};
