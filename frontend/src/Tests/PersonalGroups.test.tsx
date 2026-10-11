import { useState } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PersonalGroups,
  PersonalGroupMembership,
} from "@/features/spatial/PersonalGroupControls";
import {
  createPersonalGroup,
  deletePersonalGroup,
  personalGroupMemberIds,
  togglePersonalGroupMember,
  updatePersonalGroup,
} from "@/features/spatial/personalGroups";
import {
  createDefaultWorkspace,
  resolveTopology,
} from "@/features/spatial/model";
import { SystemObjectInspector } from "@/features/spatial/SystemObjectInspector";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import {
  projectSystemDocument,
  reconcileSystemWorkspace,
} from "@/features/spatial/systemProjection";
import {
  loadWorkspace,
  parseWorkspace,
  saveWorkspace,
} from "@/features/spatial/workspace";
import type { SpatialWorkspace } from "@/features/spatial/types";

afterEach(cleanup);
beforeEach(() => localStorage.clear());

describe("automatic placement in the object inspector", () => {
  it("offers focus and personal membership without manual pinning even for older locked layouts", () => {
    const document = {
      ...createEmptySystem(),
      devices: [{ id: "pump", label: "Pump", kind: "pump" }],
      groups: [{ id: "site", label: "North site", member_ids: ["pump"] }],
    };
    const projection = projectSystemDocument(document);
    const workspace = createPersonalGroup(
      {
        ...projection.workspace,
        groups: projection.workspace.groups.map((group) => ({
          ...group,
          locked: true,
        })),
      },
      "Maintenance",
    );
    const focus = vi.fn();
    const layout = vi.fn();
    render(
      <SystemObjectInspector
        node={resolveTopology(projection.topology, workspace).nodes[0]!}
        document={document}
        workspace={workspace}
        onLayout={layout}
        canEdit={true}
        saveError=""
        disabledReason=""
        onRename={vi.fn()}
        onEdit={vi.fn()}
        onSelect={vi.fn()}
        onFocus={focus}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /^(Pin|Unpin|Pinned by group)$/ }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Focus" }));
    expect(focus).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("checkbox", { name: "Maintenance" }));
    const changed = layout.mock.calls[0]![0] as SpatialWorkspace;
    expect(changed.personalGroups![0]!.memberIds).toEqual(["pump"]);
    expect(changed.groups).toBe(workspace.groups);
    expect(changed.positions).toBe(workspace.positions);
  });
});

describe("personal grouping as a presentation overlay", () => {
  it("roundtrips multiple memberships separately from the catalog and existing layout", () => {
    const document = {
      ...createEmptySystem(),
      devices: [{ id: "device:one", label: "Pump", kind: "pump" }],
      groups: [{ id: "site", label: "Site", member_ids: ["device:one"] }],
    };
    const original = JSON.stringify(document);
    const projection = projectSystemDocument(document);
    const before = projection.workspace;
    let next = createPersonalGroup(before, "Maintenance", "device:one");
    next = createPersonalGroup(next, "Favourites", "device:one");
    const first = next.personalGroups![0]!;
    const second = next.personalGroups![1]!;
    next = updatePersonalGroup(next, first.id, {
      name: "  Critical assets  ",
      color: "#abc123",
    });

    expect(next.memberships).toBe(before.memberships);
    expect(next.groups).toBe(before.groups);
    expect(next.positions).toBe(before.positions);
    expect(next.personalGroups![0]!.name).toBe("Critical assets");
    expect(personalGroupMemberIds(next, first.id)).toEqual(
      new Set(["device:one"]),
    );
    expect(personalGroupMemberIds(next, second.id)).toEqual(
      new Set(["device:one"]),
    );
    expect(saveWorkspace("user:alice", next)).toBe(true);
    expect(loadWorkspace("user:alice")).toEqual(next);
    expect(loadWorkspace("user:bob").personalGroups).toBeUndefined();
    expect(parseWorkspace(JSON.stringify(next))).toEqual(next);
    expect(reconcileSystemWorkspace(projection, next).personalGroups).toEqual(
      next.personalGroups,
    );
    expect(JSON.stringify(document)).toBe(original);

    const removed = togglePersonalGroupMember(next, first.id, "device:one");
    expect(personalGroupMemberIds(removed, first.id).size).toBe(0);
    expect(personalGroupMemberIds(removed, second.id).size).toBe(1);
    const deleted = deletePersonalGroup(removed, second.id);
    expect(deleted.personalGroups).toHaveLength(1);
    expect(deleted.memberships).toBe(before.memberships);
    expect(projection.topology.nodes).toHaveLength(1);
    expect(JSON.stringify(document)).toBe(original);
  });

  it("keeps older workspace files valid and strips unknown personal fields", () => {
    const old = createDefaultWorkspace();
    expect(parseWorkspace(JSON.stringify(old))).toEqual(old);
    const next = createPersonalGroup(old, "My equipment", "sensor-1");
    const imported = parseWorkspace(
      JSON.stringify({
        ...next,
        personalGroups: [
          {
            ...next.personalGroups![0]!,
            readings: [1, 2],
            password: "ignored",
          },
        ],
      }),
    );
    expect(imported).toEqual(next);
  });

  it.each([
    { id: "g", name: "Group", color: "red", memberIds: [] },
    { id: "g", name: "", color: "#123456", memberIds: [] },
    { id: "g", name: "Group", color: "#123456", memberIds: ["__proto__"] },
    {
      id: "g",
      name: "Group",
      color: "#123456",
      memberIds: ["sensor", "sensor"],
    },
    { id: "g", name: "Group", color: "#123456", memberIds: "sensor" },
  ])("rejects malformed personal group data before persistence", (group) => {
    expect(
      parseWorkspace(
        JSON.stringify({
          ...createDefaultWorkspace(),
          personalGroups: [group],
        }),
      ),
    ).toBeUndefined();
  });
});

