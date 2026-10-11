import type { SpatialCatalogProjection } from "./catalog";
import type { SpatialGroup, SpatialWorkspace } from "./types";

const MAX_GROUPS = 128;
const validGroup = (group: SpatialGroup) =>
  /^[\w:.-]{1,128}$/.test(group.id) &&
  group.name.trim().length > 0 &&
  group.name.length <= 80 &&
  /^#[0-9a-fA-F]{6}$/.test(group.color) &&
  typeof group.collapsed === "boolean" &&
  typeof group.locked === "boolean";
const copyGroup = (group: SpatialGroup): SpatialGroup => ({
  id: group.id,
  name: group.name,
  color: group.color,
  collapsed: group.collapsed,
  locked: group.locked,
});

/** Keep fleet containment complete when restoring or importing a presentation. */
export function reconcileCatalogWorkspace(
  catalog: SpatialCatalogProjection,
  workspace: SpatialWorkspace,
): SpatialWorkspace {
  const saved = new Map(
    workspace.groups
      .filter(validGroup)
      .map((group) => [group.id, group]),
  );
  const groups = catalog.groups.map((group) =>
    copyGroup(saved.get(group.id) ?? group),
  );
  const groupIds = new Set(groups.map((group) => group.id));
  // Required collections take priority over custom extras within storage limits.
  for (const group of workspace.groups) {
    if (
      groups.length >= MAX_GROUPS ||
      !/^custom-[\w:.-]+$/.test(group.id) ||
      !validGroup(group) ||
      groupIds.has(group.id)
    )
      continue;
    groups.push(copyGroup(group));
    groupIds.add(group.id);
  }
  return {
    ...workspace,
    groups,
    memberships: {
      ...Object.fromEntries(
        catalog.topology.nodes.map((node) => [node.id, node.groupId]),
      ),
      ...Object.fromEntries(
        Object.entries(workspace.memberships).filter(([, groupId]) =>
          groupIds.has(groupId),
        ),
      ),
    },
  };
}
