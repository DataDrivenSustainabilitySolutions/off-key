import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataSources from "../pages/DataSources";
import type { Catalog, CatalogSnapshot } from "../types/collection";

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
  it("limits bulk changes to visible selected chargers and reviews their effective changes", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Select visible chargers" }),
    );
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search catalog" }),
      {
        target: { value: "Yard" },
      },
    );
    expect(
      screen.getByText("1 visible chargers selected · 1 hidden selections"),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Set for visible selected" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByText(
      "Temperature (temperature) · Collection: Paused → Latest every 10s",
    );
    const draft = api.post.mock.calls[0]![1].catalog as Catalog;
    expect(
      draft.sources[0]!.chargers.map((charger) => charger.policy?.mode),
    ).toEqual(["sample", "off"]);
    expect(draft.sources).toHaveLength(2);
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search catalog" }),
      {
        target: { value: "" },
      },
    );
    expect(screen.getByRole("checkbox", { name: "Garage" })).toBeTruthy();
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
  it("preserves selection, category and collection interval across tab switches", async () => {
    mockSnapshot(snapshot(inventory()));
    show();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Yard" }));
    fireEvent.change(screen.getByLabelText("Bulk sensor category"), {
      target: { value: "Thermal" },
    });
    fireEvent.change(
      screen.getByLabelText("Bulk collection policy interval in seconds"),
      { target: { value: "60" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Catalog" }));
    fireEvent.click(screen.getByRole("button", { name: "Collection" }));
    expect(
      (screen.getByRole("checkbox", { name: "Yard" }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(
      (screen.getByLabelText("Bulk sensor category") as HTMLSelectElement)
        .value,
    ).toBe("Thermal");
    expect(
      (
        screen.getByLabelText(
          "Bulk collection policy interval in seconds",
        ) as HTMLInputElement
      ).value,
    ).toBe("60");
    fireEvent.click(
      screen.getByRole("button", { name: "Set for visible selected" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    await screen.findByText(
      "Temperature (temperature) · Collection: Paused → Latest every 60s",
    );
  });
});
