import type { SystemConnection } from "@/types/system";

/** A plain-TCP MQTT connection; callers name the fields they assert on. */
export const mqttConnection = (
  fields: Pick<SystemConnection, "id" | "label" | "host"> & Partial<SystemConnection>,
): SystemConnection => ({ protocol: "mqtt", port: 1883, transport: "tcp", tls: false, ...fields });
