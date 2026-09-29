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

describe("catalog collection UI", () => {
  it("keeps data sources focused on collection configuration", async () => {
    const catalog = inventory();
    catalog.sources[0]!.chargers[1]!.policy = {
      mode: "original",
      interval_seconds: 10,
    };
    mockSnapshot(snapshot(catalog));
    show();
    await screen.findByRole("button", { name: "Configure Yard" });
    expect(screen.getAllByText("Off")).toHaveLength(3);
    expect(screen.getByText("3 of 3 measurements enabled")).toBeTruthy();
    fireEvent.click(
      screen.getByText("Live diagnostics", { selector: "summary" }),
    );
    expect(screen.queryByText("Storage and retention")).toBeNull();
    expect(api.get).not.toHaveBeenCalledWith("/v1/sources/storage");
    expect(screen.queryByRole("link", { name: "View telemetry" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Latest values" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Pause selected" })).toBeNull();
  });

  it("builds a broker, charger and sensor without a configuration file", async () => {
    show();
    await screen.findByRole("button", { name: "Add broker" });
    fireEvent.click(screen.getByRole("button", { name: "Add broker" }));
    const host = screen.getByLabelText("Hostname");
    fireEvent.change(host, { target: { value: "charger.ts.net" } });
    expect(host.closest("details")?.open).toBe(true);
    fireEvent.change(screen.getByLabelText("Charger name"), {
      target: { value: "Yard charger" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add sensor" }));
    fireEvent.click(screen.getByText("New sensor").closest("summary")!);
    fireEvent.change(screen.getByLabelText("Sensor key"), {
      target: { value: "temperature" },
    });
    fireEvent.change(screen.getByLabelText("Upstream topic"), {
      target: { value: "device/evCharger/0/temperature" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const catalog = api.put.mock.calls[0]?.[1].catalog as Catalog;
    expect(catalog.sources[0]?.host).toBe("charger.ts.net");
    const charger = catalog.sources[0]?.chargers[0];
    expect(charger?.label).toBe("Yard charger");
    expect(charger?.policy?.mode).toBe("off");
    expect(charger?.sensors[0]?.upstream_topic).toBe(
      "device/evCharger/0/temperature",
    );
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("validates imports without saving, and confirms affected monitors only on Save", async () => {
    const catalog = inventory();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const preview = api.post.getMockImplementation()!;
    api.post.mockImplementation(async (...args) => ({
      ...(await preview(...args)),
      affected_monitors: [{ id: "monitor-1", name: "Yard temperature" }],
    }));
    show();
    await screen.findByRole("button", { name: "Add broker" });
    const file = { size: 1024, text: async () => JSON.stringify(catalog) };
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });
    await screen.findByRole("button", { name: "Configure Yard" });
    expect(api.put).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(confirm.mock.calls[0]![0]).toContain("Yard temperature");
    expect(confirm.mock.calls[0]![0]).toContain("fresh calibration");
    expect(api.put).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/v1/sources", {
        expected_revision: 1,
        catalog,
        pause_affected_monitors: true,
      }),
    );
  });

  it("makes catalog editing unavailable for ordinary users", async () => {
    mockSnapshot(snapshot(inventory(), false));
    show();
    await screen.findByRole("button", { name: "Add broker" });
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    fireEvent.click(
      screen.getByText("Import and history", { selector: "summary" }),
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Import catalog",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Add broker" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.change(
      screen.getByRole("combobox", { name: "Broker evidence" }),
      {
        target: { value: "candidate" },
      },
    );
    expect(screen.getAllByLabelText("Hostname")).toHaveLength(1);
    expect(api.post).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
  });
  it("clears selection on filtering and changes only the explicitly selected chargers", async () => {
    const original = inventory();
    mockSnapshot(snapshot(original));
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Select shown chargers" }),
    );
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search catalog" }),
      { target: { value: "Yard" } },
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Configure selected",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(
      screen.getByRole("button", { name: "Select shown chargers" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure selected" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const draft = api.put.mock.calls[0]![1].catalog as Catalog;
    const [yard, garage] = draft.sources[0]!.chargers;
    expect(
      yard!.sensors.map((sensor) => effectivePolicy(draft, yard!, sensor).mode),
    ).toEqual(["sample", "off", "off"]);
    expect(garage).toEqual(original.sources[0]!.chargers[1]);
    expect(draft.sources[1]).toEqual(original.sources[1]);
    expect(api.put).toHaveBeenCalledTimes(1);
  });

  it("edits a filtered charger by identity without deleting hidden definitions", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", { name: "Add broker" });
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search catalog" }),
      {
        target: { value: "Garage" },
      },
    );
    fireEvent.change(screen.getByLabelText("Charger name"), {
      target: { value: "Garage renamed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const draft = api.put.mock.calls[0]![1].catalog as Catalog;
    expect(draft.sources[0]!.chargers.map((charger) => charger.label)).toEqual([
      "Yard",
      "Garage renamed",
    ]);
    expect(draft.sources[1]!.host).toBe("candidate.ts.net");
  });

  it("filters candidate hosts and clears filters when adding a broker", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", { name: "Add broker" });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Broker evidence" }),
      {
        target: { value: "candidate" },
      },
    );
    expect(screen.getByLabelText("Hostname").getAttribute("value")).toBe(
      "candidate.ts.net",
    );
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search catalog" }),
      {
        target: { value: "no match" },
      },
    );
    expect(screen.getByText(/No matching hosts or chargers/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add broker" }));
    expect(
      (
        screen.getByRole("searchbox", {
          name: "Search catalog",
        }) as HTMLInputElement
      ).value,
    ).toBe("");
    expect(screen.getAllByLabelText("Hostname")).toHaveLength(3);
  });
  it("keeps a filtered broker mounted and focused when editing changes its evidence", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", { name: "Add broker" });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Broker evidence" }),
      {
        target: { value: "observed" },
      },
    );
    const host = screen.getByLabelText("Hostname");
    host.focus();
    fireEvent.change(host, { target: { value: "n" } });
    expect(
      (
        screen.getByRole("combobox", {
          name: "Broker evidence",
        }) as HTMLSelectElement
      ).value,
    ).toBe("all");
    expect(screen.getAllByLabelText("Hostname")).toContain(host);
    expect(document.activeElement).toBe(host);
    fireEvent.change(host, { target: { value: "new.ts.net" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const source = (api.put.mock.calls[0]![1].catalog as Catalog).sources[0]!;
    expect(source.host).toBe("new.ts.net");
    expect(source.verified).toBe(false);
  });
  it("preserves charger selection and unsaved measurement rates when reopening configuration", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(
      await screen.findByRole("checkbox", { name: "Select Yard for editing" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure selected" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.change(screen.getByLabelText("Collection interval in seconds"), {
      target: { value: "60" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(
      (
        screen.getByRole("checkbox", {
          name: "Select Yard for editing",
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Configure selected" }));
    expect(
      (
        screen.getByRole("checkbox", {
          name: "Thermal measurements",
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);
    expect(
      (
        screen.getByLabelText(
          "Rate for Yard Temperature interval in seconds",
        ) as HTMLInputElement
      ).value,
    ).toBe("60");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Latest every 60s")).toBeTruthy();
  });

  it.each(["Thermal", "Current", "Status"])(
    "selects only %s and persists it with Save changes",
    async (category) => {
      mockSnapshot(snapshot(inventory()));
      show();
      fireEvent.click(
        await screen.findByRole("button", { name: "Select shown chargers" }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Configure selected" }),
      );
      fireEvent.click(
        screen.getByRole("checkbox", { name: `${category} measurements` }),
      );
      expect(screen.getByText("2 of 6 measurements selected")).toBeTruthy();
      for (const other of ["Thermal", "Current", "Status"].filter(
        (value) => value !== category,
      )) {
        expect(
          (
            screen.getByRole("checkbox", {
              name: `${other} measurements`,
            }) as HTMLInputElement
          ).checked,
        ).toBe(false);
      }
      expect(api.post).not.toHaveBeenCalled();
      expect(api.put).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      expect(api.put).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
      const draft = api.put.mock.calls[0]![1].catalog as Catalog;
      for (const charger of draft.sources[0]!.chargers) {
        for (const sensor of charger.sensors)
          expect(effectivePolicy(draft, charger, sensor).mode).toBe(
            sensor.category === category ? "sample" : "off",
          );
      }
    },
  );

  it("turns off inherited and explicit policies when replacing all categories with temperature only", async () => {
    const catalog = inventory();
    const yard = catalog.sources[0]!.chargers[0]!;
    yard.policy = null;
    yard.sensors[1]!.policy = { mode: "original", interval_seconds: 10 };
    mockSnapshot(snapshot(catalog));
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Configure Yard" }),
    );
    expect(screen.getByText("3 of 3 measurements selected")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear measurements" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const draft = api.put.mock.calls[0]![1].catalog as Catalog;
    const changed = draft.sources[0]!.chargers[0]!;
    expect(
      changed.sensors.map(
        (sensor) => effectivePolicy(draft, changed, sensor).mode,
      ),
    ).toEqual(["sample", "off", "off"]);
    expect(draft.sources[0]!.chargers[1]).toEqual(
      catalog.sources[0]!.chargers[1],
    );
  });

  it("cancels editor changes without changing the draft or publishing", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Configure Yard" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      (
        screen.getByRole("button", {
          name: "Save changes",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Configure Yard" }));
    expect(screen.getByText("0 of 3 measurements selected")).toBeTruthy();
    expect(api.post).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("preserves mixed rates and represents partial category selection accurately", async () => {
    const catalog = inventory();
    const yard = catalog.sources[0]!.chargers[0]!;
    yard.sensors[0]!.policy = { mode: "sample", interval_seconds: 60 };
    yard.sensors[1]!.policy = { mode: "original", interval_seconds: 10 };
    mockSnapshot(snapshot(catalog));
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Select shown chargers" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure selected" }));
    const thermal = screen.getByRole("checkbox", {
      name: "Thermal measurements",
    }) as HTMLInputElement;
    expect(thermal.indeterminate).toBe(true);
    fireEvent.click(thermal);
    expect(thermal.checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const draft = api.put.mock.calls[0]![1].catalog as Catalog;
    const [nextYard, garage] = draft.sources[0]!.chargers;
    expect(nextYard!.sensors[0]!.policy).toEqual(yard.sensors[0]!.policy);
    expect(nextYard!.sensors[1]!.policy).toEqual(yard.sensors[1]!.policy);
    expect(garage!.sensors[0]!.policy).toEqual({
      mode: "sample",
      interval_seconds: 10,
    });
    expect(garage!.sensors[1]!.policy).toBeNull();
  });

  it.each(["", "0", "-1", "1.5", "3601"])(
    "rejects invalid sampling interval '%s' before staging",
    async (value) => {
      mockSnapshot(snapshot(inventory()));
      show();
      fireEvent.click(
        await screen.findByRole("button", { name: "Configure Yard" }),
      );
      fireEvent.click(
        screen.getByRole("checkbox", { name: "Thermal measurements" }),
      );
      fireEvent.change(
        screen.getByLabelText("Collection interval in seconds"),
        { target: { value } },
      );
      expect(
        (
          screen.getByRole("button", {
            name: "Done",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true);
      expect(screen.getByRole("alert").textContent).toContain("whole seconds");
      expect(api.put).not.toHaveBeenCalled();
    },
  );

  it("keeps unsaved changes after a failed save and revalidates on retry", async () => {
    api.put.mockRejectedValueOnce(new Error("Database unavailable"));
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Configure Yard" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Database unavailable",
    );
    expect(screen.getAllByText("Unsaved changes").length).toBeGreaterThan(0);
    expect(toast.success).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(api.put.mock.calls[0]![1]).toEqual(api.put.mock.calls[1]![1]);
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Changes saved"),
    );
  });

  it.each(["shared", "individual"])(
    "switches an invalid %s interval to a valid original-rate policy",
    async (scope) => {
      mockSnapshot(snapshot(inventory()));
      show();
      fireEvent.click(
        await screen.findByRole("button", { name: "Configure Yard" }),
      );
      fireEvent.click(
        screen.getByRole("checkbox", { name: "Thermal measurements" }),
      );
      fireEvent.change(
        screen.getByLabelText("Collection interval in seconds"),
        { target: { value: "" } },
      );
      fireEvent.change(
        screen.getByLabelText(
          scope === "shared"
            ? "Collection frequency"
            : "Rate for Yard Temperature",
        ),
        { target: { value: "original" } },
      );
      expect(
        (
          screen.getByRole("button", {
            name: "Done",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
      const draft = api.put.mock.calls[0]![1].catalog as Catalog;
      expect(draft.sources[0]!.chargers[0]!.sensors[0]!.policy).toEqual({
        mode: "original",
        interval_seconds: 10,
      });
    },
  );

  it("lets read-only users inspect measurements without editing collection", async () => {
    mockSnapshot(snapshot(inventory(), false));
    show();
    const details = await screen.findByRole("button", {
      name: "View collection for Yard",
    });
    expect((details as HTMLButtonElement).disabled).toBe(false);
    expect(
      (
        screen.getByRole("checkbox", {
          name: "Select Yard for editing",
        }) as HTMLInputElement
      ).disabled,
    ).toBe(true);
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    fireEvent.click(details);
    expect(
      (
        screen.getByRole("checkbox", {
          name: "Thermal measurements",
        }) as HTMLInputElement
      ).closest("fieldset")?.disabled,
    ).toBe(true);
    expect(
      screen.getByText(/Saved collection settings · view only/),
    ).toBeTruthy();
  });

  it("returns keyboard focus after accepting or cancelling collection edits", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    const configure = await screen.findByRole("button", {
      name: "Configure Yard",
    });
    configure.focus();
    fireEvent.click(configure);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(document.activeElement).toBe(configure));
    fireEvent.click(configure);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(configure));
  });

  it.each(["link", "back"])(
    "protects an unsaved draft during %s navigation",
    async (action) => {
      mockSnapshot(snapshot(inventory()));
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      const { router } = show();
      fireEvent.click(
        await screen.findByRole("button", { name: "Configure Yard" }),
      );
      expect(
        within(screen.getByRole("dialog")).getByText("Yard", {
          selector: "strong",
        }),
      ).toBeTruthy();
      fireEvent.click(
        screen.getByRole("checkbox", { name: "Thermal measurements" }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      const leave = () =>
        action === "back" ? router.navigate(-1) : router.navigate("/away");
      await act(leave);
      expect(confirm).toHaveBeenCalledWith(
        "Leave this page and discard your unsaved changes?",
      );
      expect(router.state.location.pathname).toBe("/sources");
      expect(screen.getAllByText(/Unsaved changes/)[0]).toBeTruthy();
      confirm.mockReturnValue(true);
      await act(leave);
      expect(await screen.findByText("Another page")).toBeTruthy();
      expect(api.put).not.toHaveBeenCalled();
    },
  );

  it("keeps drafts without prompting for same-page navigation", async () => {
    mockSnapshot(snapshot(inventory()));
    const confirm = vi.spyOn(window, "confirm");
    const { router } = show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Configure Yard" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await act(() => router.navigate("/sources?view=collection"));
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.getAllByText(/Unsaved changes/)[0]).toBeTruthy();
  });

  it("loads the paused inventory directly from the empty collection page", async () => {
    const get = api.get.getMockImplementation()!;
    api.get.mockImplementation(async (url) =>
      url.endsWith("ambibox-template") ? inventory() : get(url),
    );
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Load AmbiBox inventory" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Configure Yard" }),
    );
    expect(screen.getByText("0 of 3 measurements selected")).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("turns off collection through the editor, including sensor overrides, without changing other chargers", async () => {
    const catalog = inventory();
    catalog.sources[0]!.chargers[0]!.policy = null;
    catalog.sources[0]!.chargers[0]!.sensors[0]!.policy = {
      mode: "original",
      interval_seconds: 10,
    };
    mockSnapshot(snapshot(catalog));
    show();
    fireEvent.click(
      await screen.findByRole("checkbox", { name: "Select Yard for editing" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure selected" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear measurements" }));
    expect(screen.getByText("0 of 3 measurements selected")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const next = api.put.mock.calls[0]![1].catalog as Catalog;
    expect(
      next.sources[0]!.chargers[0]!.sensors.every(
        (sensor) =>
          effectivePolicy(next, next.sources[0]!.chargers[0]!, sensor).mode ===
          "off",
      ),
    ).toBe(true);
    expect(next.sources[0]!.chargers[1]).toEqual(
      catalog.sources[0]!.chargers[1],
    );
    expect(api.put.mock.calls[0]![1].catalog).toEqual(next);
  });

  it("requires confirmation before discarding a draft and guards browser reloads", async () => {
    mockSnapshot(snapshot(inventory()));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Configure Yard" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getAllByText(/Unsaved changes/)[0]).toBeTruthy();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    await screen.findByRole("button", { name: "Reload saved catalog" });
    const cleanUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanUnload);
    expect(cleanUnload.defaultPrevented).toBe(false);
  });

  it.each(["editor", "catalog"])(
    "blocks stale edits in the %s when another administrator saves",
    async (panel) => {
      const intervals = vi.spyOn(globalThis, "setInterval");
      mockSnapshot(snapshot(inventory()));
      show();
      fireEvent.click(
        await screen.findByRole("button", { name: "Configure Yard" }),
      );
      fireEvent.click(
        screen.getByRole("checkbox", { name: "Thermal measurements" }),
      );
      if (panel === "catalog")
        fireEvent.click(screen.getByRole("button", { name: "Done" }));
      const refresh = intervals.mock.calls.find(
        ([, delay]) => delay === 3000,
      )![0] as () => Promise<void>;
      api.get.mockResolvedValue({ ...snapshot(inventory()), revision: 2 });
      await act(refresh);
      const scope =
        panel === "editor" ? within(screen.getByRole("dialog")) : screen;
      expect(scope.getByRole("alert").textContent).toContain(
        "Someone saved a newer catalog",
      );
      expect(
        (
          scope.getByRole("button", {
            name: panel === "editor" ? "Done" : "Save changes",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true);
      expect(api.put).not.toHaveBeenCalled();
    },
  );

  it("clears a recovered status error without hiding an action error", async () => {
    const intervals = vi.spyOn(globalThis, "setInterval");
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", { name: "Configure Yard" });
    const refresh = intervals.mock.calls.find(
      ([, delay]) => delay === 3000,
    )![0] as () => Promise<void>;
    api.get.mockRejectedValueOnce(new Error("Network lost"));
    await act(refresh);
    expect(screen.getByRole("alert").textContent).toContain("Network lost");
    await act(refresh);
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Configure Yard" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    api.post.mockRejectedValueOnce(new Error("Invalid catalog"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("alert");
    await act(refresh);
    expect(screen.getByRole("alert").textContent).toContain("Invalid catalog");
  });

  it("combines fleet-wide temperature with three specific measurements on another charger", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Select shown chargers" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure selected" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.change(screen.getByLabelText("Collection interval in seconds"), {
      target: { value: "60" },
    });
    fireEvent.click(screen.getByRole("button", { name: "By charger" }));
    expect(
      (
        screen.getByRole("checkbox", {
          name: "All measurements for Yard",
        }) as HTMLInputElement
      ).indeterminate,
    ).toBe(true);
    fireEvent.click(screen.getByText("Garage", { selector: "summary" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Garage · AC current" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Garage · Connected" }),
    );
    expect(screen.getByText("4 of 6 measurements selected")).toBeTruthy();
    expect(
      (
        screen.getByRole("checkbox", {
          name: "All measurements for Garage",
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);
    fireEvent.click(
      screen.getByText("Customize individual rates", { selector: "summary" }),
    );
    fireEvent.change(
      screen.getByLabelText("Rate for Garage AC current interval in seconds"),
      { target: { value: "120" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "By category" }));
    expect(
      (
        screen.getByRole("checkbox", {
          name: "Thermal measurements",
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);
    expect(
      (
        screen.getByRole("checkbox", {
          name: "Current measurements",
        }) as HTMLInputElement
      ).indeterminate,
    ).toBe(true);
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const draft = api.put.mock.calls[0]![1].catalog as Catalog;
    const [yard, garage] = draft.sources[0]!.chargers;
    expect(
      yard!.sensors.map((sensor) => effectivePolicy(draft, yard!, sensor).mode),
    ).toEqual(["sample", "off", "off"]);
    expect(
      garage!.sensors.map((sensor) => effectivePolicy(draft, garage!, sensor)),
    ).toEqual([
      { mode: "sample", interval_seconds: 60 },
      { mode: "sample", interval_seconds: 120 },
      { mode: "sample", interval_seconds: 60 },
    ]);
  });

  it("saves definition and collection edits together without a review or confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm");
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", { name: "Configure Yard" });
    fireEvent.change(screen.getAllByLabelText("Charger name")[0]!, {
      target: { value: "Yard renamed" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Configure Yard renamed" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByText("Latest every 10s")).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Changes saved"),
    );
    const catalog = api.put.mock.calls[0]![1].catalog as Catalog;
    expect(catalog.sources[0]!.chargers[0]!.label).toBe("Yard renamed");
    expect(catalog.sources[0]!.chargers[0]!.sensors[0]!.policy?.mode).toBe(
      "sample",
    );
    expect(api.put.mock.calls[0]![1].pause_affected_monitors).toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Review changes" })).toBeNull();
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.queryAllByText("Unsaved changes")).toHaveLength(0);
  });

  it("confirms removals at save time and preserves edits when cancelled", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", { name: "Configure Yard" });
    const yard = within(screen.getByRole("region", { name: "Charger Yard" }));
    fireEvent.click(
      yard.getByText("Charger settings", { selector: "summary" }),
    );
    fireEvent.click(yard.getByRole("button", { name: "Remove charger" }));
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(confirm.mock.calls[0]![0]).toContain("Charger Yard");
    expect(api.put).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "Charger Yard" })).toBeNull();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0]![1].pause_affected_monitors).toBe(false);
  });

  it("keeps the existing catalog when an import fails server validation", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    await screen.findByRole("button", { name: "Configure Yard" });
    api.post.mockRejectedValueOnce(
      new Error("Sensor keys and topics must be unique within a charger"),
    );
    const file = {
      size: 100,
      text: async () => JSON.stringify({ sources: [] }),
    };
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });
    expect((await screen.findByRole("alert")).textContent).toContain(
      "must be unique",
    );
    expect(screen.getByRole("button", { name: "Configure Yard" })).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
    expect(
      (
        screen.getByRole("button", {
          name: "Save changes",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("explains that copying definitions turns off the target charger", async () => {
    const catalog = inventory();
    catalog.sources[0]!.chargers[0]!.policy = {
      mode: "original",
      interval_seconds: 10,
    };
    mockSnapshot(snapshot(catalog));
    show();
    await screen.findByRole("button", { name: "Configure Yard" });
    const yard = within(screen.getByRole("region", { name: "Charger Yard" }));
    fireEvent.click(
      yard.getByText("Charger settings", { selector: "summary" }),
    );
    expect(yard.getByText(/Copying definitions replaces/)).toBeTruthy();
    fireEvent.change(
      yard.getByRole("combobox", {
        name: "Copy sensor definitions from another charger",
      }),
      { target: { value: "charger-1" } },
    );
    expect(yard.getAllByText("Off")).toHaveLength(3);
    expect(yard.getByText("0 of 3 measurements enabled")).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("distinguishes saved changes from worker acknowledgement and application failure", async () => {
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
    await screen.findByRole("button", { name: "Configure Yard" });
    const refresh = intervals.mock.calls.find(
      ([, delay]) => delay === 3000,
    )![0] as () => Promise<void>;
    fireEvent.change(screen.getAllByLabelText("Charger name")[0]!, {
      target: { value: "Yard renamed" },
    });
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
