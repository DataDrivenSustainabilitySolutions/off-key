export const DEVICE_TELEMETRY_PREFIX = "telemetry";


export interface DeviceTelemetryTopic {
  chargerId: string;
  telemetryType: string;
}

const isConcreteHierarchy = (value: string): boolean => {
  const levels = value.split("/");
  return (
    levels.length > 0 &&
    levels.every(
      (level) =>
        level.length > 0 && !level.includes("+") && !level.includes("#"),
    )
  );
};

export const buildDeviceTelemetryTopic = (
  chargerId: string,
  telemetryType: string,
): string => {
  if (!isConcreteHierarchy(chargerId) || chargerId.includes("/")) {
    throw new Error("Entity ID must be one concrete MQTT level.");
  }
  if (!isConcreteHierarchy(telemetryType)) {
    throw new Error("Telemetry type must be a concrete MQTT hierarchy.");
  }
  return `${DEVICE_TELEMETRY_PREFIX}/${chargerId}/${telemetryType}`;
};

export const buildDeviceTelemetryChargerFilter = (chargerId: string): string => {
  if (!isConcreteHierarchy(chargerId) || chargerId.includes("/")) {
    throw new Error("Entity ID must be one concrete MQTT level.");
  }
  return `${DEVICE_TELEMETRY_PREFIX}/${chargerId}/#`;
};

export const parseDeviceTelemetryTopic = (
  topic: string,
): DeviceTelemetryTopic | null => {
  const levels = topic.trim().split("/");
  const offset = 1;
  if (
    levels.length < offset + 2 ||
    levels[0] !== "telemetry"
  ) {
    return null;
  }
  const chargerId = levels[offset] ?? "";
  const telemetryLevels = levels.slice(offset + 1);
  if (
    !isConcreteHierarchy(chargerId) ||
    chargerId.includes("/") ||
    telemetryLevels.some(
      (level) =>
        level.length === 0 || level.includes("+") || level.includes("#"),
    )
  ) {
    return null;
  }
  return { chargerId, telemetryType: telemetryLevels.join("/") };
};
