import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SystemTopicBrowser } from "@/features/spatial/SystemTopicBrowser";
import { SystemObjectInspector } from "@/features/spatial/SystemObjectInspector";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import { projectSystemDocument } from "@/features/spatial/systemProjection";
import type { SystemStream } from "@/features/spatial/systemTypes";
import type { SystemLiveTelemetry } from "@/features/spatial/systemLiveTelemetry";
import type {
  LiveNodeSnapshot,
  LiveStatus,
} from "@/features/spatial/systemLiveTypes";

afterEach(cleanup);

const base = (id: string, topic: string, label = id): SystemStream => ({
  id,
  label,
  connection_id: "broker",
  device_id: "meter",
  topic,
  value_type: "number",
  category: "Energy",
  unit: "A",
});
const shared = (): SystemStream[] => [
  {
    ...base("temperature", "plant/meter/status", "Temperature"),
    category: "Status",
    unit: "°C",
    payload_pointer: "/temperature",
  },
  {
    ...base("running", "plant/meter/status", "Running"),
    category: "Status",
    value_type: "boolean",
    unit: undefined,
    payload_pointer: "/running",
  },
  {
    ...base("mode", "plant/meter/status", "Mode"),
    category: "Status",
    value_type: "text",
    unit: undefined,
    payload_pointer: "/mode",
  },
  {
    ...base("serial", "plant/meter/status", "Serial number"),
    category: "Status",
    value_type: "identifier",
    unit: undefined,
    payload_pointer: "/serial",
  },
];
const channels = (count = 96): SystemStream[] =>
  Array.from({ length: count }, (_, index) => {
    const suffix = String(index + 1).padStart(3, "0");
    return {
      ...base(
        `channel:${suffix}`,
        `plant/meter/channels/${suffix}`,
        `Channel ${suffix}`,
      ),
      category: index % 2 === 0 ? "Energy" : "Diagnostics",
    };
  });
const streams = () => [...shared(), ...channels()];
const readingButtons = () =>
  screen.queryAllByRole("button", { name: /^Inspect / });

