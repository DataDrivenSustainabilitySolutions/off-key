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
    fireEvent.click(screen.getByText("New sensor"));
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
    mockSnapshot(snapshot(empty, false));
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
    expect(api.post).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
  });
});
