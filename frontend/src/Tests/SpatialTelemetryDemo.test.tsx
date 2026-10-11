import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SpatialTelemetryDemo from "@/pages/SpatialTelemetryDemo";
import {
  createDefaultWorkspace,
  createDemoTopology,
} from "@/features/spatial/model";
import type { SpatialCanvasProps } from "@/features/spatial/SpatialScene";

const canvas = vi.hoisted(() => ({ props: null as SpatialCanvasProps | null }));
const storageKey = "aberration:spatial:v1:7:demo";

vi.mock("@/auth/AuthContext", () => ({
  useAuth: () => ({ userId: 7, isAuthenticated: false }),
}));
vi.mock("@/features/spatial/SpatialCanvas", () => ({
  SpatialCanvas: (props: SpatialCanvasProps) => {
    canvas.props = props;
    return <div data-testid="telemetry-canvas" />;
  },
}));
vi.mock("@/components/EChart", () => ({
  EChart: () => <div data-testid="telemetry-chart" />,
}));
vi.mock("@/features/spatial/useCatalogNames", () => ({
  useCatalogNames: () => ({
    status: "sign-in-required",
    canRename: () => false,
  }),
  fetchSavedSpatialCatalog: vi.fn(),
}));

describe("optional telemetry preview automatic placement", () => {
  beforeEach(() => {
    localStorage.clear();
    canvas.props = null;
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("ignores old manual positions and locks while preserving camera and collection appearance", async () => {
    const workspace = createDefaultWorkspace();
    workspace.layoutMode = "manual";
    workspace.positions["sensor-1"] = { x: 900, z: -800 };
    workspace.locks["sensor-1"] = true;
    workspace.groups[0]!.locked = true;
    workspace.groups[0]!.color = "#123456";
    workspace.camera.zoom = 1.7;
    localStorage.setItem(storageKey, JSON.stringify(workspace));

    render(<SpatialTelemetryDemo />);

    const original = createDemoTopology().nodes.find(
      (node) => node.id === "sensor-1",
    )!;
    const sensor = canvas.props!.nodes.find((node) => node.id === "sensor-1")!;
    expect(sensor.position).toEqual(original.position);
    expect(sensor.locked).toBe(false);
    expect(canvas.props!.camera.zoom).toBe(1.7);
    expect(canvas.props!.groups[0]).toMatchObject({
      locked: false,
      color: "#123456",
    });
    expect(canvas.props!.editMode).toBe(false);
    expect(canvas.props!.onGroupMove).toBeUndefined();

    act(() => canvas.props!.onMove({ "sensor-1": { x: 10, z: 20 } }));
    fireEvent.keyDown(window, { key: "ArrowRight", shiftKey: true });
    expect(
      canvas.props!.nodes.find((node) => node.id === "sensor-1")!.position,
    ).toEqual(original.position);
    expect(
      screen.queryByRole("button", {
        name: /Arrange|Tidy|Undo layout|Lock|Pin/,
      }),
    ).toBeNull();

    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem(storageKey)!);
      expect(saved.layoutMode).toBe("automatic");
      expect(saved.positions).toEqual({});
      expect(saved.locks).toEqual({});
      expect(saved.camera.zoom).toBe(1.7);
    });
  });

  it("keeps charts, collection editing, camera controls, and feed controls without placement controls", () => {
    render(<SpatialTelemetryDemo />);
    const sensor = canvas.props!.nodes.find((node) => node.id === "sensor-1")!;
    fireEvent.click(screen.getByRole("button", { name: sensor.label }));
    expect(screen.getByTestId("telemetry-chart")).toBeTruthy();
    expect(screen.getByLabelText(/Publish cadence/)).toBeTruthy();
    expect(screen.getByLabelText("Collection")).toBeTruthy();
    expect(screen.queryByLabelText("X position")).toBeNull();
    expect(screen.queryByLabelText("Z position")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Pin object|Pinned/ }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Fit scene" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Top view" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Pause telemetry" }));
    expect(
      screen.getByRole("button", { name: "Resume telemetry" }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByText(canvas.props!.groups[0]!.name, { selector: "span" }),
    );
    expect(screen.getByLabelText("Collection colour")).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: /Lock collection|Unlock collection/,
      }),
    ).toBeNull();
    expect(screen.queryByText(/Arrange mode|pinned members/)).toBeNull();
  });

  it("imports camera and collection preferences without restoring manual coordinates or locks", async () => {
    render(<SpatialTelemetryDemo />);
    fireEvent.click(
      screen.getByRole("button", { name: "Workspace preferences" }),
    );
    expect(screen.getByRole("button", { name: "Export view" })).toBeTruthy();
    const imported = createDefaultWorkspace();
    imported.layoutMode = "manual";
    imported.positions["sensor-1"] = { x: 800, z: 700 };
    imported.locks["sensor-1"] = true;
    imported.groups[0]!.locked = true;
    imported.camera.zoom = 2.1;
    const file = new File([JSON.stringify(imported)], "old-layout.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", {
      value: async () => JSON.stringify(imported),
    });
    fireEvent.change(screen.getByLabelText("View JSON file"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(canvas.props!.camera.zoom).toBe(2.1));
    const original = createDemoTopology().nodes.find(
      (node) => node.id === "sensor-1",
    )!;
    expect(
      canvas.props!.nodes.find((node) => node.id === "sensor-1")!,
    ).toMatchObject({ position: original.position, locked: false });
    expect(canvas.props!.groups.every((group) => !group.locked)).toBe(true);
    expect(JSON.parse(localStorage.getItem(storageKey)!).positions).toEqual({});
    expect(JSON.parse(localStorage.getItem(storageKey)!).locks).toEqual({});
  });
});