function GroupsHarness({
  initial = createDefaultWorkspace(),
}: {
  initial?: SpatialWorkspace;
}) {
  const [workspace, setWorkspace] = useState(initial);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  return (
    <>
      <PersonalGroups
        workspace={workspace}
        selectedId="device:one"
        selectedGroupId={selectedGroupId}
        onChange={setWorkspace}
        onSelectGroup={setSelectedGroupId}
      />
      <output data-testid="workspace">{JSON.stringify(workspace)}</output>
      <output data-testid="selected-group">{selectedGroupId}</output>
    </>
  );
}
const current = (): SpatialWorkspace =>
  JSON.parse(screen.getByTestId("workspace").textContent!);

describe("easy personal grouping controls", () => {
  it("creates with the selected object, toggles membership, changes color, and deletes only the personal group", () => {
    render(<GroupsHarness />);
    fireEvent.click(
      screen.getByRole("button", { name: "Create personal group" }),
    );
    const input = screen.getByRole("textbox", {
      name: "New personal group name",
    });
    fireEvent.change(input, { target: { value: "North site" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    expect(current().personalGroups).toHaveLength(1);
    expect(current().personalGroups![0]!.memberIds).toEqual(["device:one"]);
    expect(screen.getByTestId("selected-group").textContent).toBe(
      current().personalGroups![0]!.id,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove selected object from North site",
      }),
    );
    expect(current().personalGroups![0]!.memberIds).toEqual([]);
    fireEvent.click(
      screen.getByRole("button", { name: "Add selected object to North site" }),
    );
    expect(current().personalGroups![0]!.memberIds).toEqual(["device:one"]);
    fireEvent.change(screen.getByLabelText("Color for North site"), {
      target: { value: "#4499aa" },
    });
    expect(current().personalGroups![0]!.color).toBe("#4499aa");
    fireEvent.click(
      screen.getByRole("button", { name: "Delete personal group North site" }),
    );
    expect(current().personalGroups).toEqual([]);
    expect(screen.getByTestId("selected-group").textContent).toBe("");
    expect(current().groups).toEqual(createDefaultWorkspace().groups);
  });

  it("saves group renames with Enter or blur, and cancels with Escape", async () => {
    render(
      <GroupsHarness
        initial={createPersonalGroup(createDefaultWorkspace(), "North site")}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Edit personal group North site" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Rename personal group North site" }),
    );
    let input = screen.getByRole("textbox", {
      name: "Rename personal group North site",
    });
    fireEvent.change(input, { target: { value: "East site" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(current().personalGroups![0]!.name).toBe("East site");
    fireEvent.click(
      screen.getByRole("button", { name: "Rename personal group East site" }),
    );
    input = screen.getByRole("textbox", {
      name: "Rename personal group East site",
    });
    fireEvent.change(input, { target: { value: "West site" } });
    fireEvent.blur(input);
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(current().personalGroups![0]!.name).toBe("West site");
    fireEvent.click(
      screen.getByRole("button", { name: "Rename personal group West site" }),
    );
    input = screen.getByRole("textbox", {
      name: "Rename personal group West site",
    });
    fireEvent.change(input, { target: { value: "Cancelled" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);
    expect(current().personalGroups![0]!.name).toBe("West site");
  });

  it("creates on blur and cancels a new group without accidentally saving on Escape", () => {
    render(<GroupsHarness />);
    fireEvent.click(
      screen.getByRole("button", { name: "Create personal group" }),
    );
    let input = screen.getByRole("textbox", {
      name: "New personal group name",
    });
    fireEvent.change(input, { target: { value: "Saved on blur" } });
    fireEvent.blur(input);
    expect(current().personalGroups![0]!.name).toBe("Saved on blur");
    fireEvent.click(
      screen.getByRole("button", { name: "Create personal group" }),
    );
    input = screen.getByRole("textbox", { name: "New personal group name" });
    fireEvent.change(input, { target: { value: "Cancelled" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);
    expect(current().personalGroups).toHaveLength(1);
  });

  it("supports multiple inspector memberships independently", () => {
    let initial = createPersonalGroup(createDefaultWorkspace(), "Maintenance");
    initial = createPersonalGroup(initial, "Favourites", "device:one");
    function InspectorHarness() {
      const [workspace, setWorkspace] = useState(initial);
      return (
        <>
          <PersonalGroupMembership
            workspace={workspace}
            nodeId="device:one"
            onChange={setWorkspace}
          />
          <output data-testid="workspace">{JSON.stringify(workspace)}</output>
        </>
      );
    }
    render(<InspectorHarness />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Maintenance" }));
    expect(
      current().personalGroups!.every((group) =>
        group.memberIds.includes("device:one"),
      ),
    ).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Favourites" }));
    expect(current().personalGroups![0]!.memberIds).toEqual(["device:one"]);
    expect(current().personalGroups![1]!.memberIds).toEqual([]);
  });
});
