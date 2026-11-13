import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { useRef, useState, type ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { copySteps, holdSteps } from "@/features/pipelines/clipboard";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import { removeElements, type GraphDocument } from "@/features/pipelines/model";
import type PipelineCanvas from "@/features/pipelines/PipelineCanvas";
import { PipelineShortcuts } from "@/features/pipelines/PipelineShortcuts";
import { PipelineWorkbench } from "@/features/pipelines/PipelineWorkbench";
import { SHORTCUTS } from "@/features/pipelines/shortcuts";
import { useGraphEditor } from "@/features/pipelines/useGraphEditor";
import { useStepShortcuts } from "@/features/pipelines/useStepShortcuts";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

// The canvas is stood in for, so a test chooses steps the way the canvas reports it.
let canvas: ComponentProps<typeof PipelineCanvas>;
vi.mock("@/features/pipelines/PipelineCanvas", () => ({
  default: (props: ComponentProps<typeof PipelineCanvas>) => { canvas = props; return <div aria-label="Pipeline graph" />; },
}));

const catalog = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: [
    { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "",
      input_type: null, output_type: "features" },
    { id: "features.passthrough", kind: "transform", group: "route", label: "Pass through", description: "",
      input_type: "features", output_type: "features" },
    { id: "detector:a", kind: "detector", group: "detector", label: "Detector A", description: "",
      input_type: "features", output_type: "scores" },
  ],
});

const design = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "pass", kind: "transform", component: "features.passthrough" },
      { id: "detector", kind: "detector", component: "detector:a" },
    ],
    edges: [{ source: "input", target: "pass", order: 0 }, { source: "pass", target: "detector", order: 0 }],
  }),
  layout: normalizeLayout({ nodes: { input: { x: 0, y: 0 }, pass: { x: 288, y: 0 }, detector: { x: 576, y: 0 } } }),
});

/** The workbench as a screen holds it: the step in focus in the editor, the panel beside it. */
function Composer() {
  const [document, setDocument] = useState(design);
  const editor = useGraphEditor({ document, onChange: setDocument, components: catalog.components });
  return <PipelineWorkbench catalog={catalog} document={document} selected={editor.selected} onSelect={editor.select}
    onChange={editor.commit} onAdd={editor.add} />;
}

const panel = () => screen.queryByRole("heading", { name: "Step settings" });
const picker = () => screen.getByRole<HTMLSelectElement>("combobox", { name: "Selected step" });

describe("choosing several steps", () => {
  beforeEach(() => { render(<Composer />); });

  it("opens the settings for one step and none for steps gathered together", () => {
    act(() => canvas.onSelect("pass"));
    expect(canvas.selection).toEqual(["pass"]);
    expect(picker().value).toBe("pass");
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));

    act(() => canvas.onSelectionChange(["pass", "detector"]));
    expect(canvas.selection).toEqual(["pass", "detector"]);
    // The step that was in focus stays in focus, and no panel opens.
    expect(canvas.selected).toBe("pass");
    expect(panel()).toBeNull();
  });

  it("names the chosen steps where one step would show its settings, and leads to each", () => {
    act(() => canvas.onSelectionChange(["input", "detector"]));
    expect(canvas.selected).toBe("detector");
    fireEvent.click(screen.getByRole("button", { name: "Step settings" }));
    expect(picker().value).toBe("");
    expect(picker().selectedOptions[0]!.textContent).toBe("2 steps");
    const chosen = screen.getByRole("list", { name: "Chosen steps" });
    expect(within(chosen).getAllByRole("button").map((button) => button.textContent)).toEqual(["Aligned inputs", "Detector A"]);
    expect(screen.getByText("They move, copy and delete together. Choose one for its settings.")).toBeTruthy();

    fireEvent.click(within(chosen).getByRole("button", { name: "Aligned inputs" }));
    expect(canvas.selection).toEqual(["input"]);
    expect(picker().value).toBe("input");
  });

  it("puts the last gathered step in focus when the one that was has left, and lets go of all at once", () => {
    act(() => canvas.onSelect("pass"));
    act(() => canvas.onSelectionChange(["pass", "detector", "input"]));
    act(() => canvas.onSelectionChange(["detector", "input"]));
    expect(canvas.selected).toBe("input");
    expect(canvas.selection).toEqual(["detector", "input"]);
    // One step left of a group is that step, with the panel as it was.
    act(() => canvas.onSelectionChange(["detector"]));
    expect(canvas.selection).toEqual(["detector"]);
    expect(canvas.selected).toBe("detector");

    act(() => canvas.onSelect("pass"));
    expect(panel()).not.toBeNull();
    act(() => canvas.onSelectionChange([]));
    expect(canvas.selection).toEqual([]);
    // Settings do not stay open with no step to show.
    expect(panel()).toBeNull();
  });

  it("lets a group go when another step comes into focus, and forgets steps that are removed", () => {
    act(() => canvas.onSelectionChange(["input", "pass", "detector"]));
    act(() => canvas.onChange(removeElements(canvas.document, { nodeIds: ["pass"] })));
    expect(canvas.selection).toEqual(["input", "detector"]);
    // A step added from the menu is in focus alone.
    act(() => canvas.onAdd("features.passthrough"));
    expect(canvas.selection).toEqual([canvas.selected]);
    expect(canvas.selected).toMatch(/^features_passthrough/);
  });
});

