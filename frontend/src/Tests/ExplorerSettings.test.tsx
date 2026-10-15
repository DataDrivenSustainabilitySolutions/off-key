import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ExplorerSettings from "@/features/explorer/ExplorerSettings";
import { createEmptySystem, importSystemDocument } from "@/features/catalogue/systemDocument";
import type { SystemDocument } from "@/features/catalogue/systemTypes";

const fixture = (): SystemDocument => ({
  ...createEmptySystem("Weather system"),
  connections: [{
    id: "broker:weather", label: "Weather broker", protocol: "mqtt",
    host: "weather.example.test", port: 1883, transport: "tcp", tls: false,
  }],
  devices: [{ id: "device:roof", label: "Roof", kind: "sensor", connection_id: "broker:weather" }],
  streams: [{
    id: "stream:temperature", label: "Temperature", topic: "roof/temperature",
    connection_id: "broker:weather", device_id: "device:roof", value_type: "number", category: "Weather", unit: "°C",
  }],
});
const common = () => ({
  document: fixture(), revision: 7,
  canEdit: true, saving: false, error: "",
  onImport: vi.fn().mockResolvedValue(true),
  onExport: vi.fn().mockResolvedValue(undefined),
  onCreate: vi.fn(),
});
const file = (contents: string) => {
  const selected = new File([contents], "system.json", { type: "application/json" });
  Object.defineProperty(selected, "text", { configurable: true, value: () => Promise.resolve(contents) });
  return selected;
};
const choose = (contents: string) =>
  fireEvent.change(screen.getByLabelText("Catalogue file"), { target: { files: [file(contents)] } });
