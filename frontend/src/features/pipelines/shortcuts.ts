/** A key or combination of keys: as it is shown, and as assistive technology is told. */
export type Shortcut = { label: string; aria: string };

const apple = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);

/** A key held with Ctrl, or with ⌘ on a Mac; `shift` adds Shift. */
const command = (key: string, shift = false): Shortcut => apple
  ? { label: `${shift ? "⇧" : ""}⌘${key}`, aria: `${shift ? "Shift+" : ""}Meta+${key}` }
  : { label: `${shift ? "Shift+" : ""}Ctrl+${key}`, aria: `${shift ? "Shift+" : ""}Control+${key}` };
const key = (label: string, aria = label): Shortcut => ({ label, aria });

/** The keys of the canvas, named once for its menus, its buttons and the list of them. */
export const SHORTCUTS = {
  add: key("A"),
  note: key("N"),
  rename: key("F2"),
  duplicate: command("D"),
  copy: command("C"),
  cut: command("X"),
  paste: command("V"),
  remove: key("Del", "Delete"),
  keep: command("Enter"),
  switch: command("B"),
  selectAll: command("A"),
  undo: command("Z"),
  redo: command("Z", true),
  fit: key("1"),
  readable: key("0"),
  help: key("?"),
} satisfies Record<string, Shortcut>;

type Row = {
  does: string;
  /** Keys and gestures as they are shown: any one of them does it, or one each where the row names several things. */
  keys: string[];
  /** Changes the design, so a design that is only shown leaves it out. */
  edits?: boolean;
};

/** Every key and gesture of the canvas, as its list shows them. */
export const SHORTCUT_SHEET: Array<{ title: string; rows: Row[] }> = [
  { title: "Steps", rows: [
    { does: "Add a step", keys: [SHORTCUTS.add.label, "Double-click"], edits: true },
    { does: "Rename", keys: [SHORTCUTS.rename.label], edits: true },
    { does: "Duplicate", keys: [SHORTCUTS.duplicate.label], edits: true },
    { does: "Copy", keys: [SHORTCUTS.copy.label] },
    { does: "Cut, paste", keys: [SHORTCUTS.cut.label, SHORTCUTS.paste.label], edits: true },
    { does: "Delete", keys: [SHORTCUTS.remove.label], edits: true },
    { does: "Switch off or on", keys: [SHORTCUTS.switch.label], edits: true },
    { does: "Undo, redo", keys: [SHORTCUTS.undo.label, SHORTCUTS.redo.label], edits: true },
    { does: "Menu", keys: ["Right-click", "Shift+F10"], edits: true },
  ] },
  { title: "Choosing", rows: [
    { does: "One step", keys: ["Click", "Enter"] },
    { does: "More steps", keys: ["Shift+click", "Shift+drag"] },
    { does: "Every step", keys: [SHORTCUTS.selectAll.label] },
    { does: "Let go", keys: ["Esc"] },
  ] },
  { title: "View", rows: [
    { does: "Whole graph", keys: [SHORTCUTS.fit.label] },
    { does: "Readable size", keys: [SHORTCUTS.readable.label] },
    { does: "Zoom", keys: ["+", "−", "Scroll"] },
    { does: "Move chosen steps", keys: ["Arrow keys"], edits: true },
  ] },
  { title: "Notes", rows: [
    { does: "Add a note", keys: [SHORTCUTS.note.label], edits: true },
    { does: "Change a note", keys: ["Double-click", "Enter"], edits: true },
    { does: "Keep, give up", keys: [SHORTCUTS.keep.label, "Esc"], edits: true },
  ] },
];