describe("keys for steps", () => {
  const fragment = copySteps(design(), ["pass"])!;
  const text = holdSteps(fragment);
  const commands = { copy: vi.fn(), paste: vi.fn(), duplicate: vi.fn(), selectAll: vi.fn(), switch: vi.fn() };
  /** A clipboard event as a browser sends it; jsdom has none of its own. */
  const clipboard = (type: "copy" | "cut" | "paste", target: EventTarget, held = "") => {
    const data = { held, setData: (_format: string, value: string) => { data.held = value; }, getData: () => data.held };
    const event = Object.assign(new Event(type, { bubbles: true, cancelable: true }), { clipboardData: data });
    target.dispatchEvent(event);
    return { data, prevented: event.defaultPrevented };
  };
  const mount = () => {
    const field = document.body.appendChild(document.createElement("input"));
    const graph = document.body.appendChild(document.createElement("div"));
    const view = renderHook(() => { const surface = useRef(graph); useStepShortcuts(surface, commands); });
    return { field, graph, unmount: () => { view.unmount(); field.remove(); graph.remove(); } };
  };
  beforeEach(() => {
    for (const command of Object.values(commands)) command.mockReset();
    commands.copy.mockReturnValue(text);
    commands.duplicate.mockReturnValue(true);
    commands.selectAll.mockReturnValue(true);
    commands.switch.mockReturnValue(true);
  });

  it("writes the chosen steps to the clipboard on copy and cut, and reads them back on paste", () => {
    const { unmount } = mount();
    const copied = clipboard("copy", document.body);
    expect(commands.copy).toHaveBeenLastCalledWith(false);
    expect([copied.data.held, copied.prevented]).toEqual([text, true]);
    expect(clipboard("cut", document.body).prevented).toBe(true);
    expect(commands.copy).toHaveBeenLastCalledWith(true);

    expect(clipboard("paste", document.body, text).prevented).toBe(true);
    expect(commands.paste).toHaveBeenCalledExactlyOnceWith(fragment);
    unmount();
  });

  it("leaves other text, and nothing to copy, to the browser", () => {
    const { unmount } = mount();
    expect(clipboard("paste", document.body, "Charger A").prevented).toBe(false);
    expect(commands.paste).not.toHaveBeenCalled();
    commands.copy.mockReturnValue(undefined);
    const copied = clipboard("copy", document.body);
    expect([copied.data.held, copied.prevented]).toEqual(["", false]);
    unmount();
  });

  it("leaves a text field its own copy, paste and keys", () => {
    const { field, unmount } = mount();
    expect(clipboard("copy", field).prevented).toBe(false);
    expect(clipboard("paste", field, text).prevented).toBe(false);
    expect(fireEvent.keyDown(field, { key: "d", ctrlKey: true })).toBe(true);
    expect(fireEvent.keyDown(field, { key: "a", ctrlKey: true })).toBe(true);
    for (const command of Object.values(commands)) expect(command).not.toHaveBeenCalled();
    unmount();
  });

  it("duplicates with Ctrl or Cmd+D, and chooses every step with Ctrl or Cmd+A on the canvas only", () => {
    const { graph, unmount } = mount();
    const button = document.body.appendChild(document.createElement("button"));
    // A handled key does not also reach the browser, which would add a bookmark or mark the page.
    expect(fireEvent.keyDown(button, { key: "d", ctrlKey: true })).toBe(false);
    expect(fireEvent.keyDown(document.body, { key: "D", metaKey: true })).toBe(false);
    expect(commands.duplicate).toHaveBeenCalledTimes(2);
    expect(fireEvent.keyDown(graph, { key: "a", ctrlKey: true })).toBe(false);
    expect(fireEvent.keyDown(document.body, { key: "a", metaKey: true })).toBe(false);
    expect(commands.selectAll).toHaveBeenCalledTimes(2);
    // Elsewhere on the page the key marks its text.
    expect(fireEvent.keyDown(button, { key: "a", ctrlKey: true })).toBe(true);
    expect(commands.selectAll).toHaveBeenCalledTimes(2);
    // With nothing to duplicate the key stays the browser's, as it does with other keys held.
    commands.duplicate.mockReturnValue(false);
    expect(fireEvent.keyDown(document.body, { key: "d", ctrlKey: true })).toBe(true);
    expect(fireEvent.keyDown(document.body, { key: "d", ctrlKey: true, shiftKey: true })).toBe(true);
    expect(commands.duplicate).toHaveBeenCalledTimes(3);
    // Ctrl or Cmd+B switches the chosen steps off or on, and stays the browser's with none chosen.
    expect(fireEvent.keyDown(document.body, { key: "b", ctrlKey: true })).toBe(false);
    expect(fireEvent.keyDown(graph, { key: "B", metaKey: true })).toBe(false);
    commands.switch.mockReturnValue(false);
    expect(fireEvent.keyDown(document.body, { key: "b", ctrlKey: true })).toBe(true);
    expect(commands.switch).toHaveBeenCalledTimes(3);
    button.remove();
    unmount();
  });
});

