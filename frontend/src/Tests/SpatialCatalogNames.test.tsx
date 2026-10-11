import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiUtils } from "@/lib/api-client";
import { parseSpatialCatalog, serializeSpatialCatalog } from "@/features/spatial/catalog";
import { applyCatalogNames, applyCatalogWorkspaceNames, buildCatalogNameIndex, catalogGroupNameTarget, catalogNameTarget } from "@/features/spatial/catalogNames";
import { fetchSavedSpatialCatalog, useCatalogNames } from "@/features/spatial/useCatalogNames";
import { createDefaultWorkspace } from "@/features/spatial/model";
import type { Catalog, CatalogSnapshot } from "@/types/collection";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiUtils: { ...actual.apiUtils, get: vi.fn(), patch: vi.fn() } };
});

const sourceId = "00000000-0000-4000-8000-000000000001";
const chargerId = "00000000-0000-4000-8000-000000000002";
function catalog(broker = "Original broker", charger = "Original charger", sensor = "Original sensor"): Catalog {
  return {
    schema_version: 1, provider: "ambibox", default_policy: { mode: "off", interval_seconds: 10 },
    sources: [{
      id: sourceId, label: broker, host: "private-broker.example.invalid", port: 1883, verified: true, forward_port: null,
      chargers: [{ id: chargerId, local_id: "0", label: charger, policy: null, sensors: [{ key: "phase/1", label: sensor, category: "electrical", value_type: "number", unit: "W", upstream_topic: "device/evCharger/0/phase/1", policy: null }] }],
    }],
  };
}
const projection = () => parseSpatialCatalog(JSON.stringify(catalog()));
const snapshot = (value = catalog(), revision = 1, canEdit = true): CatalogSnapshot => ({ catalog: value, revision, can_edit: canEdit, collection: {}, ingress: {}, sensor_activity: {}, updated_at: null, updated_by: null });
const chargerTarget = { kind: "charger" as const, source_id: sourceId, charger_id: chargerId };

beforeEach(() => { vi.clearAllMocks(); });

describe("canonical spatial catalog names", () => {
  it("uses stable entity identities for broker, charger, nested sensor keys, and fleet collections", () => {
    const original = projection();
    const updated = applyCatalogNames(original, buildCatalogNameIndex(catalog("DB broker", "DB charger", "DB sensor")));
    expect(updated.topology.nodes.map((node) => node.label)).toEqual(["DB broker", "DB charger", "DB sensor"]);
    expect(updated.topology.nodes.find((node) => node.kind === "sensor")?.metric).toBe("DB sensor");
    expect(updated.groups[0]?.name).toBe("DB charger");
    expect(updated.datasetKey).toBe(original.datasetKey);
    expect(updated.topology.edges).toBe(original.topology.edges);
    expect(updated.topology.nodes.map((node) => node.id)).toEqual(original.topology.nodes.map((node) => node.id));
    expect(updated.topology.nodes[1]?.position).toBe(original.topology.nodes[1]?.position);
    expect(catalogGroupNameTarget(updated, original.groups[0]!.id)).toEqual(chargerTarget);
    expect(catalogNameTarget(updated.topology.nodes[2]!)).toMatchObject({ kind: "sensor", sensor_key: "phase/1" });
    expect(serializeSpatialCatalog(updated)).not.toContain("private-broker.example.invalid");
  });

  it("preserves manual colours, locks, custom collection titles, camera, positions, and grouping", () => {
    const original = projection();
    const updated = applyCatalogNames(original, buildCatalogNameIndex(catalog("DB broker", "DB charger")));
    const workspace = {
      ...createDefaultWorkspace(),
      groups: [{ ...original.groups[0]!, name: "Stale imported name", color: "#ff8844", locked: true, collapsed: false }, { id: "custom-team", name: "Our team", color: "#0088ff", locked: false, collapsed: true }],
      positions: { [original.topology.nodes[1]!.id]: { x: 20, z: 30 } },
      memberships: { [original.topology.nodes[2]!.id]: "custom-team" },
    };
    const result = applyCatalogWorkspaceNames(workspace, updated);
    expect(result.groups[0]).toEqual({ ...workspace.groups[0], name: "DB charger" });
    expect(result.groups[1]).toBe(workspace.groups[1]);
    expect(result.positions).toBe(workspace.positions);
    expect(result.memberships).toBe(workspace.memberships);
    expect(result.camera).toBe(workspace.camera);
    expect(catalogGroupNameTarget(updated, "custom-team")).toBeUndefined();
    expect(catalogNameTarget({ ...original.topology.nodes[1]!, kind: "group", id: "group:custom-team" })).toBeUndefined();
  });
});

