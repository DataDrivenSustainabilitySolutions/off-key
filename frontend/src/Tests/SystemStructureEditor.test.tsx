import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SystemStructureEditor } from "@/features/spatial/SystemStructureEditor";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import type { SystemDocument } from "@/features/spatial/systemTypes";

const fixture = (): SystemDocument => ({
  ...createEmptySystem("Weather observations"),
  default_policy: { mode: "sample", interval_seconds: 30 },
  connections: [
    {
      id: "broker:east",
      label: "East broker",
      protocol: "mqtt",
      host: "east.example.test",
      port: 1883,
      transport: "tcp",
      tls: false,
    },
    {
      id: "broker:west",
      label: "West broker",
      protocol: "mqtt",
      host: "west.example.test",
      port: 1883,
      transport: "tcp",
      tls: false,
    },
  ],
  devices: [
    {
      id: "station",
      label: "Weather station",
      kind: "weather-station",
      connection_id: "broker:east",
    },
  ],
  streams: [
    {
      id: "temperature",
      label: "Temperature",
      connection_id: "broker:east",
      device_id: "station",
      topic: "weather/temperature",
      value_type: "number",
      category: "Weather",
      policy: { mode: "off", interval_seconds: 10 },
    },
  ],
  groups: [
    {
      id: "group:east",
      label: "East roof",
      member_ids: ["station", "temperature"],
    },
    { id: "group:west", label: "West roof", member_ids: [] },
  ],
});
const common = () => ({
  revision: 7,
  canEdit: true,
  saving: false,
  saveError: "",
  onSave: vi.fn().mockResolvedValue(true),
  onDone: vi.fn(),
});

