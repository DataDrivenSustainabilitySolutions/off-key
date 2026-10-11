import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient, apiUtils } from "@/lib/api-client";
import { ConfiguredSystemWorkspace } from "@/features/spatial/ConfiguredSystemWorkspace";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import { projectSystemDocument } from "@/features/spatial/systemProjection";
import type { SpatialCanvasProps } from "@/features/spatial/SpatialScene";
import type {
  SystemDocument,
  SystemSnapshot,
} from "@/features/spatial/systemTypes";
import type { SpatialGroup, SpatialNode } from "@/features/spatial/types";

const canvas = vi.hoisted(() => ({ props: null as SpatialCanvasProps | null }));

vi.mock("@/auth/AuthContext", () => ({
  useAuth: () => ({ userId: 1, isAuthenticated: true }),
}));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    apiUtils: { ...actual.apiUtils, get: vi.fn() },
    apiClient: { ...actual.apiClient, put: vi.fn() },
  };
});
vi.mock("@/features/spatial/SpatialCanvas", () => ({
  SpatialCanvas: (props: SpatialCanvasProps) => {
    canvas.props = props;
    return (
      <div>
        <output data-testid="scene-state">
          {JSON.stringify({ nodes: props.nodes, groups: props.groups })}
        </output>
        <button
          onClick={() => {
            const station = props.nodes.find((node) => node.id === "station")!;
            props.onMove({
              station: {
                x: station.position.x + 9,
                z: station.position.z + 12,
              },
            });
          }}
        >
          Attempt object move
        </button>
        <button
          onClick={() =>
            props.onCameraChange({
              ...props.camera,
              zoom: props.camera.zoom + 0.1,
            })
          }
        >
          Move camera
        </button>
      </div>
    );
  },
}));

