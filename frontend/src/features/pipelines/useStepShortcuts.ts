import { useEffect, useRef, type RefObject } from "react";
import { readSteps, type StepFragment } from "./clipboard";

type Commands = {
  /** The chosen steps as text for the clipboard, taken out of the design when cut; undefined when there are none. */
  copy: (cut: boolean) => string | undefined;
  paste: (fragment: StepFragment) => void;
  /** Whether there was something to duplicate. */
  duplicate: () => boolean;
  /** Whether there was something to choose. */
  selectAll: () => boolean;
  /** Switch the chosen steps off or on; whether any step was chosen. */
  switch: () => boolean;
};

/** Fields, dialogs and menus keep the keys for their own text and entries. */
const keepsKeys = (target: EventTarget | null) => target instanceof Element
  && !!target.closest("input, textarea, select, [contenteditable='true'], [role='dialog'], [role='menu']");

/**
 * Copy, cut and paste through the clipboard of the system, so steps travel between designs
 * and windows, plus Ctrl/Cmd+D to duplicate, Ctrl/Cmd+B to switch off or on and Ctrl/Cmd+A to choose every step.
 */
export function useStepShortcuts(canvas: RefObject<HTMLElement | null>, commands: Commands) {
  const latest = useRef(commands);
  useEffect(() => { latest.current = commands; });
  useEffect(() => {
    const copy = (event: ClipboardEvent) => {
      // Text marked on the page is copied as text.
      if (keepsKeys(event.target) || window.getSelection()?.isCollapsed === false) return;
      const text = latest.current.copy(event.type === "cut");
      if (!text) return;
      event.clipboardData?.setData("text/plain", text);
      event.preventDefault();
    };
    const paste = (event: ClipboardEvent) => {
      if (keepsKeys(event.target)) return;
      const fragment = readSteps(event.clipboardData?.getData("text/plain") ?? "");
      if (!fragment) return;
      event.preventDefault();
      latest.current.paste(fragment);
    };
    const keydown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.defaultPrevented
        || keepsKeys(event.target)) return;
      const key = event.key.toLowerCase();
      // Elsewhere on the page Ctrl/Cmd+A marks its text, as it does on any page.
      const onCanvas = event.target === window.document.body
        || (event.target instanceof Node && !!canvas.current?.contains(event.target));
      const done = key === "d" ? latest.current.duplicate() : key === "b" ? latest.current.switch()
        : key === "a" && onCanvas ? latest.current.selectAll() : false;
      if (done) event.preventDefault();
    };
    window.addEventListener("copy", copy);
    window.addEventListener("cut", copy);
    window.addEventListener("paste", paste);
    window.addEventListener("keydown", keydown);
    return () => {
      window.removeEventListener("copy", copy);
      window.removeEventListener("cut", copy);
      window.removeEventListener("paste", paste);
      window.removeEventListener("keydown", keydown);
    };
  }, [canvas]);
}
