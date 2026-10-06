import { createDefaultWorkspace } from "./model";
import type {
  CameraPose,
  Perspective,
  Point,
  SpatialGroup,
  SpatialWorkspace,
} from "./types";

export const MAX_WORKSPACE_BYTES = 1_000_000;
const MAX_OBJECTS = 10_000;
const INVALID_KEYS = new Set(["__proto__", "constructor", "prototype"]);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isId = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[\w:.-]{1,128}$/.test(value) &&
  !INVALID_KEYS.has(value);
const isName = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= 80;
const boundedNumber = (value: unknown, limit: number): value is number =>
  typeof value === "number" &&
  Number.isFinite(value) &&
  Math.abs(value) <= limit;
const isPoint = (value: unknown): value is Point =>
  isRecord(value) &&
  boundedNumber(value.x, 10_000) &&
  boundedNumber(value.z, 10_000);
const isVector = (value: unknown): value is [number, number, number] =>
  Array.isArray(value) &&
  value.length === 3 &&
  value.every((item) => boundedNumber(item, 100_000));
const isCamera = (value: unknown): value is CameraPose =>
  isRecord(value) &&
  isVector(value.position) &&
  isVector(value.target) &&
  typeof value.zoom === "number" &&
  Number.isFinite(value.zoom) &&
  value.zoom >= 0.05 &&
  value.zoom <= 32;
const isGroup = (value: unknown): value is SpatialGroup =>
  isRecord(value) &&
  isId(value.id) &&
  isName(value.name) &&
  typeof value.color === "string" &&
  /^#[0-9a-fA-F]{6}$/.test(value.color) &&
  typeof value.collapsed === "boolean" &&
  typeof value.locked === "boolean";
const isPerspective = (value: unknown): value is Perspective =>
  isRecord(value) &&
  isId(value.id) &&
  isName(value.name) &&
  isCamera(value.camera) &&
  (value.view === undefined ||
    value.view === "isometric" ||
    value.view === "top");

function validMap(
  value: unknown,
  test: (item: unknown) => boolean,
): value is Record<string, unknown> {
  return (
    isRecord(value) &&
    Object.keys(value).length <= MAX_OBJECTS &&
    Object.entries(value).every(([id, item]) => isId(id) && test(item))
  );
}

/** Copy only presentation fields: runtime measurements must never be saved. */
function validatedWorkspace(value: unknown): SpatialWorkspace | undefined {
  if (!isRecord(value) || value.version !== 1 || !isCamera(value.camera))
    return;
  if (
    !Array.isArray(value.groups) ||
    !value.groups.length ||
    value.groups.length > 64 ||
    !value.groups.every(isGroup)
  )
    return;
  const ids = new Set(value.groups.map((group) => group.id));
  if (ids.size !== value.groups.length) return;
  if (
    !validMap(value.positions, isPoint) ||
    !validMap(value.locks, (locked) => typeof locked === "boolean") ||
    !validMap(value.memberships, (id) => isId(id) && ids.has(id))
  )
    return;
  if (
    !Array.isArray(value.perspectives) ||
    value.perspectives.length > 12 ||
    !value.perspectives.every(isPerspective)
  )
    return;
  if (
    new Set(value.perspectives.map((perspective) => perspective.id)).size !==
    value.perspectives.length
  )
    return;
  return {
    version: 1,
    positions: Object.fromEntries(
      Object.entries(value.positions).map(([id, point]) => [
        id,
        { x: (point as Point).x, z: (point as Point).z },
      ]),
    ),
    locks: Object.fromEntries(Object.entries(value.locks)) as Record<
      string,
      boolean
    >,
    memberships: Object.fromEntries(
      Object.entries(value.memberships),
    ) as Record<string, string>,
    groups: value.groups.map((group) => ({
      id: group.id,
      name: group.name,
      color: group.color,
      collapsed: group.collapsed,
      locked: group.locked,
    })),
    camera: {
      position: [...value.camera.position],
      target: [...value.camera.target],
      zoom: value.camera.zoom,
    },
    perspectives: value.perspectives.map((perspective) => ({
      id: perspective.id,
      name: perspective.name,
      camera: {
        position: [...perspective.camera.position],
        target: [...perspective.camera.target],
        zoom: perspective.camera.zoom,
      },
      ...(perspective.view ? { view: perspective.view } : {}),
    })),
  };
}

export function loadWorkspace(key: string): SpatialWorkspace {
  try {
    const saved = window.localStorage.getItem(key);
    return saved
      ? (parseWorkspace(saved) ?? createDefaultWorkspace())
      : createDefaultWorkspace();
  } catch {
    return createDefaultWorkspace();
  }
}

/** Import shares the storage schema and returns nothing on invalid input. */
export function parseWorkspace(contents: string): SpatialWorkspace | undefined {
  if (contents.length > MAX_WORKSPACE_BYTES) return;
  try {
    return validatedWorkspace(JSON.parse(contents));
  } catch {
    return;
  }
}

export function saveWorkspace(
  key: string,
  workspace: SpatialWorkspace,
): boolean {
  try {
    const safe = validatedWorkspace(workspace);
    if (!safe) return false;
    const serialized = JSON.stringify(safe);
    if (serialized.length > MAX_WORKSPACE_BYTES) return false;
    window.localStorage.setItem(key, serialized);
    return true;
  } catch {
    return false;
  }
}
