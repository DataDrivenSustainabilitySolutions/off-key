import { createHash } from "node:crypto";
import { expect, type APIRequestContext } from "@playwright/test";
import type { CollectionPolicy } from "../../src/types/collection";
import type { SystemSnapshot } from "../../src/features/catalogue/systemTypes";

const stableKey = (kind: string, identity: string) => `${kind}-${createHash("sha256").update(identity).digest("hex")}`;
export const fixtureEntityId = (deviceId: string) => stableKey("entity", deviceId);
export const fixtureReadingKey = (deviceId: string, key: string) => stableKey("reading", `${deviceId}:${key.replaceAll("/", ":")}`);

/** Create domain-neutral fixtures through the same public opt-in workflow as users. */
export const addTestCharger = async (
  api: APIRequestContext, token: string, deviceId: string, localId: string,
  keys: readonly string[], policy: CollectionPolicy = { mode: "original", interval_seconds: 10 },
): Promise<Record<string, string>> => {
  const headers = { Authorization: `Bearer ${token}` };
  const response = await api.get("/api/v1/system", { headers });
  expect(response.ok(), await response.text()).toBeTruthy();
  const snapshot = await response.json() as SystemSnapshot;
  const document = snapshot.document;
  let connection = document.connections.find(item => item.host === "source-broker");
  if (!connection) {
    connection = { id: "test-broker", label: "Test broker", protocol: "mqtt", host: "source-broker", port: 1883, tls: false, transport: "tcp" };
    document.connections.push(connection);
  }
  document.devices.push({ id: deviceId, label: `Entity ${deviceId}`, connection_id: connection.id, kind: "device" });
  const streamIds = keys.map(key => `${deviceId}:${key.replaceAll("/", ":")}`);
  document.streams.push(...keys.map((key, index) => ({
    id: streamIds[index]!, label: key, category: "Test", value_type: "number" as const,
    connection_id: connection!.id, device_id: deviceId, topic: `tests/${localId}/${key}`,
  })));
  const saved = await api.put("/api/v1/system", { headers, data: { expected_revision: snapshot.revision, document } });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  let current = await saved.json() as SystemSnapshot;
  expect(streamIds.every(id => current.runtime.bindings?.[id]?.policy.mode === "off")).toBe(true);
  if (policy.mode !== "off") {
    const applied = await api.put("/api/v1/system/collection", { headers, data: {
      expected_revision: current.revision, expected_collection_revision: current.runtime.collection_revision,
      stream_ids: streamIds, policy,
    } });
    expect(applied.ok(), await applied.text()).toBeTruthy();
    current = await applied.json() as SystemSnapshot;
  }
  await expect.poll(async () => {
    const result = await api.get("/api/v1/system", { headers });
    const latest = await result.json() as SystemSnapshot;
    return latest.runtime.collection?.revision === current.runtime.collection_revision
      && latest.runtime.collection?.status === "applied"
      && (policy.mode === "off" || latest.runtime.ingress?.sources?.[connection!.id]?.state === "connected");
  }, { timeout: 120_000, intervals: [1000] }).toBe(true);
  const status = await api.get("/api/v1/system/health", { headers });
  expect(status.ok(), await status.text()).toBeTruthy();
  // Envelope tests need the current generation; upstream tests publish through real brokers.
  const value = current;
  const health = await status.json() as { ingress: { generation?: string } };
  if (policy.mode === "off") return {};
  const generation = health.ingress.generation;
  expect(generation).toBeTruthy();
  return Object.fromEntries(keys.map((key, index) => [key, `ingress/system/${generation}/${value.runtime.bindings![streamIds[index]!]!.telemetry_key}`]));
};

export const removeTestCharger = async (api: APIRequestContext, token: string, identifier: string): Promise<void> => {
  const headers = { Authorization: `Bearer ${token}` };
  const response = await api.get("/api/v1/system", { headers });
  expect(response.ok(), await response.text()).toBeTruthy();
  const system = await response.json() as SystemSnapshot;
  const removedReadings = new Set(system.document.streams.filter(stream => stream.device_id === identifier
    || system.runtime.bindings?.[stream.id]?.entity_id === identifier).map(stream => stream.id));
  const removedDevices = new Set(system.document.streams.filter(stream => removedReadings.has(stream.id)).flatMap(stream => stream.device_id ?? []));
  system.document.streams = system.document.streams.filter(stream => !removedReadings.has(stream.id));
  system.document.devices = system.document.devices.filter(device => !removedDevices.has(device.id));
  const removedConnections = new Set(system.document.connections.filter(connection => !system.document.streams.some(stream => stream.connection_id === connection.id)
    && !system.document.devices.some(device => device.connection_id === connection.id)).map(connection => connection.id));
  system.document.connections = system.document.connections.filter(connection => !removedConnections.has(connection.id));
  const removedIds = new Set([...removedReadings, ...removedDevices, ...removedConnections]);
  system.document.groups = system.document.groups.map(group => ({ ...group, member_ids: group.member_ids.filter(id => !removedIds.has(id)) })).filter(group => group.member_ids.length);
  const saved = await api.put("/api/v1/system", { headers, data: { expected_revision: system.revision, document: system.document, pause_affected_monitors: true } });
  expect(saved.ok(), await saved.text()).toBeTruthy();
};