describe("DB-backed name persistence", () => {
  it("opens the account's saved catalog as a stripped projection without exporting broker addresses", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot(catalog("DB broker", "DB charger"), 4, false));
    const saved = await fetchSavedSpatialCatalog();
    expect(saved.groups[0]?.name).toBe("DB charger");
    expect(JSON.stringify(saved)).not.toContain("private-broker.example.invalid");
    expect(apiUtils.get).toHaveBeenCalledWith("/v1/sources", { signal: undefined });
  });
  it("stays read-only without login and does not pretend a browser-local edit was saved", async () => {
    const onCanonicalNames = vi.fn();
    const { result } = renderHook(() => useCatalogNames({ projection: projection(), isAuthenticated: false, onCanonicalNames }));
    expect(result.current.status).toBe("sign-in-required");
    await act(async () => { expect(await result.current.rename(chargerTarget, "New name")).toBe(false); });
    expect(apiUtils.get).not.toHaveBeenCalled();
    expect(apiUtils.patch).not.toHaveBeenCalled();
    expect(onCanonicalNames).not.toHaveBeenCalled();
  });

  it("loads canonical titles for viewers but blocks writes when can_edit is false", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot(catalog("DB broker", "DB charger"), 4, false));
    const onCanonicalNames = vi.fn();
    const imported = projection();
    const { result } = renderHook(() => useCatalogNames({ projection: imported, isAuthenticated: true, onCanonicalNames }));
    await waitFor(() => expect(result.current.status).toBe("read-only"));
    expect(onCanonicalNames.mock.calls[0]?.[0].groups[0].name).toBe("DB charger");
    await act(async () => { expect(await result.current.rename(chargerTarget, "New name")).toBe(false); });
    expect(apiUtils.patch).not.toHaveBeenCalled();
  });

  it("updates titles only after the database acknowledges the versioned rename", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
    let acknowledge!: (value: CatalogSnapshot) => void;
    vi.mocked(apiUtils.patch).mockImplementation(() => new Promise((resolve) => { acknowledge = resolve; }));
    const onCanonicalNames = vi.fn();
    const imported = projection();
    const { result } = renderHook(() => useCatalogNames({ projection: imported, isAuthenticated: true, onCanonicalNames }));
    await waitFor(() => expect(result.current.canEdit).toBe(true));
    let pending!: Promise<boolean>;
    act(() => { pending = result.current.rename(chargerTarget, "  Persisted charger  "); });
    expect(onCanonicalNames).toHaveBeenCalledTimes(1);
    expect(result.current.saving).toBe(true);
    expect(result.current.canRename(chargerTarget)).toBe(true);
    await act(async () => { expect(await result.current.rename(chargerTarget, "Concurrent name")).toBe(false); });
    expect(apiUtils.patch).toHaveBeenCalledTimes(1);
    expect(apiUtils.patch).toHaveBeenCalledWith("/v1/sources/labels", { expected_revision: 1, ...chargerTarget, label: "Persisted charger" }, expect.objectContaining({ redirectOnUnauthorized: false }));
    await act(async () => { acknowledge(snapshot(catalog("Original broker", "Persisted charger"), 2)); expect(await pending).toBe(true); });
    expect(onCanonicalNames.mock.calls[1]?.[0].groups[0].name).toBe("Persisted charger");
    expect(result.current.revision).toBe(2);
  });

  it("keeps the old title when a save fails and exposes an actionable error", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
    vi.mocked(apiUtils.patch).mockRejectedValue(new ApiRequestError("Database unavailable", 503));
    const onCanonicalNames = vi.fn();
    const imported = projection();
    const { result } = renderHook(() => useCatalogNames({ projection: imported, isAuthenticated: true, onCanonicalNames }));
    await waitFor(() => expect(result.current.canEdit).toBe(true));
    await act(async () => { expect(await result.current.rename(chargerTarget, "Unsaved name")).toBe(false); });
    expect(onCanonicalNames).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBe("Database unavailable");
    expect(result.current.revision).toBe(1);
  });

  it("does not restore stale edit permission when a delayed save overlaps a viewer refresh", async () => {
    vi.mocked(apiUtils.get).mockResolvedValueOnce(snapshot()).mockResolvedValueOnce(snapshot(catalog(), 1, false));
    let acknowledge!: (value: Omit<CatalogSnapshot, "can_edit">) => void;
    vi.mocked(apiUtils.patch).mockImplementation(() => new Promise((resolve) => { acknowledge = resolve; }));
    const imported = projection();
    const onCanonicalNames = vi.fn();
    const { result } = renderHook(() => useCatalogNames({ projection: imported, isAuthenticated: true, onCanonicalNames }));
    await waitFor(() => expect(result.current.canEdit).toBe(true));
    let pending!: Promise<boolean>;
    act(() => { pending = result.current.rename(chargerTarget, "Committed before role changed"); });
    await act(async () => { await result.current.refresh(); });
    expect(result.current.canEdit).toBe(false);
    const { can_edit: _permission, ...saved } = snapshot(catalog("Original broker", "Committed before role changed"), 2);
    void _permission;
    await act(async () => { acknowledge(saved); expect(await pending).toBe(true); });
    expect(result.current.canEdit).toBe(false);
    expect(result.current.status).toBe("read-only");
    expect(result.current.revision).toBe(2);
  });

  it("refetches canonical names after a revision conflict instead of overwriting another edit", async () => {
    vi.mocked(apiUtils.get).mockResolvedValueOnce(snapshot()).mockResolvedValueOnce(snapshot(catalog("Original broker", "Another editor's name"), 3));
    vi.mocked(apiUtils.patch).mockRejectedValue(new ApiRequestError("Revision conflict", 409));
    const onCanonicalNames = vi.fn();
    const imported = projection();
    const { result } = renderHook(() => useCatalogNames({ projection: imported, isAuthenticated: true, onCanonicalNames }));
    await waitFor(() => expect(result.current.canEdit).toBe(true));
    await act(async () => { expect(await result.current.rename(chargerTarget, "Overwriting name")).toBe(false); });
    expect(apiUtils.patch).toHaveBeenCalledTimes(1);
    expect(onCanonicalNames.mock.calls[1]?.[0].groups[0].name).toBe("Another editor's name");
    expect(result.current.revision).toBe(3);
    expect(result.current.error).toContain("The catalog changed");
  });

  it("ignores a previous account's delayed response after the account context changes", async () => {
    let resolveOld!: (value: CatalogSnapshot) => void;
    vi.mocked(apiUtils.get).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; })).mockResolvedValueOnce(snapshot(catalog("New account broker", "New account charger"), 5, false));
    const onCanonicalNames = vi.fn();
    const imported = projection();
    const { result, rerender } = renderHook(({ accountKey }) => useCatalogNames({ projection: imported, isAuthenticated: true, accountKey, onCanonicalNames }), { initialProps: { accountKey: 1 } });
    rerender({ accountKey: 2 });
    await waitFor(() => expect(result.current.revision).toBe(5));
    await act(async () => { resolveOld(snapshot(catalog("Old account broker", "Old account charger"), 20)); });
    expect(onCanonicalNames).toHaveBeenCalledTimes(1);
    expect(onCanonicalNames.mock.calls[0]?.[0].groups[0].name).toBe("New account charger");
  });

  it("shows an unavailable backend or an unmatched catalog without enabling writes", async () => {
    vi.mocked(apiUtils.get).mockRejectedValueOnce(new ApiRequestError("Network unavailable"));
    const imported = projection();
    const onCanonicalNames = vi.fn();
    const { result } = renderHook(() => useCatalogNames({ projection: imported, isAuthenticated: true, onCanonicalNames }));
    await waitFor(() => expect(result.current.status).toBe("unavailable"));
    expect(result.current.canEdit).toBe(false);
    vi.mocked(apiUtils.get).mockResolvedValueOnce(snapshot({ ...catalog(), sources: [] }));
    await act(async () => { await result.current.refresh(); });
    expect(result.current.status).toBe("unmatched");
    expect(result.current.canRename(chargerTarget)).toBe(false);
  });
});