const fixture = (): SystemDocument => ({
  ...createEmptySystem(),
  connections: [
    {
      id: "broker",
      label: "Broker",
      protocol: "mqtt",
      host: "broker.example.test",
      port: 1883,
      transport: "tcp",
      tls: false,
    },
  ],
  devices: [
    {
      id: "station",
      label: "Station",
      kind: "station",
      connection_id: "broker",
    },
  ],
  streams: [
    {
      id: "temperature",
      label: "Temperature",
      connection_id: "broker",
      device_id: "station",
      topic: "weather/temperature",
      value_type: "number",
      category: "Other",
    },
  ],
  groups: [
    { id: "alpha", label: "Alpha", member_ids: ["station", "temperature"] },
    { id: "beta", label: "Beta", member_ids: [] },
  ],
});
const snapshot = (document = fixture(), revision = 7): SystemSnapshot => ({
  document,
  revision,
  can_edit: true,
  storage_origin: "saved",
  runtime: {
    mode: "configured_only",
    legacy_collection_revision: 0,
    message: "Saved configuration",
  },
});
const scene = (): { nodes: SpatialNode[]; groups: SpatialGroup[] } =>
  JSON.parse(screen.getByTestId("scene-state").textContent!);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("automatic configured workspace", () => {
  it("offers no placement controls and ignores stale object movement callbacks", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
    render(
      <MemoryRouter>
        <ConfiguredSystemWorkspace onPreview={vi.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(scene().nodes).toHaveLength(2));
    const before = canvas.props!;
    expect(before.editMode).toBe(false);
    expect(before.onGroupMove).toBeUndefined();
    const noPlacementControls = () => {
      expect(
        screen.queryByRole("button", {
          name: /^(Automatic layout|Inspect|Arrange|Tidy positions|Undo layout change|Pin|Unpin|Lock group|Unlock group)$/,
        }),
      ).toBeNull();
    };
    noPlacementControls();
    fireEvent.click(
      screen.getByRole("button", { name: "Attempt object move" }),
    );
    expect(canvas.props!.nodes).toBe(before.nodes);
    expect(canvas.props!.onMove).toBe(before.onMove);
    fireEvent.click(screen.getByRole("button", { name: "Station" }));
    noPlacementControls();
    fireEvent.click(screen.getByRole("button", { name: /^Alpha/ }));
    noPlacementControls();
    fireEvent.click(
      screen.getByRole("button", { name: "Workspace preferences" }),
    );
    noPlacementControls();
    await waitFor(() => {
      const saved = JSON.parse(
        localStorage.getItem("aberration:spatial:system:v1:1")!,
      );
      expect(saved.positions).toEqual({});
      expect(saved.locks).toEqual({});
      expect(saved.layoutMode).toBe("automatic");
    });
    expect(apiClient.put).not.toHaveBeenCalled();
  });
  it("browses a dense entity without adding its readings to the scene, then locates one selected reading", async () => {
    const document = fixture();
    document.streams.push(
      ...Array.from({ length: 100 }, (_, index) => ({
        ...document.streams[0]!,
        id: `probe:${index}`,
        label: `Probe ${String(index).padStart(3, "0")}`,
        topic: `weather/probe/${String(index).padStart(3, "0")}`,
        category: "Diagnostics",
      })),
    );
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot(document));
    render(
      <MemoryRouter>
        <ConfiguredSystemWorkspace onPreview={vi.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(scene().nodes).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Station" }));
    const overview = scene().nodes;
    expect(overview).toHaveLength(2);
    expect(
      screen.getAllByText("101 topics · 101 readings").length,
    ).toBeGreaterThan(0);
    const search = screen.getByRole("searchbox", {
      name: "Search topics and readings",
    });
    fireEvent.change(search, { target: { value: "weather/probe/099" } });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Inspect Probe 099 on weather/probe/099",
      }),
    );
    expect(
      scene()
        .nodes.map((node) => node.id)
        .sort(),
    ).toEqual(["broker", "probe:99", "station"]);
    for (const node of overview)
      expect(
        scene().nodes.find((item) => item.id === node.id)!.position,
      ).toEqual(node.position);
    expect(apiClient.put).not.toHaveBeenCalled();
  });
  it("migrates current-ID manual layouts and fits once while preserving personal groups and perspectives", async () => {
    const document = fixture();
    const projection = projectSystemDocument(document);
    const camera = {
      ...projection.workspace.camera,
      target: [100, 0, 100] as [number, number, number],
    };
    const personalGroups = [
      {
        id: "personal:one",
        name: "Favorites",
        color: "#1177cc",
        memberIds: ["station"],
      },
    ];
    const perspectives = [{ id: "saved-view", name: "Overview", camera }];
    localStorage.setItem(
      "aberration:spatial:system:v1:1",
      JSON.stringify({
        ...projection.workspace,
        layoutMode: "manual",
        camera,
        positions: {
          broker: { x: 100, z: 100 },
          station: { x: 100, z: 100 },
          temperature: { x: 100, z: 100 },
        },
        locks: { broker: true, station: true, temperature: true },
        groups: projection.workspace.groups.map((group) => ({
          ...group,
          locked: true,
          collapsed: true,
        })),
        personalGroups,
        perspectives,
      }),
    );
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot(document));
    render(
      <MemoryRouter>
        <ConfiguredSystemWorkspace onPreview={vi.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(scene().nodes).toHaveLength(2));
    expect(canvas.props!.fitRequest).toBe(1);
    expect(
      scene().nodes.find((node) => node.id === "station")!.position,
    ).toEqual(
      projection.topology.nodes.find((node) => node.id === "station")!.position,
    );
    expect(scene().nodes.every((node) => !node.locked)).toBe(true);
    expect(
      screen.getByRole("button", { name: "Show personal group Favorites" }),
    ).not.toBeNull();
    await waitFor(() => {
      const saved = JSON.parse(
        localStorage.getItem("aberration:spatial:system:v1:1")!,
      );
      expect(saved.positions).toEqual({});
      expect(saved.locks).toEqual({});
      expect(
        saved.groups.every(
          (group: SpatialGroup) => !group.locked && !group.collapsed,
        ),
      ).toBe(true);
      expect(saved.personalGroups).toEqual(personalGroups);
      expect(saved.perspectives).toEqual(perspectives);
      expect(saved.camera).toEqual(camera);
    });
  });
  it("restores an automatic view's camera without fitting again", async () => {
    const { workspace } = projectSystemDocument(fixture());
    const camera = { ...workspace.camera, zoom: 1.7 };
    localStorage.setItem(
      "aberration:spatial:system:v1:1",
      JSON.stringify({ ...workspace, positions: {}, locks: {}, camera }),
    );
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
    render(
      <MemoryRouter>
        <ConfiguredSystemWorkspace onPreview={vi.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(scene().nodes).toHaveLength(2));
    expect(canvas.props!.camera).toEqual(camera);
    expect(canvas.props!.fitRequest).toBe(0);
  });
  it("keeps scene topology stable when only the camera changes", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
    render(
      <MemoryRouter>
        <ConfiguredSystemWorkspace onPreview={vi.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(scene().nodes.length).toBeGreaterThan(0));
    const before = canvas.props!;
    fireEvent.click(screen.getByRole("button", { name: "Move camera" }));
    expect(canvas.props!.camera.zoom).toBeCloseTo(before.camera.zoom + 0.1);
    expect(canvas.props!.nodes).toBe(before.nodes);
    expect(canvas.props!.edges).toBe(before.edges);
    expect(canvas.props!.groups).toBe(before.groups);
    expect(canvas.props!.pulseRoutes).toBe(before.pulseRoutes);
    expect(canvas.props!.pulseSources).toBe(before.pulseSources);
    fireEvent.click(
      screen.getByRole("button", { name: "Workspace preferences" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "Perspective name" }),
      { target: { value: "Overview" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save perspective" }));
    expect(canvas.props!.nodes).toBe(before.nodes);
    expect(canvas.props!.edges).toBe(before.edges);
    expect(canvas.props!.groups).toBe(before.groups);
    expect(canvas.props!.pulseRoutes).toBe(before.pulseRoutes);
    expect(canvas.props!.pulseSources).toBe(before.pulseSources);
  });
  it("preserves saved catalog names and membership when personal grouping changes", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
    vi.mocked(apiClient.put).mockImplementation(async (_endpoint, payload) => {
      void _endpoint;
      return {
        data: snapshot((payload as { document: SystemDocument }).document, 8),
      };
    });
    render(
      <MemoryRouter>
        <ConfiguredSystemWorkspace onPreview={vi.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(scene().nodes.some((node) => node.id === "station")).toBe(true),
    );
    expect(scene().nodes.some((node) => node.id === "temperature")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /^Beta/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Edit group and members" }),
    );
    fireEvent.change(screen.getByLabelText("group name"), {
      target: { value: "Canonical roof" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Temperature" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^Canonical roof/ }),
      ).not.toBeNull(),
    );
    // Catalog membership is saved independently of the broker regions drawn on the plane.
    const saved = (
      vi.mocked(apiClient.put).mock.calls[0]![1] as { document: SystemDocument }
    ).document;
    expect(saved.groups.find((group) => group.id === "beta")).toMatchObject({
      label: "Canonical roof",
      member_ids: ["temperature"],
    });
    fireEvent.click(screen.getByRole("button", { name: "Station" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Create personal group" }),
    );
    const name = screen.getByRole("textbox", {
      name: "New personal group name",
    });
    fireEvent.change(name, { target: { value: "My workspace" } });
    fireEvent.keyDown(name, { key: "Enter" });
    fireEvent.change(screen.getByLabelText("Color for My workspace"), {
      target: { value: "#9911cc" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Return to system overview" }),
    );
    expect(
      screen.getByRole("button", { name: /^Canonical roof/ }),
    ).not.toBeNull();
    expect(
      saved.groups.find((group) => group.id === "beta")!.member_ids,
    ).toEqual(["temperature"]);
    expect(apiClient.put).toHaveBeenCalledTimes(1);
  });

  it("imports and exports view preferences without restoring obsolete manual placement", async () => {
    const document = { ...fixture(), label: "Imported system" };
    const { workspace } = projectSystemDocument(document);
    const layout = {
      ...workspace,
      layoutMode: "manual",
      positions: { station: { x: 900, z: -900 } },
      locks: { station: true },
      camera: { ...workspace.camera, zoom: 1.4 },
      personalGroups: [
        {
          id: "personal:watch",
          name: "Watch",
          color: "#1177cc",
          memberIds: ["temperature"],
        },
      ],
      perspectives: [
        { id: "view", name: "Saved view", camera: workspace.camera },
      ],
    };
    vi.mocked(apiUtils.get)
      .mockResolvedValueOnce(snapshot())
      .mockResolvedValue(snapshot(document, 8));
    vi.mocked(apiClient.put).mockImplementation(async (_endpoint, payload) => ({
      data: snapshot((payload as { document: SystemDocument }).document, 8),
    }));
    let exported: Blob | undefined;
    const OriginalURL = URL;
    vi.stubGlobal(
      "URL",
      class extends OriginalURL {
        static createObjectURL(blob: Blob) {
          exported = blob;
          return "blob:workspace-test";
        }
        static revokeObjectURL() {}
      },
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(
      <MemoryRouter>
        <ConfiguredSystemWorkspace onPreview={vi.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(scene().nodes).toHaveLength(2));
    fireEvent.click(
      screen.getByRole("button", { name: "Workspace preferences" }),
    );
    const file = new File([], "workspace.json", { type: "application/json" });
    Object.defineProperty(file, "text", {
      value: async () =>
        JSON.stringify({
          format: "aberration-workspace",
          schema_version: 1,
          system: document,
          layout,
        }),
    });
    fireEvent.change(screen.getByLabelText("System configuration file"), {
      target: { files: [file] },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Replace saved definition" }),
    );
    await waitFor(() => expect(canvas.props!.camera.zoom).toBe(1.4));
    expect(
      scene().nodes.find((node) => node.id === "station")!.position,
    ).toEqual(
      projectSystemDocument(document).topology.nodes.find(
        (node) => node.id === "station",
      )!.position,
    );
    expect(canvas.props!.editMode).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Export workspace" }));
    await waitFor(() => expect(exported).toBeDefined());
    const contents = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(exported!);
    });
    const bundle = JSON.parse(contents);
    expect(bundle.system.label).toBe("Imported system");
    expect(bundle.layout.positions).toEqual({});
    expect(bundle.layout.locks).toEqual({});
    expect(bundle.layout.layoutMode).toBe("automatic");
    expect(bundle.layout.camera).toEqual(layout.camera);
    expect(bundle.layout.personalGroups).toEqual(layout.personalGroups);
    expect(bundle.layout.perspectives).toEqual(layout.perspectives);
    expect(apiClient.put).toHaveBeenCalledTimes(1);
  });

  it("filters personal groups independently of catalog groups and returns to the complete overview", async () => {
    const document = fixture();
    document.devices.push({
      id: "other",
      label: "Other entity",
      kind: "sensor",
      connection_id: "broker",
    });
    document.groups[0]!.member_ids.push("other");
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot(document));
    render(
      <MemoryRouter>
        <ConfiguredSystemWorkspace onPreview={vi.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(scene().nodes).toHaveLength(3));
    fireEvent.click(screen.getByRole("button", { name: "Station" }));
    expect(scene().nodes.some((node) => node.id === "temperature")).toBe(false);
    fireEvent.click(
      screen.getByRole("button", { name: "Create personal group" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "New personal group name" }),
      { target: { value: "My focus" } },
    );
    fireEvent.keyDown(
      screen.getByRole("textbox", { name: "New personal group name" }),
      { key: "Enter" },
    );
    expect(
      scene()
        .nodes.map((node) => node.id)
        .sort(),
    ).toEqual(["broker", "station"]);
    expect(
      screen
        .getByRole("button", { name: "Show personal group My focus" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    // Choosing a catalog group clears the personal filter and uses the saved hard structure.
    fireEvent.click(screen.getByRole("button", { name: /^Alpha/ }));
    expect(
      scene()
        .nodes.map((node) => node.id)
        .sort(),
    ).toEqual(["broker", "other", "station"]);
    expect(
      screen
        .getByRole("button", { name: "Show personal group My focus" })
        .getAttribute("aria-pressed"),
    ).toBe("false");
    fireEvent.click(
      screen.getByRole("button", { name: "Show personal group My focus" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Return to system overview" }),
    );
    expect(scene().nodes).toHaveLength(3);
    expect(apiClient.put).not.toHaveBeenCalled();
    expect(document.groups[0]!.member_ids).toEqual([
      "station",
      "temperature",
      "other",
    ]);
  });
});
