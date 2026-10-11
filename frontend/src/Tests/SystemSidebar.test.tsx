import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SystemSidebar } from "@/features/spatial/SystemSidebar";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import { projectSystemDocument } from "@/features/spatial/systemProjection";
import type { SystemDocument } from "@/features/spatial/systemTypes";

const fixture = (): SystemDocument => ({
  ...createEmptySystem(),
  connections: [
    {
      id: "broker",
      label: "Shared broker",
      protocol: "mqtt",
      host: "broker.example.test",
      port: 1883,
      transport: "tcp",
      tls: false,
    },
  ],
  devices: [
    {
      id: "east",
      label: "East roof",
      kind: "station",
      connection_id: "broker",
    },
    {
      id: "west",
      label: "West roof",
      kind: "station",
      connection_id: "broker",
    },
  ],
  streams: [
    {
      id: "east-version",
      label: "Version",
      connection_id: "broker",
      device_id: "east",
      topic: "east/version",
      value_type: "text",
      category: "Other",
    },
    {
      id: "west-version",
      label: "Version",
      connection_id: "broker",
      device_id: "west",
      topic: "west/version",
      value_type: "text",
      category: "Other",
    },
    {
      id: "broker-version",
      label: "Version",
      connection_id: "broker",
      topic: "broker/version",
      value_type: "text",
      category: "Other",
    },
  ],
  groups: [],
});
const props = (query = "") => {
  const document = fixture();
  const projection = projectSystemDocument(document);
  return {
    document,
    nodes: projection.topology.nodes,
    workspace: projection.workspace,
    query,
    filter: "stream" as const,
    selectedId: null,
    selectedGroup: null,
    canEdit: true,
    saved: true,
    onQuery: vi.fn(),
    onFilter: vi.fn(),
    onSelect: vi.fn(),
    onGroup: vi.fn(),
    onCreate: vi.fn(),
    onLayout: vi.fn(),
  };
};

describe("configured stream navigation", () => {
  it("keeps catalog navigation and personal membership without any placement locks", () => {
    const options = props();
    options.document.groups = [
      { id: "roof", label: "Roof", member_ids: ["east"] },
    ];
    const projection = projectSystemDocument(options.document);
    options.workspace = {
      ...projection.workspace,
      groups: projection.workspace.groups.map((group) => ({
        ...group,
        locked: true,
      })),
      personalGroups: [
        { id: "mine", name: "Maintenance", color: "#448877", memberIds: [] },
      ],
    };
    const personal = vi.fn();
    render(
      <SystemSidebar
        {...options}
        selectedId="east"
        onPersonalGroup={personal}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /^(Lock|Unlock) / }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Roof1" }));
    expect(options.onGroup).toHaveBeenCalledWith("roof");
    expect(options.onLayout).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Add selected object to Maintenance",
      }),
    );
    expect(
      options.onLayout.mock.calls[0]![0].personalGroups[0].memberIds,
    ).toEqual(["east"]);
    fireEvent.click(
      screen.getByRole("button", { name: "Show personal group Maintenance" }),
    );
    expect(personal).toHaveBeenCalledWith("mine");
  });

  it("disambiguates repeated stream titles with visible and accessible device owners", () => {
    const options = props();
    render(<SystemSidebar {...options} />);
    const east = screen.getByRole("button", { name: "Version · East roof" });
    expect(east.querySelector("small")?.textContent).toBe("East roof");
    expect(
      screen.getByRole("button", { name: "Version · West roof" }),
    ).not.toBeNull();
    expect(
      screen
        .getByRole("button", { name: "Version · Shared broker" })
        .querySelector("small")?.textContent,
    ).toBe("Shared broker");
    fireEvent.click(east);
    expect(options.onSelect).toHaveBeenCalledWith("east-version");
    expect(screen.queryByRole("button", { name: "Ungrouped" })).toBeNull();
  });

  it("finds independent stream bindings by their owning connection", () => {
    render(<SystemSidebar {...props("Shared broker")} />);
    expect(
      screen.getByRole("button", { name: "Version · Shared broker" }),
    ).not.toBeNull();
    expect(
      screen.queryByRole("button", { name: "Version · East roof" }),
    ).toBeNull();
  });
});