const preview = () => screen.getByRole("button", { name: "Replace saved catalogue" });
const waitForPreview = () => waitFor(() => expect(preview()).not.toBeNull());
describe("explorer settings catalogue files", () => {
  it("reviews a plain catalogue before writing and pins its selected revision", async () => {
    const props = common();
    const { rerender } = render(<ExplorerSettings {...props} />);
    const imported = { ...fixture(), label: "Roof observations" };
    choose(JSON.stringify(imported));
    await waitForPreview();
    expect(screen.getByText("Roof observations")).not.toBeNull();
    expect(screen.getByText("system.json")).not.toBeNull();
    expect(screen.getByText("1 broker · 1 entity · 1 reading · 0 collections")).not.toBeNull();
    expect(props.onImport).not.toHaveBeenCalled();
    rerender(<ExplorerSettings {...props} revision={9} />);
    fireEvent.click(preview());
    await waitFor(() => expect(props.onImport).toHaveBeenCalledWith(imported, 7));
    expect(screen.queryByRole("button", { name: "Replace saved catalogue" })).toBeNull();
  });

  it("rejects retired provider-specific catalogue files", () => {
    expect(() => importSystemDocument(JSON.stringify({ provider: "ambibox", schema_version: 1, sources: [] }))).toThrow();
  });

  it.each([
    ["broken json", "valid JSON"],
    [JSON.stringify({ format: "aberration-explorer-workspace", schema_version: 1, system: fixture() }), "unsupported field"],
    [JSON.stringify({ format: "aberration-workspace", schema_version: 1, system: fixture() }), "unsupported field"],
    [JSON.stringify({ ...fixture(), streams: [{ ...fixture().streams[0]!, connection_id: "missing" }] }), "connection does not exist"],
  ])("rejects invalid input before any database mutation", async (contents, message) => {
    const props = common();
    render(<ExplorerSettings {...props} />);
    choose(contents);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(message));
    expect(props.onImport).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Replace saved catalogue" })).toBeNull();
  });

  it("rejects large files before reading them", async () => {
    const props = common();
    render(<ExplorerSettings {...props} />);
    const huge = file(" ".repeat(1_048_576 + 1));
    const read = vi.spyOn(huge, "text");
    fireEvent.change(screen.getByLabelText("Catalogue file"), { target: { files: [huge] } });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("1 MiB"));
    expect(read).not.toHaveBeenCalled();
    expect(props.onImport).not.toHaveBeenCalled();
  });

  it("keeps the preview after a save conflict and waits for acknowledgement", async () => {
    let acknowledge!: (saved: boolean) => void;
    const props = { ...common(), onImport: vi.fn(() => new Promise<boolean>((resolve) => { acknowledge = resolve; })) };
    render(<ExplorerSettings {...props} />);
    choose(JSON.stringify(fixture()));
    await waitForPreview();
    fireEvent.click(preview());
    fireEvent.click(preview());
    expect(props.onImport).toHaveBeenCalledTimes(1);
    expect(preview().matches(":disabled")).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("Saving catalogue…");
    await act(async () => acknowledge(false));
    expect(screen.getByRole("alert").textContent).toContain("not imported");
    expect(preview().matches(":disabled")).toBe(false);
    fireEvent.click(preview());
    await act(async () => acknowledge(true));
    expect(screen.queryByRole("button", { name: "Replace saved catalogue" })).toBeNull();
  });

  it("cancels a reviewed import without saving and exports only the catalogue", async () => {
    const props = common();
    render(<ExplorerSettings {...props} />);
    choose(JSON.stringify(fixture()));
    await waitForPreview();
    fireEvent.click(screen.getByRole("button", { name: "Cancel import" }));
    expect(props.onImport).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Replace saved catalogue" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Export catalogue" }));
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(props.onExport.mock.calls).toEqual([[]]);
    expect(screen.queryByRole("button", { name: "Export workspace" })).toBeNull();
    expect(screen.queryByText(/personal group/i)).toBeNull();
  });

  it("locks concurrent file actions until export completes and reports failures", async () => {
    let fail!: (error: Error) => void;
    const props = { ...common(), onExport: vi.fn(() => new Promise<void>((_resolve, reject) => { fail = reject; })) };
    render(<ExplorerSettings {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Export catalogue" }));
    fireEvent.click(screen.getByRole("button", { name: "Export catalogue" }));
    expect(props.onExport).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Import file" }).matches(":disabled")).toBe(true);
    await act(async () => fail(new Error("Export failed.")));
    expect(screen.getByRole("alert").textContent).toBe("Export failed.");
    expect(screen.getByRole("button", { name: "Import file" }).matches(":disabled")).toBe(false);
  });

  it("offers structure edits separately and allows viewers to export", () => {
    const props = common();
    const { rerender } = render(<ExplorerSettings {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Add broker" }));
    fireEvent.click(screen.getByRole("button", { name: "Add entity" }));
    fireEvent.click(screen.getByRole("button", { name: "Add reading" }));
    fireEvent.click(screen.getByRole("button", { name: "Add collection" }));
    expect(props.onCreate.mock.calls).toEqual([["connection"], ["device"], ["stream"], ["group"]]);
    rerender(<ExplorerSettings {...props} canEdit={false} />);
    expect(screen.getByRole("button", { name: "Add broker" }).matches(":disabled")).toBe(true);
    expect(screen.getByLabelText("Catalogue file").matches(":disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Export catalogue" }).matches(":disabled")).toBe(false);
    rerender(<ExplorerSettings {...props} document={createEmptySystem()} />);
    expect(screen.getByRole("button", { name: "Add reading" }).matches(":disabled")).toBe(true);
  });

  it("keeps a reviewed file cancellable when catalogue edit access is lost", async () => {
    const props = common();
    const { rerender } = render(<ExplorerSettings {...props} />);
    choose(JSON.stringify(fixture()));
    await waitForPreview();
    rerender(<ExplorerSettings {...props} canEdit={false} />);
    expect(preview().matches(":disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Cancel import" }));
    expect(screen.queryByRole("region", { name: "Import preview" })).toBeNull();
    expect(props.onImport).not.toHaveBeenCalled();
  });
});
