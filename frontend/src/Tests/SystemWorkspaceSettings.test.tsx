import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SystemWorkspaceSettings } from "@/features/spatial/SystemWorkspaceSettings";
import {
  createEmptySystem,
  serializeSystemDocument,
} from "@/features/spatial/systemDocument";
import { createDefaultWorkspace } from "@/features/spatial/model";
import { parseWorkspace } from "@/features/spatial/workspace";
import type { SpatialWorkspace } from "@/features/spatial/types";
import type { SystemDocument } from "@/features/spatial/systemTypes";

const fixture = (): SystemDocument => ({
  ...createEmptySystem("Weather system"),
  connections: [
    {
      id: "weather-broker",
      label: "Weather broker",
      protocol: "mqtt",
      host: "weather.example.test",
      port: 1883,
      transport: "tcp",
      tls: false,
    },
  ],
});
const common = () => ({
  document: fixture(),
  revision: 7,
  workspace: createDefaultWorkspace(),
  canEdit: true,
  saving: false,
  saveError: "",
  onSave: vi.fn().mockResolvedValue(true),
  onLayout: vi.fn(),
  onCreate: vi.fn(),
  onExport: vi.fn().mockResolvedValue(undefined),
  onImport: vi.fn().mockResolvedValue(true),
  onRefresh: vi.fn(),
  onNotice: vi.fn(),
});
const file = (contents: string) => {
  const selected = new File([contents], "system.json", {
    type: "application/json",
  });
  Object.defineProperty(selected, "text", {
    value: () => Promise.resolve(contents),
  });
  return selected;
};
const choose = (contents: string) =>
  fireEvent.change(screen.getByLabelText("System configuration file"), {
    target: { files: [file(contents)] },
  });

describe("system configuration files", () => {
  it("previews a configuration before any write and pins the revision at file selection", async () => {
    const props = common();
    const { rerender } = render(<SystemWorkspaceSettings {...props} />);
    const imported = { ...fixture(), label: "Roof observations" };
    choose(serializeSystemDocument(imported));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Replace saved definition" }),
      ).not.toBeNull(),
    );
    expect(screen.getByText("Roof observations")).not.toBeNull();
    expect(props.onImport).not.toHaveBeenCalled();
    expect(props.onLayout).not.toHaveBeenCalled();
    rerender(
      <SystemWorkspaceSettings
        {...props}
        revision={9}
        document={{ ...fixture(), label: "Other editor" }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Replace saved definition" }),
    );
    await waitFor(() =>
      expect(props.onImport).toHaveBeenCalledWith(imported, undefined, 7),
    );
  });

  it("passes a workspace's configuration and layout together and waits for acknowledgement", async () => {
    let acknowledge!: (saved: boolean) => void;
    const props = {
      ...common(),
      onImport: vi.fn(
        () =>
          new Promise<boolean>((resolve) => {
            acknowledge = resolve;
          }),
      ),
    };
    render(<SystemWorkspaceSettings {...props} />);
    const layout = createDefaultWorkspace();
    layout.positions["weather-broker"] = { x: 4, z: 8 };
    layout.camera.zoom = 2;
    choose(
      JSON.stringify({
        format: "aberration-workspace",
        schema_version: 1,
        system: fixture(),
        layout,
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Replace saved definition" }),
      ).not.toBeNull(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Replace saved definition" }),
    );
    expect(props.onImport).toHaveBeenCalledWith(fixture(), layout, 7);
    expect(props.onLayout).not.toHaveBeenCalled();
    expect(
      screen
        .getByRole("button", { name: "Replace saved definition" })
        .matches(":disabled"),
    ).toBe(true);
    await act(async () => {
      acknowledge(false);
    });
    expect(
      screen.getByRole("button", { name: "Replace saved definition" }),
    ).not.toBeNull();
    expect(screen.getByRole("alert").textContent).toContain("not imported");
    expect(props.onLayout).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Replace saved definition" }),
    );
    await act(async () => {
      acknowledge(true);
    });
    expect(
      screen.queryByRole("button", { name: "Replace saved definition" }),
    ).toBeNull();
  });

  it("rejects invalid workspace layouts before exposing the replace action", async () => {
    const props = common();
    render(<SystemWorkspaceSettings {...props} />);
    choose(
      JSON.stringify({
        format: "aberration-workspace",
        schema_version: 1,
        system: fixture(),
        layout: { version: 8 },
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "layout is invalid",
      ),
    );
    expect(
      screen.queryByRole("button", { name: "Replace saved definition" }),
    ).toBeNull();
    expect(props.onImport).not.toHaveBeenCalled();
  });

  it("exports through the canonical export callback and keeps the file actions busy until it finishes", async () => {
    let finish!: () => void;
    const props = {
      ...common(),
      onExport: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            finish = resolve;
          }),
      ),
    };
    render(<SystemWorkspaceSettings {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Export workspace" }));
    expect(props.onExport).toHaveBeenCalledWith(true);
    expect(
      screen
        .getByRole("button", { name: "Import configuration" })
        .matches(":disabled"),
    ).toBe(true);
    expect(props.onSave).not.toHaveBeenCalled();
    await act(async () => {
      finish();
    });
    expect(
      screen
        .getByRole("button", { name: "Export configuration" })
        .matches(":disabled"),
    ).toBe(false);
  });
});

