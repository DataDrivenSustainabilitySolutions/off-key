export const DEFAULT_SIDEBAR_WIDTH = 264;
export const MIN_SIDEBAR_WIDTH = 224;
export const MAX_SIDEBAR_WIDTH = 360;
const MIN_WORKSPACE_WIDTH = 480;

export function constrainSidebarWidth(width: number, containerWidth = Infinity): number {
  const maximum = Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, containerWidth - MIN_WORKSPACE_WIDTH));
  return Math.round(Math.max(MIN_SIDEBAR_WIDTH, Math.min(maximum, width)));
}
