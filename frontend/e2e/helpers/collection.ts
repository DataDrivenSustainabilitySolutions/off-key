import { randomUUID } from "node:crypto";
import { expect, type APIRequestContext } from "@playwright/test";

import type { Catalog, CatalogSnapshot } from "../../src/types/collection";

// The development broker uses the same scalar topic contract as AmbiBox.
export const addTestCharger = async (
  api: APIRequestContext,
  token: string,
  chargerId: string,
  localId: string,
  keys: readonly string[],
): Promise<Record<string, string>> => {
  const headers = { Authorization: `Bearer ${token}` };
  const response = await api.get("/api/v1/sources", { headers });
  expect(response.ok(), await response.text()).toBeTruthy();
  const snapshot = (await response.json()) as CatalogSnapshot;
  const catalog: Catalog = snapshot.catalog;
  let source = catalog.sources.find((item) => item.host === "source-broker");
  if (!source) {
    source = {
      id: randomUUID(),
      label: "Development broker",
      host: "source-broker",
      port: 1883,
      verified: true,
      forward_port: null,
      chargers: [],
    };
    catalog.sources.push(source);
  }
  source.chargers = source.chargers.filter(
    (charger) => charger.id !== chargerId,
  );
  source.chargers.push({
    id: chargerId,
    local_id: localId,
    label: `Charger ${chargerId}`,
    policy: { mode: "original", interval_seconds: 10 },
    sensors: keys.map((key) => ({
      key,
      label: key,
      category: "Test",
      value_type: "number",
      unit: null,
      upstream_topic: `device/evCharger/${localId}/${key}`,
      policy: null,
    })),
  });
  const saved = await api.put("/api/v1/sources", {
    headers,
    data: { expected_revision: snapshot.revision, catalog },
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  const revision = ((await saved.json()) as CatalogSnapshot).revision;
  await expect
    .poll(
      async () => {
        const status = await api.get("/api/v1/sources/status", { headers });
        const current = (await status.json()) as CatalogSnapshot;
        return (
          current.collection.revision === revision &&
          current.collection.status === "applied" &&
          current.ingress.sources?.[source.id]?.status === "connected"
        );
      },
      { timeout: 120_000, intervals: [1_000] },
    )
    .toBe(true);
  return Object.fromEntries(
    keys.map((key) => [
      key,
      `ingress/ambibox/${source.id}/device/evCharger/${localId}/${key}`,
    ]),
  );
};

export const removeTestCharger = async (
  api: APIRequestContext,
  token: string,
  chargerId: string,
): Promise<void> => {
  const headers = { Authorization: `Bearer ${token}` };
  const response = await api.get("/api/v1/sources", { headers });
  expect(response.ok(), await response.text()).toBeTruthy();
  const snapshot = (await response.json()) as CatalogSnapshot;
  const source = snapshot.catalog.sources.find((item) =>
    item.chargers.some((charger) => charger.id === chargerId),
  );
  if (!source) return;
  source.chargers = source.chargers.filter(
    (charger) => charger.id !== chargerId,
  );
  snapshot.catalog.sources = snapshot.catalog.sources.filter(
    (item) => item.id !== source.id || source.chargers.length > 0,
  );
  const saved = await api.put("/api/v1/sources", {
    headers,
    data: {
      expected_revision: snapshot.revision,
      catalog: snapshot.catalog,
      pause_affected_monitors: true,
    },
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();
};