describe("generic structure editing", () => {
  it("creates an MQTT connection for a non-charging system with transport and credential references", async () => {
    const props = common();
    render(
      <SystemStructureEditor
        {...props}
        document={createEmptySystem("Weather")}
        kind="connection"
      />,
    );
    fireEvent.change(screen.getByLabelText("connection name"), {
      target: { value: "Roof observatory" },
    });
    fireEvent.change(screen.getByLabelText("Broker host"), {
      target: { value: "weather.example.test" },
    });
    fireEvent.change(screen.getByLabelText("Broker port"), {
      target: { value: "443" },
    });
    fireEvent.change(screen.getByLabelText("Transport"), {
      target: { value: "websocket" },
    });
    fireEvent.change(screen.getByLabelText("WebSocket path"), {
      target: { value: "/mqtt" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Use TLS" }));
    fireEvent.change(screen.getByLabelText("Credential reference"), {
      target: { value: "credentials/weather" },
    });
    expect(props.onSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(props.onDone).toHaveBeenCalled());
    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        connections: [
          expect.objectContaining({
            id: expect.stringMatching(/^connection:/),
            label: "Roof observatory",
            host: "weather.example.test",
            port: 443,
            transport: "websocket",
            websocket_path: "/mqtt",
            tls: true,
            credential_ref: "credentials/weather",
          }),
        ],
      }),
      7,
    );
  });

  it("creates a typed stream with a payload binding and explicitly leaves collection Off", async () => {
    const props = common();
    render(
      <SystemStructureEditor {...props} document={fixture()} kind="stream" />,
    );
    fireEvent.change(screen.getByLabelText("stream name"), {
      target: { value: "Roof humidity" },
    });
    fireEvent.change(screen.getByLabelText("MQTT topic"), {
      target: { value: "weather/roof/readings" },
    });
    fireEvent.change(screen.getByLabelText("Payload field"), {
      target: { value: "/sensors/humidity" },
    });
    fireEvent.change(screen.getByLabelText("Device"), {
      target: { value: "station" },
    });
    fireEvent.change(screen.getByLabelText("Unit"), { target: { value: "%" } });
    expect(screen.queryByLabelText("Collection policy")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(props.onSave).toHaveBeenCalled());
    const saved = props.onSave.mock.calls[0]![0] as SystemDocument;
    expect(saved.streams[1]).toMatchObject({
      label: "Roof humidity",
      topic: "weather/roof/readings",
      payload_pointer: "/sensors/humidity",
      device_id: "station",
      value_type: "number",
      unit: "%",
      policy: { mode: "off", interval_seconds: 10 },
    });
    expect(saved.default_policy.mode).toBe("sample");
  });

  it("removes hidden WebSocket-only fields when switching an existing connection back to TCP", async () => {
    const system = fixture();
    system.connections[0] = {
      ...system.connections[0]!,
      transport: "websocket",
      websocket_path: "/mqtt",
    };
    const props = common();
    render(
      <SystemStructureEditor
        {...props}
        document={system}
        kind="connection"
        entityId="broker:east"
      />,
    );
    fireEvent.change(screen.getByLabelText("Transport"), {
      target: { value: "tcp" },
    });
    expect(screen.queryByLabelText("WebSocket path")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(props.onSave).toHaveBeenCalled());
    expect(
      (props.onSave.mock.calls[0]![0] as SystemDocument).connections.find(
        (entry) => entry.id === "broker:east",
      ),
    ).not.toHaveProperty("websocket_path");
  });

  it("moves a device's attached streams together while retaining IDs and topic bindings", async () => {
    const props = common();
    render(
      <SystemStructureEditor
        {...props}
        document={fixture()}
        kind="device"
        entityId="station"
      />,
    );
    fireEvent.change(screen.getByLabelText("Connection"), {
      target: { value: "broker:west" },
    });
    expect(screen.getByText(/moves this device’s 1 stream/)).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(props.onSave).toHaveBeenCalled());
    const saved = props.onSave.mock.calls[0]![0] as SystemDocument;
    expect(saved.devices[0]?.connection_id).toBe("broker:west");
    expect(saved.streams[0]).toMatchObject({
      id: "temperature",
      connection_id: "broker:west",
      topic: "weather/temperature",
    });
  });

  it("requires a removal confirmation before saving the cascade", async () => {
    const props = common();
    render(
      <SystemStructureEditor
        {...props}
        document={fixture()}
        kind="device"
        entityId="station"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Remove device" }));
    expect(props.onSave).not.toHaveBeenCalled();
    expect(screen.getByText(/1 dependent objects/)).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
    await waitFor(() => expect(props.onSave).toHaveBeenCalled());
    const saved = props.onSave.mock.calls[0]![0] as SystemDocument;
    expect(saved.devices).toEqual([]);
    expect(saved.streams).toEqual([]);
    expect(saved.groups[0]?.member_ids).toEqual([]);
  });

  it("preserves explicit stream bindings when a device connection is cleared", async () => {
    const props = common();
    render(
      <SystemStructureEditor
        {...props}
        document={fixture()}
        kind="device"
        entityId="station"
      />,
    );
    fireEvent.change(screen.getByLabelText("Connection"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(props.onSave).toHaveBeenCalled());
    const saved = props.onSave.mock.calls[0]![0] as SystemDocument;
    expect(saved.devices[0]).not.toHaveProperty("connection_id");
    expect(saved.streams[0]?.connection_id).toBe("broker:east");
  });

  it("keeps the configuration's object order stable when editing an existing definition", async () => {
    const props = common();
    render(
      <SystemStructureEditor
        {...props}
        document={fixture()}
        kind="connection"
        entityId="broker:east"
      />,
    );
    fireEvent.change(screen.getByLabelText("connection name"), {
      target: { value: "Renamed east" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(props.onSave).toHaveBeenCalled());
    expect(
      (props.onSave.mock.calls[0]![0] as SystemDocument).connections.map(
        (item) => item.id,
      ),
    ).toEqual(["broker:east", "broker:west"]);
  });

  it("moves selected group members out of their previous group atomically", async () => {
    const props = common();
    render(
      <SystemStructureEditor
        {...props}
        document={fixture()}
        kind="group"
        entityId="group:west"
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Temperature" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(props.onSave).toHaveBeenCalled());
    const saved = props.onSave.mock.calls[0]![0] as SystemDocument;
    expect(
      saved.groups.find((entry) => entry.id === "group:west")?.member_ids,
    ).toEqual(["temperature"]);
    expect(
      saved.groups.find((entry) => entry.id === "group:east")?.member_ids,
    ).toEqual(["station"]);
  });

  it("keeps a conflicting draft pinned to its original revision after canonical data refreshes", async () => {
    const props = { ...common(), onSave: vi.fn().mockResolvedValue(false) };
    const { rerender } = render(
      <SystemStructureEditor
        {...props}
        document={fixture()}
        kind="stream"
        entityId="temperature"
      />,
    );
    fireEvent.change(screen.getByLabelText("stream name"), {
      target: { value: "My unsaved title" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.getByRole("alert")).not.toBeNull());
    const updated = fixture();
    updated.streams[0]!.label = "Other editor";
    rerender(
      <SystemStructureEditor
        {...props}
        saveError="Revision conflict. Review the saved system."
        document={updated}
        revision={9}
        kind="stream"
        entityId="temperature"
      />,
    );
    expect(
      (screen.getByLabelText("stream name") as HTMLInputElement).value,
    ).toBe("My unsaved title");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(props.onSave).toHaveBeenCalledTimes(2));
    expect(props.onSave.mock.calls[1]![1]).toBe(7);
    expect(props.onDone).not.toHaveBeenCalled();
  });

  it("disables edits while awaiting acknowledgement and closes only after it succeeds", async () => {
    let acknowledge!: (saved: boolean) => void;
    const props = {
      ...common(),
      onSave: vi.fn(
        () =>
          new Promise<boolean>((resolve) => {
            acknowledge = resolve;
          }),
      ),
    };
    render(
      <SystemStructureEditor
        {...props}
        document={fixture()}
        kind="group"
        entityId="group:east"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      screen
        .getByRole("checkbox", { name: "Temperature" })
        .matches(":disabled"),
    ).toBe(true);
    expect(props.onDone).not.toHaveBeenCalled();
    await act(async () => {
      acknowledge(true);
    });
    expect(props.onDone).toHaveBeenCalledTimes(1);
  });
});