describe("default policy editing", () => {
  it("captures the baseline on edit, then takes the next acknowledged revision for subsequent edits", async () => {
    const props = common();
    const { rerender } = render(<SystemWorkspaceSettings {...props} />);
    fireEvent.change(screen.getByLabelText("Default policy"), {
      target: { value: "sample" },
    });
    fireEvent.change(screen.getByLabelText("Default sampling interval"), {
      target: { value: "25" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save default policy" }),
    );
    await waitFor(() =>
      expect(props.onSave).toHaveBeenCalledWith(
        {
          ...fixture(),
          default_policy: { mode: "sample", interval_seconds: 25 },
        },
        7,
      ),
    );
    const acknowledged = {
      ...fixture(),
      default_policy: { mode: "sample" as const, interval_seconds: 25 },
    };
    rerender(
      <SystemWorkspaceSettings
        {...props}
        document={acknowledged}
        revision={8}
      />,
    );
    fireEvent.change(screen.getByLabelText("Default policy"), {
      target: { value: "original" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save default policy" }),
    );
    await waitFor(() => expect(props.onSave).toHaveBeenCalledTimes(2));
    expect(props.onSave.mock.calls[1]).toEqual([
      {
        ...acknowledged,
        default_policy: { mode: "original", interval_seconds: 25 },
      },
      8,
    ]);
  });

  it("keeps a dirty policy pinned across other saved changes and retains it after failure", async () => {
    const props = { ...common(), onSave: vi.fn().mockResolvedValue(false) };
    const { rerender } = render(<SystemWorkspaceSettings {...props} />);
    fireEvent.change(screen.getByLabelText("Default policy"), {
      target: { value: "sample" },
    });
    fireEvent.change(screen.getByLabelText("Default sampling interval"), {
      target: { value: "30" },
    });
    rerender(
      <SystemWorkspaceSettings
        {...props}
        revision={10}
        document={{ ...fixture(), label: "New saved name" }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save default policy" }),
    );
    await waitFor(() => expect(screen.getByRole("alert")).not.toBeNull());
    expect(props.onSave.mock.calls[0]![1]).toBe(7);
    expect(
      (screen.getByLabelText("Default sampling interval") as HTMLInputElement)
        .value,
    ).toBe("30");
    expect(props.onNotice).not.toHaveBeenCalled();
  });

  it("rejects an out-of-range policy before writing and disables inputs for viewers", async () => {
    const props = common();
    const { rerender } = render(<SystemWorkspaceSettings {...props} />);
    fireEvent.change(screen.getByLabelText("Default policy"), {
      target: { value: "sample" },
    });
    fireEvent.change(screen.getByLabelText("Default sampling interval"), {
      target: { value: "0" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save default policy" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "between 1 and 3600",
      ),
    );
    expect(props.onSave).not.toHaveBeenCalled();
    rerender(<SystemWorkspaceSettings {...props} canEdit={false} />);
    expect(
      screen.getByLabelText("Default sampling interval").matches(":disabled"),
    ).toBe(true);
    expect(
      screen.getByLabelText("System configuration file").matches(":disabled"),
    ).toBe(true);
  });
});

describe("saved perspectives", () => {
  it("roundtrips a top view with its camera, then restores both from a different current view", () => {
    const props = { ...common(), onView: vi.fn() };
    const camera = {
      position: [12, 35, 0] as [number, number, number],
      target: [5, 0, -2] as [number, number, number],
      zoom: 3,
    };
    const { rerender } = render(
      <SystemWorkspaceSettings
        {...props}
        workspace={{ ...props.workspace, camera }}
        view="top"
      />,
    );
    fireEvent.change(screen.getByLabelText("Perspective name"), {
      target: { value: "Top overview" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save perspective" }));
    const saved = props.onLayout.mock.calls[0]![0] as SpatialWorkspace;
    expect(saved.perspectives[0]).toMatchObject({
      name: "Top overview",
      view: "top",
      camera,
    });
    const restored = parseWorkspace(JSON.stringify(saved))!;
    expect(restored.perspectives[0]?.view).toBe("top");
    const currentCamera = {
      position: [20, 20, 20] as [number, number, number],
      target: [0, 0, 0] as [number, number, number],
      zoom: 1,
    };
    rerender(
      <SystemWorkspaceSettings
        {...props}
        workspace={{ ...restored, camera: currentCamera }}
        view="isometric"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Top overview" }));
    expect(props.onView).toHaveBeenCalledWith("top");
    expect(props.onLayout.mock.calls[1]?.[0].camera).toEqual(camera);
    expect(props.onSave).not.toHaveBeenCalled();
  });
});
