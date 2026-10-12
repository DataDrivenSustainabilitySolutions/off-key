import { useEffect, useRef, useSyncExternalStore, type PointerEvent } from "react";
import { constrainSidebarWidth, DEFAULT_SIDEBAR_WIDTH, MAX_SIDEBAR_WIDTH, MIN_SIDEBAR_WIDTH } from "./sidebarSizing";

type Drag = {
  handle: HTMLDivElement;
  shell: HTMLElement;
  pointerId: number;
  startX: number;
  startWidth: number;
  savedWidth: number;
  nextWidth: number;
  frame: number;
};

const subscribeViewport = (listener: () => void) => {
  window.addEventListener("resize", listener);
  return () => window.removeEventListener("resize", listener);
};
const viewportWidth = () => window.innerWidth;

function endDrag(drag: Drag, width: number) {
  cancelAnimationFrame(drag.frame);
  drag.shell.style.setProperty("--ex-sidebar-width", `${width}px`);
  drag.shell.classList.remove("is-resizing");
  drag.handle.removeAttribute("data-resizing");
  drag.handle.setAttribute("aria-valuenow", String(constrainSidebarWidth(width, window.innerWidth)));
  if (drag.handle.hasPointerCapture(drag.pointerId)) drag.handle.releasePointerCapture(drag.pointerId);
}

export function ExplorerSidebarResize({ width, onCommit }: { width: number; onCommit: (width: number) => void }) {
  const handle = useRef<HTMLDivElement>(null);
  const gesture = useRef<Drag | null>(null);
  const available = useSyncExternalStore(subscribeViewport, viewportWidth, () => 1024);
  const displayedWidth = constrainSidebarWidth(width, available);
  const maximum = constrainSidebarWidth(MAX_SIDEBAR_WIDTH, available);

  useEffect(() => {
    const cancel = () => {
      const drag = gesture.current;
      gesture.current = null;
      if (drag) endDrag(drag, drag.savedWidth);
    };
    window.addEventListener("blur", cancel);
    return () => { window.removeEventListener("blur", cancel); cancel(); };
  }, []);

  const finish = (save: boolean) => {
    const drag = gesture.current;
    if (!drag) return;
    gesture.current = null;
    const changed = save && drag.nextWidth !== drag.startWidth;
    endDrag(drag, changed ? drag.nextWidth : drag.savedWidth);
    if (changed) onCommit(drag.nextWidth);
  };

  const move = (event: PointerEvent<HTMLDivElement>) => {
    const drag = gesture.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.nextWidth = constrainSidebarWidth(drag.startWidth + event.clientX - drag.startX, window.innerWidth);
    // Change only layout during the gesture. Commit React state and storage once
    // on release, without rebuilding the catalogue or rerendering the preview.
    if (drag.frame) return;
    drag.frame = requestAnimationFrame(() => {
      drag.frame = 0;
      if (gesture.current !== drag) return;
      drag.shell.style.setProperty("--ex-sidebar-width", `${drag.nextWidth}px`);
      drag.handle.setAttribute("aria-valuenow", String(drag.nextWidth));
    });
  };

  return <div ref={handle} className="ex-sidebar-resize" role="separator" tabIndex={0}
    aria-label="Resize explorer sidebar" aria-orientation="vertical" aria-controls="system-explorer"
    aria-valuemin={MIN_SIDEBAR_WIDTH} aria-valuemax={maximum} aria-valuenow={displayedWidth}
    onPointerDown={(event) => {
      if (event.button !== 0 || !event.isPrimary || gesture.current) return;
      const shell = event.currentTarget.closest<HTMLElement>(".ex-shell");
      const dock = event.currentTarget.parentElement;
      if (!shell || !dock) return;
      event.preventDefault();
      event.currentTarget.focus({ preventScroll: true });
      const startWidth = dock.getBoundingClientRect().width;
      gesture.current = { handle: event.currentTarget, shell, pointerId: event.pointerId,
        startX: event.clientX, startWidth, savedWidth: width, nextWidth: startWidth, frame: 0 };
      event.currentTarget.setPointerCapture(event.pointerId);
      event.currentTarget.dataset.resizing = "true";
      shell.classList.add("is-resizing");
    }}
    onPointerMove={move}
    onPointerUp={(event) => {
      if (event.pointerId !== gesture.current?.pointerId) return;
      move(event); finish(true);
    }}
    onPointerCancel={(event) => { if (event.pointerId === gesture.current?.pointerId) finish(false); }}
    onLostPointerCapture={(event) => { if (event.pointerId === gesture.current?.pointerId) finish(true); }}
    onDoubleClick={() => { finish(false); onCommit(DEFAULT_SIDEBAR_WIDTH); }}
    onKeyDown={(event) => {
      if (event.key === "Escape" && gesture.current) {
        event.preventDefault(); event.stopPropagation(); finish(false); return;
      }
      const step = event.shiftKey ? 64 : 16;
      const next = event.key === "ArrowLeft" ? displayedWidth - step : event.key === "ArrowRight" ? displayedWidth + step
        : event.key === "Home" ? MIN_SIDEBAR_WIDTH : event.key === "End" ? maximum : undefined;
      if (next === undefined) return;
      event.preventDefault(); event.stopPropagation();
      finish(false);
      onCommit(constrainSidebarWidth(next, available));
    }} />;
}