describe("dense MQTT topic navigation", () => {
  it("distinguishes actual topics from JSON readings and expands their individual typed fields", () => {
    const select = vi.fn();
    render(<SystemTopicBrowser streams={streams()} onSelect={select} />);
    expect(screen.getByText("97 topics · 100 readings")).not.toBeNull();
    expect(
      screen.queryByRole("button", {
        name: "Inspect Temperature on plant/meter/status",
      }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Expand topic plant/meter/status" }),
    );
    expect(
      screen
        .getByRole("button", { name: "Collapse topic plant/meter/status" })
        .getAttribute("aria-expanded"),
    ).toBe("true");
    expect(screen.getByText("/temperature · number")).not.toBeNull();
    expect(screen.getByText("/running · boolean")).not.toBeNull();
    expect(screen.getByText("/mode · text")).not.toBeNull();
    expect(screen.getByText("/serial · identifier")).not.toBeNull();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Inspect Running on plant/meter/status",
      }),
    );
    expect(select).toHaveBeenCalledWith("running");
  });

  it("makes every topic reachable while rendering at most twelve topic rows", () => {
    const select = vi.fn();
    const { container } = render(
      <SystemTopicBrowser streams={streams()} onSelect={select} />,
    );
    expect(container.querySelectorAll(".sp-topic-row")).toHaveLength(12);
    expect(
      screen.queryByRole("button", {
        name: "Inspect Channel 096 on plant/meter/channels/096",
      }),
    ).toBeNull();
    const visited = new Set<string>();
    let pageCount = 0;
    while (true) {
      container
        .querySelectorAll(".sp-topic-row code")
        .forEach((code) => visited.add(code.textContent!));
      expect(
        container.querySelectorAll(".sp-topic-row").length,
      ).toBeLessThanOrEqual(12);
      const next = screen.getByRole("button", {
        name: "Next topics",
      }) as HTMLButtonElement;
      pageCount++;
      if (next.disabled) break;
      fireEvent.click(next);
    }
    expect(visited.size).toBe(97);
    expect(pageCount).toBe(9);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Inspect Channel 096 on plant/meter/channels/096",
      }),
    );
    expect(select).toHaveBeenCalledWith("channel:096");
    expect(
      (screen.getByRole("button", { name: "Next topics" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Previous topics" }));
    expect(container.querySelectorAll(".sp-topic-row")).toHaveLength(12);
  });

  it("searches labels, exact paths, payload fields, and categories with a separate category filter", () => {
    render(<SystemTopicBrowser streams={streams()} onSelect={vi.fn()} />);
    const search = screen.getByRole("searchbox", {
      name: "Search topics and readings",
    });
    fireEvent.change(search, { target: { value: "Channel 096" } });
    expect(readingButtons()).toHaveLength(1);
    expect(
      screen.getByRole("button", {
        name: "Inspect Channel 096 on plant/meter/channels/096",
      }),
    ).not.toBeNull();
    fireEvent.change(search, { target: { value: "/channels/080" } });
    expect(readingButtons()).toHaveLength(1);
    expect(
      screen.getByRole("button", {
        name: "Inspect Channel 080 on plant/meter/channels/080",
      }),
    ).not.toBeNull();
    fireEvent.change(search, { target: { value: "Diagnostics" } });
    expect(screen.getByRole("status").textContent).toContain(
      "48 matching topics · 48 readings",
    );
    fireEvent.change(search, { target: { value: "/serial" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Expand topic plant/meter/status" }),
    );
    expect(readingButtons()).toHaveLength(1);
    expect(screen.getByText("1 of 4 readings match")).not.toBeNull();
    fireEvent.change(search, { target: { value: "Channel" } });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter topics by category" }),
      { target: { value: "Energy" } },
    );
    expect(screen.getByRole("status").textContent).toContain(
      "48 matching topics · 48 readings",
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect((search as HTMLInputElement).value).toBe("");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("keeps all readings of a dense JSON topic reachable with bounded field pages", () => {
    const fields = Array.from({ length: 64 }, (_, index) => ({
      ...base(`field:${index}`, "plant/meter/diagnostics", `Field ${index}`),
      payload_pointer: `/field_${index}`,
    }));
    render(<SystemTopicBrowser streams={fields} onSelect={vi.fn()} />);
    expect(screen.getByText("1 topic · 64 readings")).not.toBeNull();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Expand topic plant/meter/diagnostics",
      }),
    );
    const visited = new Set<string>();
    while (true) {
      expect(readingButtons()).toHaveLength(8);
      readingButtons().forEach((button) =>
        visited.add(button.getAttribute("aria-label")!),
      );
      const next = screen.getByRole("button", {
        name: "Next readings in plant/meter/diagnostics",
      }) as HTMLButtonElement;
      if (next.disabled) break;
      fireEvent.click(next);
    }
    expect(visited.size).toBe(64);
    expect(
      screen.getByRole("button", {
        name: "Inspect Field 63 on plant/meter/diagnostics",
      }),
    ).not.toBeNull();
  });

  it("opens the page and payload fields containing the selected reading", () => {
    const fields = Array.from({ length: 20 }, (_, index) => ({
      ...base(`field:${index}`, "plant/meter/diagnostics", `Field ${index}`),
      payload_pointer: `/field_${index}`,
    }));
    render(
      <SystemTopicBrowser
        streams={[...channels(), ...fields]}
        selectedStreamId="field:19"
        onSelect={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: "Collapse topic plant/meter/diagnostics",
      }),
    ).not.toBeNull();
    const selected = screen.getByRole("button", {
      name: "Inspect Field 19 on plant/meter/diagnostics",
    });
    expect(selected.getAttribute("aria-current")).toBe("true");
    expect(readingButtons()).toHaveLength(4);
    expect(screen.getByText("97–97 of 97")).not.toBeNull();
  });

  it("treats identical topic paths on distinct brokers as separate MQTT topics", () => {
    render(
      <SystemTopicBrowser
        streams={[
          base("one", "room/temperature"),
          { ...base("two", "room/temperature"), connection_id: "other-broker" },
        ]}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("2 topics · 2 readings")).not.toBeNull();
    expect(readingButtons()).toHaveLength(2);
  });

  it("uses one shared live subscription and reads only visible values without materializing histories", () => {
    const listeners = new Set<() => void>();
    let status: LiveStatus = {
      phase: "live",
      message: "Connected",
      observing: true,
      active: true,
      connections: [],
    };
    let value = 23;
    const unsubscribe = vi.fn();
    const history = vi.fn(() => {
      throw new Error("History should be lazy");
    });
    const getSnapshot = vi.fn(
      () =>
        ({
          latestValue: value,
          retained: true,
          get samples() {
            return history();
          },
        }) as unknown as LiveNodeSnapshot,
    );
    const subscribeUpdates = vi.fn((listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        unsubscribe();
      };
    });
    const telemetry = {
      subscribeUpdates,
      getStatus: () => status,
      getSnapshot,
    } as unknown as SystemLiveTelemetry;
    const { unmount } = render(
      <SystemTopicBrowser
        streams={channels()}
        telemetry={telemetry}
        onSelect={vi.fn()}
      />,
    );
    expect(subscribeUpdates).toHaveBeenCalledOnce();
    expect(getSnapshot).toHaveBeenCalledTimes(12);
    expect(screen.getAllByText("23")).toHaveLength(12);
    expect(screen.getAllByLabelText("Retained reading")).toHaveLength(12);
    expect(history).not.toHaveBeenCalled();
    getSnapshot.mockClear();
    act(() => {
      value = 24;
      status = { ...status };
      listeners.forEach((listener) => listener());
    });
    expect(screen.getAllByText("24")).toHaveLength(12);
    expect(getSnapshot).toHaveBeenCalledTimes(12);
    expect(subscribeUpdates).toHaveBeenCalledOnce();
    expect(history).not.toHaveBeenCalled();
    unmount();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("offers the same entity's complete topic browser while inspecting a selected chart", () => {
    const document = {
      ...createEmptySystem(),
      connections: [
        {
          id: "broker",
          label: "Broker",
          protocol: "mqtt" as const,
          host: "test.invalid",
          port: 1883,
          transport: "tcp" as const,
          tls: false,
        },
      ],
      devices: [
        {
          id: "meter",
          label: "Main meter",
          kind: "meter",
          connection_id: "broker",
        },
      ],
      streams: streams(),
    };
    const projection = projectSystemDocument(document);
    const selected = projection.topology.nodes.find(
      (node) => node.id === "channel:096",
    )!;
    const select = vi.fn();
    render(
      <SystemObjectInspector
        node={selected}
        document={document}
        canEdit={true}
        saveError=""
        disabledReason=""
        onRename={vi.fn()}
        onEdit={vi.fn()}
        onSelect={select}
        onFocus={vi.fn()}
      />,
    );
    const browser = within(
      screen.getByRole("region", { name: "MQTT topics and readings" }),
    );
    expect(browser.getByText("97 topics · 100 readings")).not.toBeNull();
    expect(
      browser
        .getByRole("button", {
          name: "Inspect Channel 096 on plant/meter/channels/096",
        })
        .getAttribute("aria-current"),
    ).toBe("true");
    fireEvent.change(browser.getByRole("searchbox"), {
      target: { value: "Channel 001" },
    });
    fireEvent.click(
      browser.getByRole("button", {
        name: "Inspect Channel 001 on plant/meter/channels/001",
      }),
    );
    expect(select).toHaveBeenCalledWith("channel:001");
  });
});
