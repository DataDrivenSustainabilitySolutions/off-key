export const DEFAULT_SIDEBAR_WIDTH = 288;
export const MIN_SIDEBAR_WIDTH = 240;
export const MAX_SIDEBAR_WIDTH = 480;
export const MIN_WORKSPACE_WIDTH = 480;

export function constrainSidebarWidth(width: number, containerWidth = Infinity): number {
  const maximum = Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, containerWidth - MIN_WORKSPACE_WIDTH));
  return Math.round(Math.max(MIN_SIDEBAR_WIDTH, Math.min(maximum, width)));
}