describe("the list of keys", () => {
  const rows = () => within(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).getAllByRole("term").map((term) => term.textContent);
  const keysOf = (does: string) => {
    const term = within(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).getByText(does, { selector: "dt" });
    return [...term.parentElement!.querySelectorAll("kbd")].map((key) => key.textContent);
  };

  it("names every key and gesture beside what it does, with the keys the menus show", () => {
    render(<PipelineShortcuts open onOpenChange={() => {}} />);
    expect(rows()).toEqual(["Add a step", "Rename", "Duplicate", "Copy", "Cut, paste", "Delete", "Switch off or on",
      "Undo, redo", "Menu", "One step", "More steps", "Every step", "Let go", "Whole graph", "Readable size", "Zoom", "Move chosen steps",
      "Add a note", "Change a note", "Keep, give up"]);
    expect(keysOf("Keep, give up")).toEqual([SHORTCUTS.keep.label, "Esc"]);
    expect(keysOf("Add a step")).toEqual(["A", "Double-click"]);
    expect(keysOf("Cut, paste")).toEqual([SHORTCUTS.cut.label, SHORTCUTS.paste.label]);
    expect(keysOf("More steps")).toEqual(["Shift+click", "Shift+drag"]);
    expect(SHORTCUTS.duplicate).toEqual({ label: "Ctrl+D", aria: "Control+D" });
    expect(SHORTCUTS.redo).toEqual({ label: "Shift+Ctrl+Z", aria: "Shift+Control+Z" });
  });

  it("leaves out what changes a design where the design is only shown", () => {
    render(<PipelineShortcuts open onOpenChange={() => {}} readOnly />);
    expect(rows()).toEqual(["Copy", "One step", "More steps", "Every step", "Let go", "Whole graph", "Readable size", "Zoom"]);
  });

  it("opens from its button and says so to its caller", () => {
    const changed = vi.fn();
    render(<PipelineShortcuts open={false} onOpenChange={changed} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Keyboard shortcuts" }));
    expect(changed).toHaveBeenCalledExactlyOnceWith(true);
  });
});
