import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import toast from "react-hot-toast";

import DataSources from "../pages/DataSources";
import type { Catalog, CatalogSnapshot } from "../types/collection";
import { effectivePolicy } from "../types/collection";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("../lib/api-client", () => ({ apiUtils: api }));
vi.mock("../components/NavigationBar", () => ({
  NavigationBar: () => <nav />,
}));
vi.mock("react-hot-toast", () => ({ default: { success: vi.fn() } }));

const empty: Catalog = {
  schema_version: 1,
  provider: "ambibox",
  default_policy: { mode: "sample", interval_seconds: 10 },
  sources: [],
};
const inventory = (): Catalog => ({
  ...empty,
  sources: [
    {
      id: "broker-1",
      label: "Main broker",
      host: "main.ts.net",
      port: 1883,
      verified: true,
      forward_port: 20000,
      chargers: ["Yard", "Garage"].map((label, index) => ({
        id: `charger-${index}`,
        local_id: String(index),
        label,
        policy: { mode: "off", interval_seconds: 10 },
        sensors: [
          {
            key: "temperature",
            label: "Temperature",
            category: "Thermal",
            value_type: "number",
            unit: "C",
            upstream_topic: `device/evCharger/${index}/temperature`,
            policy: null,
          },
          {
            key: "current",
            label: "AC current",
            category: "Current",
            value_type: "number",
            unit: "A",
            upstream_topic: `device/evCharger/${index}/current`,
            policy: null,
          },
          {
            key: "connected",
            label: "Connected",
            category: "Status",
            value_type: "boolean",
            unit: null,
            upstream_topic: `device/evCharger/${index}/connected`,
            policy: null,
          },
        ],
      })),
    },
    {
      id: "broker-2",
      label: "Candidate",
      host: "candidate.ts.net",
      port: 1883,
      verified: false,
      forward_port: null,
      chargers: [],
    },
  ],
});
const snapshot = (catalog = empty, can_edit = true): CatalogSnapshot => ({
  revision: 1,
  catalog,
  can_edit,
  sensor_activity: {},
  ingress: {},
  collection: {},
  updated_at: null,
  updated_by: null,
});
const mockSnapshot = (value = snapshot()) => api.get.mockResolvedValue(value);
const show = () => {
  const router = createMemoryRouter(
    [
      { path: "/sources", element: <DataSources /> },
      { path: "/away", element: <p>Another page</p> },
    ],
    { initialEntries: ["/away", "/sources"] },
  );
  return { ...render(<RouterProvider router={router} />), router };
};

beforeEach(() => {
  vi.clearAllMocks();
  mockSnapshot();
  api.post.mockImplementation(async (_url, { catalog }) => ({
    revision: 1,
    catalog,
    chargers: 1,
    selected_sensors: 1,
    sampled_rows_per_day_ceiling: 8640,
    original_rate_sensors: 0,
    affected_monitors: [],
  }));
  api.put.mockImplementation(async (_url, { catalog }) => ({
    ...snapshot(catalog),
    revision: 2,
  }));
});
afterEach(() => vi.restoreAllMocks());

const openBroker = async (name = "Main broker") => {
  const button = screen.queryByRole("button", {
    name: `Show chargers for ${name}`,
  });
  if (button) fireEvent.click(button);
  else await screen.findByRole("button", { name: `Hide chargers for ${name}` });
};
const openCharger = async (name = "Yard") => {
  await screen.findByRole("button", { name: /chargers for Main broker/ });
  await openBroker();
  const button = screen.queryByRole("button", {
    name: `Show measurements for ${name}`,
  });
  if (button) fireEvent.click(button);
  return within(screen.getByRole("region", { name: `Charger ${name}` }));
};
const edit = (
  label: string,
  value: string,
  scope: ReturnType<typeof within> = screen,
) => {
  fireEvent.click(
    scope.getByRole("button", { name: new RegExp(`^Edit ${label}:`) }),
  );
  const input = scope.getByLabelText(label);
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: "Enter" });
};
const setRate = (
  charger: string,
  sensor: string,
  mode: string,
  interval?: string,
) => {
  const label = `Collection for ${charger} · ${sensor}`;
  fireEvent.change(screen.getByLabelText(label), { target: { value: mode } });
  if (interval !== undefined)
    fireEvent.change(screen.getByLabelText(`${label} interval in seconds`), {
      target: { value: interval },
    });
};
const save = async () => {
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
  return api.put.mock.calls[0]![1].catalog as Catalog;
};

