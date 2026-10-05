import { readFileSync } from "node:fs";
import type { IClientOptions } from "mqtt";

// Production smoke uses the generated broker CA and authenticated TLS listener.
export const ingressOptions = (): IClientOptions => {
  const certificate = process.env.E2E_MQTT_CA_FILE;
  return certificate
    ? {
        ca: readFileSync(certificate),
        username: process.env.E2E_MQTT_USERNAME,
        password: process.env.E2E_MQTT_PASSWORD,
      }
    : {};
};
