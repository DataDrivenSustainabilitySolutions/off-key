import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
const mockSnapshot = (value = snapshot()) =>
  api.get.mockImplementation(async (url: string) =>
    url === "/v1/sources/storage"
      ? {
          database_size_bytes: 10000000,
          retention_policies: [],
          checked_at: "2026-09-27T12:00:00Z",
        }
      : value,
  );
const show = () =>
  render(
    <MemoryRouter>
      <DataSources />
    </MemoryRouter>,
  );

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
  it("builds a broker, charger and sensor without a configuration file", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Catalog" }));
    fireEvent.click(screen.getByRole("button", { name: "Add broker" }));
    const host = screen.getByLabelText("Hostname");
    fireEvent.change(host, { target: { value: "charger.ts.net" } });
    expect(host.closest("details")?.open).toBe(true);
    fireEvent.change(screen.getByLabelText("Charger name"), {
      target: { value: "Yard charger" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add sensor" }));
    fireEvent.click(screen.getByText("New sensor", { selector: "summary" }));
    fireEvent.change(screen.getByLabelText("Sensor key"), {
      target: { value: "temperature" },
    });
    fireEvent.change(screen.getByLabelText("Upstream topic"), {
      target: { value: "device/evCharger/0/temperature" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByRole("button", { name: "Apply collection" });
    const catalog = api.post.mock.calls[0]?.[1].catalog as Catalog;
    expect(catalog.sources[0]?.host).toBe("charger.ts.net");
    const charger = catalog.sources[0]?.chargers[0];
    expect(charger?.label).toBe("Yard charger");
    expect(charger?.policy?.mode).toBe("off");
    expect(charger?.sensors[0]?.upstream_topic).toBe(
      "device/evCharger/0/temperature",
    );
    expect(api.put).not.toHaveBeenCalled();
  });

  it("imports a catalog and requires acknowledgement before pausing affected monitors", async () => {
    const catalog: Catalog = {
      ...empty,
      sources: [
        {
          id: "cf3f5f77-e08d-4a33-8815-94cebbf2f63c",
          label: "Yard",
          host: "yard.ts.net",
          port: 1883,
          forward_port: null,
          verified: false,
          chargers: [],
        },
      ],
    };
    api.post.mockImplementation(async (_url, { catalog }) => ({
      revision: 1,
      catalog,
      chargers: 0,
      selected_sensors: 0,
      sampled_rows_per_day_ceiling: 0,
      original_rate_sensors: 0,
      affected_monitors: [{ id: "monitor-1", name: "Yard temperature" }],
    }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Catalog" }));
    const file = { size: 1024, text: async () => JSON.stringify(catalog) };
    const upload = document.querySelector('input[type="file"]')!;
    fireEvent.change(upload, { target: { files: [file] } });
    const apply = await screen.findByRole("button", {
      name: "Apply collection",
    });
    expect((apply as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Pause affected monitors/ }),
    );
    fireEvent.click(apply);
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
    fireEvent.click(await screen.findByRole("button", { name: "Catalog" }));
    expect(screen.queryByRole("button", { name: "Review changes" })).toBeNull();
    expect(
      (
        screen.getByRole("button", {
          name: "Import catalog",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: "Add broker" }).closest("fieldset")
        ?.disabled,
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
    fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByText(
      "Temperature (temperature) · Collection: Paused → Latest every 10s",
    );
    const draft = api.post.mock.calls[0]![1].catalog as Catalog;
    const [yard, garage] = draft.sources[0]!.chargers;
    expect(
      yard!.sensors.map((sensor) => effectivePolicy(draft, yard!, sensor).mode),
    ).toEqual(["sample", "off", "off"]);
    expect(garage).toEqual(original.sources[0]!.chargers[1]);
    expect(draft.sources[1]).toEqual(original.sources[1]);
    expect(api.put).not.toHaveBeenCalled();
  });

  it("edits a filtered charger by identity without deleting hidden definitions", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Catalog" }));
    expect(
      screen.getByText(
        /This draft contains 1 observed brokers and 1 candidate hosts/,
      ),
    ).toBeTruthy();
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search catalog" }),
      {
        target: { value: "Garage" },
      },
    );
    fireEvent.change(screen.getByLabelText("Charger name"), {
      target: { value: "Garage renamed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByRole("button", { name: "Apply collection" });
    const draft = api.post.mock.calls[0]![1].catalog as Catalog;
    expect(draft.sources[0]!.chargers.map((charger) => charger.label)).toEqual([
      "Yard",
      "Garage renamed",
    ]);
    expect(draft.sources[1]!.host).toBe("candidate.ts.net");
  });

  it("filters candidate hosts and clears filters when adding a broker", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Catalog" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "Catalog" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByRole("button", { name: "Apply collection" });
    const source = (api.post.mock.calls[0]![1].catalog as Catalog).sources[0]!;
    expect(source.host).toBe("new.ts.net");
    expect(source.verified).toBe(false);
  });
  it("preserves charger selection and staged measurement rates across tab switches", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Catalog" }));
    fireEvent.click(screen.getByRole("button", { name: "Collection" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByText(
      "Temperature (temperature) · Collection: Paused → Latest every 60s",
    );
  });

  it.each(["Thermal", "Current", "Status"])(
    "selects only %s and persists it only after review and apply",
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
      fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
      expect(api.put).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
      fireEvent.click(
        await screen.findByRole("button", { name: "Apply collection" }),
      );
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
    fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByRole("button", { name: "Apply collection" });
    const draft = api.post.mock.calls[0]![1].catalog as Catalog;
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
          name: "Review changes",
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
    fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByRole("button", { name: "Apply collection" });
    const draft = api.post.mock.calls[0]![1].catalog as Catalog;
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
            name: "Update draft",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true);
      expect(screen.getByRole("alert").textContent).toContain("whole seconds");
      expect(api.put).not.toHaveBeenCalled();
    },
  );

  it("shows apply errors inside review and allows a safe retry", async () => {
    api.put.mockRejectedValueOnce(new Error("Database unavailable"));
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Configure Yard" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Thermal measurements" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Apply collection" }),
    );
    const review = screen.getByRole("dialog", {
      name: "Review and start collection",
    });
    await within(review).findByRole("alert");
    expect(within(review).getByRole("alert").textContent).toContain(
      "Database unavailable",
    );
    fireEvent.click(
      within(review).getByRole("button", { name: "Apply collection" }),
    );
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
    expect(api.put.mock.calls[0]![1]).toEqual(api.put.mock.calls[1]![1]);
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
            name: "Update draft",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
      fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
      await screen.findByRole("button", { name: "Apply collection" });
      const draft = api.post.mock.calls[0]![1].catalog as Catalog;
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
    expect(screen.queryByRole("button", { name: "Review changes" })).toBeNull();
    fireEvent.click(details);
    expect(
      (
        screen.getByRole("checkbox", {
          name: "Thermal measurements",
        }) as HTMLInputElement
      ).closest("fieldset")?.disabled,
    ).toBe(true);
    expect(screen.queryByRole("button", { name: "Update draft" })).toBeNull();
    expect(
      screen.getByText(/View only · these are the saved collection settings/),
    ).toBeTruthy();
  });

  it("returns keyboard focus after closing the editor and review", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
    await waitFor(() => expect(document.activeElement).toBe(configure));
    const review = screen.getByRole("button", { name: "Review changes" });
    review.focus();
    fireEvent.click(review);
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(document.activeElement).toBe(review));
    fireEvent.click(review);
    fireEvent.click(
      await screen.findByRole("button", { name: "Apply collection" }),
    );
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Collection" }),
      ),
    );
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

  it("pauses selected chargers even when their sensors override the charger policy", async () => {
    const catalog = inventory();
    catalog.sources[0]!.chargers[0]!.sensors[0]!.policy = {
      mode: "original",
      interval_seconds: 10,
    };
    mockSnapshot(snapshot(catalog));
    show();
    fireEvent.click(
      await screen.findByRole("checkbox", { name: "Select Yard for editing" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Pause selected" }));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByRole("button", { name: "Apply collection" });
    const next = api.post.mock.calls[0]![1].catalog as Catalog;
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
    fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(screen.getByText(/Unsaved draft/)).toBeTruthy();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    await screen.findByRole("button", { name: "Reload saved catalog" });
    const cleanUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanUnload);
    expect(cleanUnload.defaultPrevented).toBe(false);
  });

  it.each(["editor", "review"])(
    "blocks a stale %s when another administrator saves",
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
      if (panel === "review") {
        fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
        fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
        await screen.findByRole("button", { name: "Apply collection" });
      }
      const refresh = intervals.mock.calls.find(
        ([, delay]) => delay === 3000,
      )![0] as () => Promise<void>;
      api.get.mockResolvedValue({ ...snapshot(inventory()), revision: 2 });
      await act(refresh);
      const dialog = screen.getByRole("dialog");
      expect(within(dialog).getByRole("alert").textContent).toContain(
        "Someone saved a newer catalog",
      );
      expect(
        (
          within(dialog).getByRole("button", {
            name: panel === "editor" ? "Update draft" : "Apply collection",
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
    fireEvent.click(screen.getByRole("button", { name: "Update draft" }));
    api.post.mockRejectedValueOnce(new Error("Invalid catalog"));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByRole("alert");
    await act(refresh);
    expect(screen.getByRole("alert").textContent).toContain("Invalid catalog");
  });
});
