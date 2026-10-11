import type { SpatialPersonalGroup, SpatialWorkspace } from "./types";

export const PERSONAL_GROUP_COLORS = [
  "#398577",
  "#6589b3",
  "#aa80a6",
  "#bb9657",
  "#7c96a0",
  "#9aab7d",
] as const;
export const MAX_PERSONAL_GROUPS = 128;
export const MAX_PERSONAL_MEMBERSHIPS = 32_768;
export const MAX_PERSONAL_GROUP_MEMBERS = 10_000;

export function personalGroupMemberIds(
  workspace: SpatialWorkspace,
  groupId: string | null,
): Set<string> {
  return new Set(
    workspace.personalGroups?.find((group) => group.id === groupId)
      ?.memberIds ?? [],
  );
}

export function createPersonalGroup(
  workspace: SpatialWorkspace,
  name: string,
  memberId?: string | null,
): SpatialWorkspace {
  const groups = workspace.personalGroups ?? [];
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 120 || groups.length >= MAX_PERSONAL_GROUPS)
    return workspace;
  const group: SpatialPersonalGroup = {
    id: `personal:${crypto.randomUUID()}`,
    name: trimmed,
    color: PERSONAL_GROUP_COLORS[groups.length % PERSONAL_GROUP_COLORS.length]!,
    memberIds:
      memberId && membershipCount(workspace) < MAX_PERSONAL_MEMBERSHIPS
        ? [memberId]
        : [],
  };
  return { ...workspace, personalGroups: [...groups, group] };
}

export function updatePersonalGroup(
  workspace: SpatialWorkspace,
  id: string,
  change: Partial<Pick<SpatialPersonalGroup, "name" | "color">>,
): SpatialWorkspace {
  const name = change.name?.trim();
  if (name !== undefined && (!name || name.length > 120)) return workspace;
  if (change.color !== undefined && !/^#[0-9a-fA-F]{6}$/.test(change.color))
    return workspace;
  return {
    ...workspace,
    personalGroups: (workspace.personalGroups ?? []).map((group) =>
      group.id === id
        ? { ...group, ...change, ...(name !== undefined ? { name } : {}) }
        : group,
    ),
  };
}

function membershipCount(workspace: SpatialWorkspace): number {
  return (workspace.personalGroups ?? []).reduce(
    (total, group) => total + group.memberIds.length,
    0,
  );
}

export function canAddPersonalMember(workspace: SpatialWorkspace): boolean {
  return membershipCount(workspace) < MAX_PERSONAL_MEMBERSHIPS;
}

/** Never changes catalog memberships, object placement, or MQTT bindings. */
export function togglePersonalGroupMember(
  workspace: SpatialWorkspace,
  id: string,
  memberId: string,
): SpatialWorkspace {
  const target = workspace.personalGroups?.find((group) => group.id === id);
  if (
    !target ||
    (!target.memberIds.includes(memberId) &&
      (target.memberIds.length >= MAX_PERSONAL_GROUP_MEMBERS ||
        !canAddPersonalMember(workspace)))
  )
    return workspace;
  return {
    ...workspace,
    personalGroups: workspace.personalGroups!.map((group) =>
      group.id !== id
        ? group
        : {
            ...group,
            memberIds: group.memberIds.includes(memberId)
              ? group.memberIds.filter((member) => member !== memberId)
              : [...group.memberIds, memberId],
          },
    ),
  };
}

export function deletePersonalGroup(
  workspace: SpatialWorkspace,
  id: string,
): SpatialWorkspace {
  return {
    ...workspace,
    personalGroups: (workspace.personalGroups ?? []).filter(
      (group) => group.id !== id,
    ),
  };
}