describe("direct collection editor", () => {
  it("starts brokers and measurements collapsed, with metadata visible and editable", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    const expand = await screen.findByRole("button", {
      name: "Show chargers for Main broker",
    });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    expect(
      screen.getByRole("button", { name: "Edit Hostname: main.ts.net" }),
    ).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Charger Yard" })).toBeNull();
    edit(
      "Broker name",
      "Renamed",
      within(screen.getByRole("region", { name: "Broker Main broker" })),
    );
    expect(
      screen
        .getByRole("button", { name: "Show chargers for Renamed" })
        .getAttribute("aria-expanded"),
    ).toBe("false");
    await openBroker("Renamed");
    const yard = within(screen.getByRole("region", { name: "Charger Yard" }));
    expect(
      yard.getByRole("button", { name: "Edit Local charger ID: 0" }),
    ).toBeTruthy();
    expect(yard.queryByRole("combobox", { name: /Collection for/ })).toBeNull();
    fireEvent.click(
      yard.getByRole("button", { name: "Show measurements for Yard" }),
    );
    expect(
      yard.getAllByRole("combobox", { name: /Collection for/ }),
    ).toHaveLength(3);
    expect(screen.queryByText("Broker settings")).toBeNull();
    expect(screen.queryByText("Charger settings")).toBeNull();
    expect(screen.queryByText("Live diagnostics")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Configure/ })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancels inline edits with Escape and keeps the row collapsed", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    const button = await screen.findByRole("button", {
      name: "Edit Broker name: Main broker",
    });
    fireEvent.click(button);
    const input = screen.getByLabelText("Broker name");
    fireEvent.change(input, { target: { value: "Changed" } });
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Edit Broker name: Main broker" }),
      ),
    );
    expect(screen.queryAllByText("Unsaved changes")).toHaveLength(0);
    expect(
      screen.getByRole("button", { name: "Show chargers for Main broker" }),
    ).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
  });

  it.each(["Hostname", "Port"])(
    "cancels %s edits without changing broker evidence",
    async (label) => {
      mockSnapshot(snapshot(inventory()));
      show();
      await screen.findByRole("region", { name: "Broker Main broker" });
      const broker = within(
        screen.getByRole("region", { name: "Broker Main broker" }),
      );
      fireEvent.click(
        broker.getByRole("button", { name: new RegExp(`^Edit ${label}:`) }),
      );
      const input = broker.getByLabelText(label);
      fireEvent.change(input, {
        target: { value: label === "Port" ? "1884" : "other.ts.net" },
      });
      fireEvent.keyDown(input, { key: "Escape" });
      expect(broker.getByText("· Observed")).toBeTruthy();
      expect(screen.queryAllByText("Unsaved changes")).toHaveLength(0);
    },
  );

  it.each(["charger", "broker"])(
    "removes a %s through its actions, with confirmation at Save",
    async (entity) => {
      mockSnapshot(snapshot(inventory()));
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      show();
      await openCharger();
      fireEvent.keyDown(
        screen.getByRole("button", {
          name:
            entity === "charger"
              ? "Actions for charger Yard"
              : "Actions for broker Main broker",
        }),
        { key: "Enter" },
      );
      fireEvent.click(
        await screen.findByRole("menuitem", {
          name: entity === "charger" ? "Remove charger" : "Remove broker",
        }),
      );
      expect(confirm).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
      expect(confirm.mock.calls[0]![0]).toContain(
        entity === "charger" ? "Charger Yard" : "Broker Main broker",
      );
      expect(api.put).not.toHaveBeenCalled();
    },
  );

  it("builds a broker, charger and measurement without a configuration file", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Add broker" }));
    edit("Hostname", "charger.ts.net");
    fireEvent.click(screen.getByRole("button", { name: "Add charger" }));
    edit("Charger name", "Yard charger");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Show measurements for Yard charger",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Add measurement" }));
    const dialog = within(
      screen.getByRole("dialog", { name: "Measurement details" }),
    );
    fireEvent.change(dialog.getByLabelText("Sensor key"), {
      target: { value: "temperature" },
    });
    fireEvent.change(dialog.getByLabelText("Upstream topic"), {
      target: { value: "device/evCharger/0/temperature" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Close" }));
    edit("Name for temperature", "Temperature");
    setRate("Yard charger", "Temperature", "sample", "30");
    const catalog = await save();
    expect(catalog.sources[0]?.host).toBe("charger.ts.net");
    const charger = catalog.sources[0]!.chargers[0]!;
    expect(charger.label).toBe("Yard charger");
    expect(charger.policy?.mode).toBe("off");
    expect(charger.sensors[0]?.upstream_topic).toBe(
      "device/evCharger/0/temperature",
    );
    expect(charger.sensors[0]?.policy).toEqual({
      mode: "sample",
      interval_seconds: 30,
    });
  });

  it("saves different rates directly on one charger without changing other streams", async () => {
    const original = inventory();
    original.sources[0]!.chargers[0]!.policy = null;
    mockSnapshot(snapshot(original));
    show();
    await openCharger();
    setRate("Yard", "Temperature", "sample", "60");
    setRate("Yard", "AC current", "original");
    setRate("Yard", "Connected", "off");
    expect(screen.getByText(/2\/3 enabled · Mixed rates/)).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
    const next = await save();
    const yard = next.sources[0]!.chargers[0]!;
    expect(
      yard.sensors.map((sensor) => effectivePolicy(next, yard, sensor)),
    ).toEqual([
      { mode: "sample", interval_seconds: 60 },
      { mode: "original", interval_seconds: 10 },
      { mode: "off", interval_seconds: 10 },
    ]);
    expect(next.sources[0]!.chargers[1]).toEqual(
      original.sources[0]!.chargers[1],
    );
    expect(next.sources[1]).toEqual(original.sources[1]);
    expect(api.put.mock.calls[0]![1].pause_affected_monitors).toBe(false);
  });

  it("keeps existing mixed and inherited policies when changing only metadata", async () => {
    const original = inventory();
    original.sources[0]!.chargers[0]!.policy = {
      mode: "sample",
      interval_seconds: 15,
    };
    original.sources[0]!.chargers[0]!.sensors[0]!.policy = {
      mode: "original",
      interval_seconds: 10,
    };
    mockSnapshot(snapshot(original));
    show();
    const yard = await openCharger();
    expect(
      screen
        .getByLabelText("Collection for Yard · Temperature")
        .getAttribute("disabled"),
    ).toBeNull();
    expect(
      (
        screen.getByLabelText(
          "Collection for Yard · AC current interval in seconds",
        ) as HTMLInputElement
      ).value,
    ).toBe("15");
    edit("Charger name", "Yard renamed", yard);
    const next = await save();
    expect(next.sources[0]!.chargers[0]).toEqual({
      ...original.sources[0]!.chargers[0],
      label: "Yard renamed",
    });
  });

  it("filters categories without changing collection, then applies only to selected measurements", async () => {
    const original = inventory();
    mockSnapshot(snapshot(original));
    show();
    await openCharger();
    fireEvent.change(screen.getByRole("combobox", { name: "Category" }), {
      target: { value: "Thermal" },
    });
    expect(
      screen.queryByLabelText("Collection for Yard · AC current"),
    ).toBeNull();
    expect(screen.queryAllByText("Unsaved changes")).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Select 2 measurements" }),
    );
    fireEvent.change(
      screen.getByLabelText(
        "Collection for selected measurements interval in seconds",
      ),
      { target: { value: "60" } },
    );
    expect(screen.queryAllByText("Unsaved changes")).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Apply to 2 measurements" }),
    );
    const next = await save();
    for (const charger of next.sources[0]!.chargers) {
      expect(
        charger.sensors.map(
          (sensor) => effectivePolicy(next, charger, sensor).mode,
        ),
      ).toEqual(["sample", "off", "off"]);
      expect(charger.sensors[0]!.policy?.interval_seconds).toBe(60);
    }
  });

  it("clears selection when filtering and never edits hidden measurements", async () => {
    const original = inventory();
    mockSnapshot(snapshot(original));
    show();
    await openCharger();
    fireEvent.click(
      screen.getByRole("button", { name: "Select 6 measurements" }),
    );
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search catalog" }),
      { target: { value: "temperature" } },
    );
    expect(screen.queryByRole("button", { name: /^Apply to/ })).toBeNull();
    expect(screen.getAllByRole("group", { name: /Measurement / })).toHaveLength(
      1,
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select Yard · Temperature" }),
    );
    fireEvent.change(
      screen.getByLabelText("Collection for selected measurements"),
      { target: { value: "original" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Apply to 1 measurement" }),
    );
    const next = await save();
    expect(next.sources[0]!.chargers[0]!.sensors[0]!.policy?.mode).toBe(
      "original",
    );
    expect(next.sources[0]!.chargers[0]!.sensors.slice(1)).toEqual(
      original.sources[0]!.chargers[0]!.sensors.slice(1),
    );
    expect(next.sources[0]!.chargers[1]).toEqual(
      original.sources[0]!.chargers[1],
    );
  });

  it("selects all measurements for one charger and can turn off explicit overrides", async () => {
    const original = inventory();
    original.sources[0]!.chargers[0]!.policy = null;
    original.sources[0]!.chargers[0]!.sensors[0]!.policy = {
      mode: "original",
      interval_seconds: 10,
    };
    mockSnapshot(snapshot(original));
    show();
    await openCharger();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select measurements for Yard" }),
    );
    fireEvent.change(
      screen.getByLabelText("Collection for selected measurements"),
      { target: { value: "off" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Apply to 3 measurements" }),
    );
    const next = await save();
    const yard = next.sources[0]!.chargers[0]!;
    expect(
      yard.sensors.every(
        (sensor) => effectivePolicy(next, yard, sensor).mode === "off",
      ),
    ).toBe(true);
    expect(next.sources[0]!.chargers[1]).toEqual(
      original.sources[0]!.chargers[1],
    );
  });

  it.each(["", "0", "-1", "1.5", "3601"])(
    "blocks invalid individual intervals (%s), even after collapsing",
    async (value) => {
      mockSnapshot(snapshot(inventory()));
      show();
      await openCharger();
      setRate("Yard", "Temperature", "sample", value);
      expect(
        (
          screen.getByRole("button", {
            name: "Save changes",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true);
      fireEvent.click(
        screen.getByRole("button", { name: "Hide measurements for Yard" }),
      );
      expect(screen.getByRole("alert").textContent).toContain("whole seconds");
      await openCharger();
      setRate("Yard", "Temperature", "original");
      const next = await save();
      expect(next.sources[0]!.chargers[0]!.sensors[0]!.policy).toEqual({
        mode: "original",
        interval_seconds: 10,
      });
    },
  );

  it("blocks invalid bulk intervals without corrupting the catalog", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await openCharger();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select measurements for Yard" }),
    );
    fireEvent.change(
      screen.getByLabelText(
        "Collection for selected measurements interval in seconds",
      ),
      { target: { value: "1.5" } },
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Apply to 3 measurements",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(screen.queryAllByText("Unsaved changes")).toHaveLength(0);
  });

  it("allows read-only users to inspect metadata and rates", async () => {
    mockSnapshot(snapshot(inventory(), false));
    show();
    const yard = await openCharger();
    expect(
      (
        yard.getByRole("button", {
          name: "View Charger name: Yard",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen.getByLabelText(
          "Collection for Yard · Temperature",
        ) as HTMLSelectElement
      ).disabled,
    ).toBe(true);
    expect(
      (screen.getByLabelText("Select Yard · Temperature") as HTMLInputElement)
        .disabled,
    ).toBe(true);
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Details for Yard · Temperature" }),
    );
    expect(
      screen.getByLabelText("Sensor key").closest("fieldset")?.disabled,
    ).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("returns keyboard focus after closing measurement details", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await openCharger();
    const button = screen.getByRole("button", {
      name: "Details for Yard · Temperature",
    });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(document.activeElement).toBe(button));
  });

  it("preserves unsaved rates when collapsing and reopening a broker", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await openCharger();
    setRate("Yard", "Temperature", "sample", "120");
    fireEvent.click(
      screen.getByRole("button", { name: "Hide chargers for Main broker" }),
    );
    await openCharger();
    expect(
      (
        screen.getByLabelText(
          "Collection for Yard · Temperature interval in seconds",
        ) as HTMLInputElement
      ).value,
    ).toBe("120");
    expect(api.put).not.toHaveBeenCalled();
  });

  it.each(["link", "back"])(
    "protects unsaved inline edits during %s navigation",
    async (action) => {
      mockSnapshot(snapshot(inventory()));
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      const { router } = show();
      await screen.findByRole("button", {
        name: "Edit Broker name: Main broker",
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Edit Broker name: Main broker" }),
      );
      fireEvent.change(screen.getByLabelText("Broker name"), {
        target: { value: "Edited" },
      });
      const leave = () =>
        action === "back" ? router.navigate(-1) : router.navigate("/away");
      await act(leave);
      expect(confirm).toHaveBeenCalledWith(
        "Leave this page and discard your unsaved changes?",
      );
      expect(router.state.location.pathname).toBe("/sources");
      confirm.mockReturnValue(true);
      await act(leave);
      expect(await screen.findByText("Another page")).toBeTruthy();
      expect(api.put).not.toHaveBeenCalled();
    },
  );

  it("guards reload and discard, but allows same-page navigation", async () => {
    mockSnapshot(snapshot(inventory()));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { router } = show();
    await openCharger();
    setRate("Yard", "Temperature", "original");
    await act(() => router.navigate("/sources?view=collection"));
    expect(confirm).not.toHaveBeenCalled();
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getAllByText("Unsaved changes").length).toBeGreaterThan(0);
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    await screen.findByRole("button", { name: "Reload saved catalog" });
    const cleanUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanUnload);
    expect(cleanUnload.defaultPrevented).toBe(false);
  });

  it("blocks stale inline and measurement edits when another administrator saves", async () => {
    const intervals = vi.spyOn(globalThis, "setInterval");
    mockSnapshot(snapshot(inventory()));
    show();
    await openCharger();
    setRate("Yard", "Temperature", "original");
    fireEvent.click(
      screen.getByRole("button", { name: "Details for Yard · Temperature" }),
    );
    const refresh = intervals.mock.calls.find(
      ([, delay]) => delay === 3000,
    )![0] as () => Promise<void>;
    api.get.mockResolvedValue({ ...snapshot(inventory()), revision: 2 });
    await act(refresh);
    expect(
      screen.getByLabelText("Sensor key").closest("fieldset")?.disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("alert").textContent).toContain(
      "Someone saved a newer catalog",
    );
    expect(
      (
        screen.getByLabelText(
          "Collection for Yard · Temperature",
        ) as HTMLSelectElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: "Save changes",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(api.put).not.toHaveBeenCalled();
  });

  it("keeps a filtered broker focused when its hostname changes the evidence", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", { name: "Edit Hostname: main.ts.net" });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Broker evidence" }),
      { target: { value: "observed" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Edit Hostname: main.ts.net" }),
    );
    const input = screen.getByLabelText("Hostname");
    fireEvent.change(input, { target: { value: "new.ts.net" } });
    expect(document.activeElement).toBe(input);
    expect(
      (
        screen.getByRole("combobox", {
          name: "Broker evidence",
        }) as HTMLSelectElement
      ).value,
    ).toBe("all");
    const next = await save();
    expect(next.sources[0]!.host).toBe("new.ts.net");
    expect(next.sources[0]!.verified).toBe(false);
    expect(next.sources).toHaveLength(2);
  });

  it("rewrites charger topic prefixes when the local ID is edited", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    const yard = await openCharger();
    edit("Local charger ID", "west", yard);
    const next = await save();
    expect(
      next.sources[0]!.chargers[0]!.sensors.every((sensor) =>
        sensor.upstream_topic.startsWith("device/evCharger/west/"),
      ),
    ).toBe(true);
  });

  it("clears filters for newly added brokers and loads a paused inventory", async () => {
    const get = api.get.getMockImplementation()!;
    api.get.mockImplementation(async (url) =>
      url.endsWith("ambibox-template") ? inventory() : get(url),
    );
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Load AmbiBox inventory" }),
    );
    await openCharger();
    expect(
      (
        screen.getByLabelText(
          "Collection for Yard · Temperature",
        ) as HTMLSelectElement
      ).value,
    ).toBe("off");
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search catalog" }),
      { target: { value: "missing" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Add broker" }));
    expect(
      (
        screen.getByRole("searchbox", {
          name: "Search catalog",
        }) as HTMLInputElement
      ).value,
    ).toBe("");
    expect(
      screen.getByRole("button", { name: "Edit Hostname: Add hostname" }),
    ).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("copies definitions with collection off and leaves other chargers unchanged", async () => {
    const original = inventory();
    original.sources[0]!.chargers[0]!.policy = {
      mode: "original",
      interval_seconds: 10,
    };
    mockSnapshot(snapshot(original));
    show();
    await openCharger();
    fireEvent.change(screen.getByLabelText("Copy measurements to Yard"), {
      target: { value: "charger-1" },
    });
    const next = await save();
    const yard = next.sources[0]!.chargers[0]!;
    expect(
      yard.sensors.every(
        (sensor) => effectivePolicy(next, yard, sensor).mode === "off",
      ),
    ).toBe(true);
    expect(
      yard.sensors.every((sensor) =>
        sensor.upstream_topic.startsWith("device/evCharger/0/"),
      ),
    ).toBe(true);
    expect(next.sources[0]!.chargers[1]).toEqual(
      original.sources[0]!.chargers[1],
    );
  });

  it("confirms removals and affected monitors only on Save and retains a cancelled draft", async () => {
    mockSnapshot(snapshot(inventory()));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const preview = api.post.getMockImplementation()!;
    api.post.mockImplementation(async (...args) => ({
      ...(await preview(...args)),
      affected_monitors: [{ id: "monitor-1", name: "Yard temperature" }],
    }));
    show();
    await openCharger();
    fireEvent.click(
      screen.getByRole("button", { name: "Details for Yard · Temperature" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Remove measurement" }));
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(confirm.mock.calls[0]![0]).toContain("Yard · Temperature");
    expect(confirm.mock.calls[0]![0]).toContain("fresh calibration");
    expect(api.put).not.toHaveBeenCalled();
    expect(
      screen.queryByLabelText("Collection for Yard · Temperature"),
    ).toBeNull();
    confirm.mockReturnValue(true);
    await save();
    expect(api.put.mock.calls[0]![1].pause_affected_monitors).toBe(true);
  });

  it("validates imports before changing the draft and preserves the catalog on failure", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", {
      name: "Show chargers for Main broker",
    });
    api.post.mockRejectedValueOnce(new Error("Sensor keys must be unique"));
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: {
        files: [
          { size: 100, text: async () => JSON.stringify({ sources: [] }) },
        ],
      },
    });
    expect((await screen.findByRole("alert")).textContent).toContain(
      "must be unique",
    );
    expect(
      screen.getByRole("button", { name: "Show chargers for Main broker" }),
    ).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: {
        files: [{ size: 100, text: async () => JSON.stringify(empty) }],
      },
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Show chargers for Main broker" }),
      ).toBeNull(),
    );
    expect(api.put).not.toHaveBeenCalled();
  });

  it("keeps edits after failed saves and revalidates them on retry", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await openCharger();
    setRate("Yard", "Temperature", "sample", "60");
    api.put.mockRejectedValueOnce(new Error("Database unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Database unavailable",
    );
    expect(
      (
        screen.getByLabelText(
          "Collection for Yard · Temperature interval in seconds",
        ) as HTMLInputElement
      ).value,
    ).toBe("60");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Changes saved"),
    );
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(api.put).toHaveBeenCalledTimes(2);
  });

  it("clears recovered status errors without hiding a validation error", async () => {
    const intervals = vi.spyOn(globalThis, "setInterval");
    mockSnapshot(snapshot(inventory()));
    show();
    await openCharger();
    const refresh = intervals.mock.calls.find(
      ([, delay]) => delay === 3000,
    )![0] as () => Promise<void>;
    api.get.mockRejectedValueOnce(new Error("Network lost"));
    await act(refresh);
    expect(screen.getByRole("alert").textContent).toContain("Network lost");
    await act(refresh);
    expect(screen.queryByRole("alert")).toBeNull();
    setRate("Yard", "Temperature", "original");
    api.post.mockRejectedValueOnce(new Error("Invalid catalog"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("alert");
    await act(refresh);
    expect(screen.getByRole("alert").textContent).toContain("Invalid catalog");
  });

  it("distinguishes saving from worker acknowledgement and application failure", async () => {
    const intervals = vi.spyOn(globalThis, "setInterval");
    const original = snapshot(inventory());
    const state = (revision: number) => ({
      revision,
      status: "applied",
      checked_at: new Date().toISOString(),
    });
    original.collection = state(1);
    original.ingress = state(1);
    mockSnapshot(original);
    api.put.mockImplementation(async (_url, { catalog }) => ({
      ...original,
      catalog,
      revision: 2,
    }));
    show();
    await openCharger();
    const refresh = intervals.mock.calls.find(
      ([, delay]) => delay === 3000,
    )![0] as () => Promise<void>;
    setRate("Yard", "Temperature", "original");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Saved · Applying changes…")).toBeTruthy();
    api.get.mockResolvedValue({
      revision: 2,
      collection: state(2),
      ingress: state(1),
    });
    await act(refresh);
    expect(screen.queryByText("Changes applied")).toBeNull();
    api.get.mockResolvedValue({
      revision: 2,
      collection: state(2),
      ingress: state(2),
    });
    await act(refresh);
    expect(screen.getByText("Changes applied")).toBeTruthy();
    api.get.mockResolvedValue({
      revision: 2,
      collection: {
        ...state(2),
        status: "error",
        error: "Collector unavailable",
      },
      ingress: state(2),
    });
    await act(refresh);
    expect(
      screen.getByText("Saved · Changes could not be applied"),
    ).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain(
      "Collector unavailable",
    );
  });
});


describe("sensor activity evidence", () => {
  const activitySnapshot = (canEdit = true) => {
    const data = snapshot(inventory(), canEdit);
    data.catalog.sources[0]!.chargers[0]!.policy = null;
    const state = {
      revision: 1,
      status: "applied",
      checked_at: new Date(Date.now()).toISOString(),
    };
    data.collection = state;
    data.ingress = {
      ...state,
      sources: { "broker-1": { status: "connected" } },
    };
    data.sensor_activity = {
      "charger-0": {
        temperature: {
          received_at: new Date(Date.now() - 3000).toISOString(),
          is_snapshot: false,
        },
        current: {
          received_at: new Date(Date.now()).toISOString(),
          is_snapshot: true,
        },
      },
    };
    return data;
  };

  it("shows member-visible evidence for individual sensors, not broker discovery", async () => {
    const data = activitySnapshot(false);
    mockSnapshot(data);
    show();
    const yard = await openCharger();
    const temperature = within(yard.getByRole("group", { name: "Measurement Temperature" }));
    expect(temperature.getByText("Recent data")).toBeTruthy();
    expect(temperature.getByText(/^Last received/).getAttribute("datetime")).toBe(
      data.sensor_activity["charger-0"]!.temperature!.received_at,
    );
    expect(within(yard.getByRole("group", { name: "Measurement AC current" })).getByText("Retained snapshot")).toBeTruthy();
    expect(within(yard.getByRole("group", { name: "Measurement Connected" })).getByText("No data yet")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show measurements for Garage" }));
    expect(within(screen.getByRole("region", { name: "Charger Garage" })).getAllByText("Collection off")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
  });

  it.each([
    { interval: 10, age: 61000, label: "No recent data" },
    { interval: 600, age: 900000, label: "Recent data" },
    { interval: 10, age: -60000, label: "No recent data" },
  ])("uses saved sampling cadence ($interval seconds) and receipt age ($age milliseconds)", async ({ interval, age, label }) => {
    const data = activitySnapshot();
    data.catalog.sources[0]!.chargers[0]!.policy = {
      mode: "sample", interval_seconds: interval,
    };
    data.sensor_activity["charger-0"]!.temperature!.received_at =
      new Date(Date.now() - age).toISOString();
    mockSnapshot(data);
    show();
    const yard = await openCharger();
    expect(within(yard.getByRole("group", { name: "Measurement Temperature" })).getByText(label)).toBeTruthy();
  });

  it("refreshes evidence without changing an unsaved collection policy and handles failures", async () => {
    const intervals = vi.spyOn(globalThis, "setInterval");
    const data = activitySnapshot();
    mockSnapshot(data);
    show();
    const yard = await openCharger();
    const temperature = within(yard.getByRole("group", { name: "Measurement Temperature" }));
    setRate("Yard", "Temperature", "off");
    expect(temperature.getByText("Recent data")).toBeTruthy();
    const refresh = intervals.mock.calls.find(([, delay]) => delay === 3000)![0] as () => Promise<void>;
    api.get.mockResolvedValue({ ...data, sensor_activity: {} });
    await act(refresh);
    expect(temperature.getByText("No data yet")).toBeTruthy();
    expect((screen.getByLabelText("Collection for Yard · Temperature") as HTMLSelectElement).value).toBe("off");
    api.get.mockRejectedValueOnce(new Error("Network lost"));
    await act(refresh);
    expect(temperature.getByText("Status unavailable")).toBeTruthy();
    api.get.mockResolvedValue(data);
    await act(refresh);
    expect(temperature.getByText("Recent data")).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("expires live evidence while status requests are still pending", async () => {
    const intervals = vi.spyOn(globalThis, "setInterval");
    const data = activitySnapshot();
    const now = Date.now();
    mockSnapshot(data);
    show();
    const yard = await openCharger();
    const temperature = within(yard.getByRole("group", { name: "Measurement Temperature" }));
    expect(temperature.getByText("Recent data")).toBeTruthy();
    api.get.mockImplementation(() => new Promise(() => {}));
    vi.spyOn(Date, "now").mockReturnValue(now + 18000);
    const refresh = intervals.mock.calls.find(([, delay]) => delay === 3000)![0] as () => Promise<void>;
    await act(refresh);
    expect(temperature.getByText("Status unavailable")).toBeTruthy();
  });

  it.each(["broker", "charger", "topic", "type"])(
    "does not certify an unsaved %s binding with another stream's data", async (binding) => {
      mockSnapshot(activitySnapshot());
      show();
      const yard = await openCharger();
      if (binding === "broker") {
        edit("Hostname", "other.ts.net", within(
          screen.getByRole("region", { name: "Broker Main broker" }),
        ));
      }
      else if (binding === "charger") edit("Local charger ID", "other", yard);
      else {
        fireEvent.click(screen.getByRole("button", { name: "Details for Yard · Temperature" }));
        fireEvent.change(screen.getByLabelText(binding === "topic" ? "Upstream topic" : "Value type"), {
          target: { value: binding === "topic" ? "device/evCharger/0/replacement" : "text" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Close" }));
      }
      expect(within(yard.getByRole("group", { name: "Measurement Temperature" })).getByText("Save to observe")).toBeTruthy();
      expect(yard.queryByText("Recent data")).toBeNull();
      expect(api.put).not.toHaveBeenCalled();
    },
  );
});
