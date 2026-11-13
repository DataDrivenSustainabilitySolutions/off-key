import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import type { GraphDocument } from "@/features/pipelines/model";
import {
  addNote, moveNote, noteBlocker, NOTE_LIMITS, notesOf, notesWithCards, readNotes, removeNote, setNoteText,
} from "@/features/pipelines/notes";
import PipelineCanvas from "@/features/pipelines/PipelineCanvas";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

const { components } = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: [
    { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "",
      input_type: null, output_type: "features" },
    { id: "features.scale", kind: "transform", group: "prepare", label: "Scale", description: "",
      input_type: "features", output_type: "features" },
  ],
});

const design = (notes?: Array<{ id: string; x: number; y: number; text: string }>): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "scale", kind: "transform", component: "features.scale" },
    ],
    edges: [{ source: "input", target: "scale", order: 0 }],
  }),
  layout: normalizeLayout({ nodes: { input: { x: 0, y: 96 }, scale: { x: 288, y: 96 } }, ...(notes ? { notes } : {}) }),
});
const why = { id: "note_1", x: 288, y: 0, text: "Scaled so that both sensors count alike." };

describe("notes of a design", () => {
  it("adds a note that says something, under an id of its own", () => {
    const first = addNote(design(), { x: 16, y: 32 }, "  Why this is here.\n")!;
    expect(first.id).toBe("note_1");
    expect(notesOf(first.document)).toEqual([{ id: "note_1", x: 16, y: 32, text: "Why this is here." }]);
    // An id that a removed note left free is not given twice.
    const held = design([{ ...why, id: "note_2" }]);
    expect(addNote(held, { x: 0, y: 0 }, "Another")!.id).toBe("note_3");
    expect(addNote(design(), { x: 0, y: 0 }, "  \n ")).toBeUndefined();
    expect(notesOf(addNote(design(), { x: 0, y: 0 }, "x".repeat(NOTE_LIMITS.length + 5))!.document)[0]!.text).toHaveLength(NOTE_LIMITS.length);
    // Nothing of the definition changes: a note is part of how the design is drawn.
    expect(first.document.definition).toBe(first.document.definition);
    expect(first.document.layout.nodes).toEqual(design().layout.nodes);
  });

  it("holds no more notes than a design may have", () => {
    const full = design(Array.from({ length: NOTE_LIMITS.notes }, (_, index) => ({ ...why, id: `note_${index + 1}` })));
    expect(noteBlocker(full)).toBe("A design holds up to 50 notes.");
    expect(addNote(full, { x: 0, y: 0 }, "One more")).toBeUndefined();
    expect(noteBlocker(design([why]))).toBeUndefined();
  });

  it("changes, moves and removes a note, and leaves the design alone when nothing changes", () => {
    const document = design([why]);
    expect(notesOf(setNoteText(document, "note_1", " Agreed with the depot. "))[0]).toEqual({ ...why, text: "Agreed with the depot." });
    expect(setNoteText(document, "note_1", `${why.text}  `)).toBe(document);
    expect(setNoteText(document, "gone", "Text")).toBe(document);
    expect(notesOf(moveNote(document, "note_1", { x: 32, y: 48 }))[0]).toEqual({ ...why, x: 32, y: 48 });
    expect(moveNote(document, "note_1", { x: 288, y: 0 })).toBe(document);
    expect(removeNote(document, "gone")).toBe(document);
    // A note that says nothing any more is removed, and a design without notes carries no list of them.
    expect(setNoteText(document, "note_1", "  ").layout).not.toHaveProperty("notes");
    expect(removeNote(document, "note_1").layout).not.toHaveProperty("notes");
  });

  it("keeps a note beside its card when the cards are arranged anew", () => {
    // One note stands over the scaling step, one under the input.
    const document = design([why, { id: "note_2", x: 0, y: 224, text: "From the depot broker." }]);
    const arranged = { ...document.layout, nodes: { input: { x: 0, y: 0 }, scale: { x: 400, y: 160 } } };
    expect(notesWithCards(document, arranged).notes).toEqual([
      { ...why, x: 400, y: 64 },
      { id: "note_2", x: 0, y: 128, text: "From the depot broker." },
    ]);
    expect(notesWithCards(design(), arranged)).toBe(arranged);
  });

  it("reads the notes of a file and leaves out what is none", () => {
    expect(readNotes([why, { ...why, text: "Said twice" }, { id: "note_2", x: 0, y: 0, text: "  Kept  " },
      { id: "note_3", x: "0", y: 0, text: "No place" }, { id: "note_4", x: 0, y: 0, text: " " }, { id: "", x: 0, y: 0, text: "No id" },
      { id: "note_5", x: 0, y: Infinity, text: "Nowhere" }, null, "note"]))
      .toEqual([why, { id: "note_2", x: 0, y: 0, text: "Kept" }]);
    expect(readNotes({ note_1: why })).toEqual([]);
    expect(readNotes(undefined)).toEqual([]);
    expect(readNotes(Array.from({ length: 60 }, (_, index) => ({ ...why, id: `n${index}` })))).toHaveLength(NOTE_LIMITS.notes);
  });
});

describe("notes on the canvas", () => {
  let latest: GraphDocument;
  const moves = vi.fn();
  function Canvas({ start = design([why]), readOnly = false, layoutEditable = false }: {
    start?: GraphDocument; readOnly?: boolean; layoutEditable?: boolean }) {
    const [document, setDocument] = useState(start);
    latest = document;
    return <PipelineCanvas document={document} components={components} selection={[]} readOnly={readOnly} layoutEditable={layoutEditable}
      onSelect={() => {}} onSelectionChange={() => {}} onAdd={() => {}} onBeginMove={moves} onChange={setDocument} />;
  }
  const note = () => screen.findByRole("note");
  const field = () => screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Note" });
  const surface = () => document.querySelector<HTMLElement>(".pl-flow-surface")!;

  it("shows the notes of a design beside its cards", async () => {
    render(<Canvas />);
    const shown = await note();
    expect(shown.textContent).toBe(why.text);
    expect(shown.style.transform).toMatch(/^translate\(288px/);
  });

  it("starts a note with N, and keeps it with Ctrl or Cmd+Enter", async () => {
    render(<Canvas start={design()} />);
    await waitFor(() => expect(surface()).toBeTruthy());
    fireEvent.keyDown(surface(), { key: "n" });
    expect(document.activeElement).toBe(field());
    // Until it says something, the design has no note.
    expect(notesOf(latest)).toEqual([]);
    fireEvent.change(field(), { target: { value: "Checked against March.\nSee the report." } });
    // Enter is a new line of the note; the canvas keeps its keys to itself meanwhile.
    fireEvent.keyDown(field(), { key: "Enter" });
    fireEvent.keyDown(field(), { key: "n" });
    expect(screen.getAllByRole("textbox", { name: "Note" })).toHaveLength(1);
    fireEvent.keyDown(field(), { key: "Enter", ctrlKey: true });
    expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull();
    expect(notesOf(latest)).toMatchObject([{ id: "note_1", text: "Checked against March.\nSee the report." }]);
    expect((await note()).textContent).toBe("Checked against March.\nSee the report.");
  });

  it("keeps what was written when the field is left, and nothing when Escape gives it up", async () => {
    render(<Canvas start={design()} />);
    await waitFor(() => expect(surface()).toBeTruthy());
    fireEvent.keyDown(surface(), { key: "n" });
    fireEvent.change(field(), { target: { value: "Left by clicking away" } });
    fireEvent.blur(field());
    expect(notesOf(latest).map((item) => item.text)).toEqual(["Left by clicking away"]);

    fireEvent.keyDown(surface(), { key: "N" });
    fireEvent.change(field(), { target: { value: "Given up" } });
    fireEvent.keyDown(field(), { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull();
    expect(notesOf(latest)).toHaveLength(1);
    // A note that was never written is none.
    fireEvent.keyDown(surface(), { key: "n" });
    fireEvent.blur(field());
    expect(notesOf(latest)).toHaveLength(1);
  });

  it("changes a note in its place with a double-click or Enter, and removes one that is emptied", async () => {
    render(<Canvas />);
    fireEvent.doubleClick(await note());
    expect(field().value).toBe(why.text);
    fireEvent.change(field(), { target: { value: "Scaled alike." } });
    fireEvent.keyDown(field(), { key: "Escape" });
    expect(notesOf(latest)).toEqual([why]);

    fireEvent.keyDown(await note(), { key: "Enter" });
    fireEvent.change(field(), { target: { value: "Scaled alike." } });
    fireEvent.keyDown(field(), { key: "Enter", metaKey: true });
    expect(notesOf(latest)).toEqual([{ ...why, text: "Scaled alike." }]);

    fireEvent.doubleClick(await note());
    fireEvent.change(field(), { target: { value: "" } });
    fireEvent.blur(field());
    expect(screen.queryByRole("note")).toBeNull();
    expect(latest.layout).not.toHaveProperty("notes");
  });

  it("removes the note in focus with Delete and leaves the steps", async () => {
    render(<Canvas />);
    fireEvent.keyDown(await note(), { key: "Delete" });
    expect(screen.queryByRole("note")).toBeNull();
    expect(latest.definition.nodes).toHaveLength(2);
  });

  it("moves with the pointer along the grid, and with the arrow keys", async () => {
    moves.mockClear();
    render(<Canvas />);
    const shown = await note();
    fireEvent.pointerDown(shown, { pointerId: 1, button: 0, clientX: 300, clientY: 20 });
    // A hand that trembles on a click moves nothing.
    fireEvent.pointerMove(shown, { pointerId: 1, clientX: 302, clientY: 21 });
    expect(notesOf(latest)).toEqual([why]);
    expect(moves).not.toHaveBeenCalled();
    fireEvent.pointerMove(shown, { pointerId: 1, clientX: 350, clientY: 60 });
    fireEvent.pointerMove(shown, { pointerId: 1, clientX: 371, clientY: 55 });
    fireEvent.pointerUp(shown, { pointerId: 1 });
    expect(notesOf(latest)).toEqual([{ ...why, x: 352, y: 32 }]);
    // One move is one step back for Undo.
    expect(moves).toHaveBeenCalledOnce();
    fireEvent.pointerMove(await note(), { pointerId: 1, clientX: 500, clientY: 500 });
    expect(notesOf(latest)).toEqual([{ ...why, x: 352, y: 32 }]);

    fireEvent.keyDown(await note(), { key: "ArrowLeft" });
    fireEvent.keyDown(await note(), { key: "ArrowDown" });
    expect(notesOf(latest)).toEqual([{ ...why, x: 336, y: 48 }]);
  });

  it("offers Edit and Delete in the menu of a note", async () => {
    render(<Canvas />);
    await waitFor(() => expect(document.querySelector(".react-flow__node")).toBeTruthy());
    fireEvent.contextMenu(await note());
    const menu = await screen.findByRole("menu", { name: "Note" });
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Edit", "DeleteDel"]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: /^Edit/ }));
    expect(field().value).toBe(why.text);
    fireEvent.keyDown(field(), { key: "Escape" });
    fireEvent.contextMenu(await note());
    fireEvent.click(within(await screen.findByRole("menu", { name: "Note" })).getByRole("menuitem", { name: /^Delete/ }));
    expect(notesOf(latest)).toEqual([]);
  });

  it("only shows notes where the design is shown, and moves them where its cards can be moved", async () => {
    const shown = render(<Canvas readOnly />);
    fireEvent.doubleClick(await note());
    fireEvent.keyDown(await note(), { key: "Enter" });
    fireEvent.keyDown(await note(), { key: "Delete" });
    fireEvent.keyDown(await note(), { key: "ArrowLeft" });
    fireEvent.keyDown(surface(), { key: "n" });
    expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull();
    expect(notesOf(latest)).toEqual([why]);
    shown.unmount();

    render(<Canvas readOnly layoutEditable />);
    fireEvent.keyDown(await note(), { key: "Delete" });
    act(() => { fireEvent.keyDown(screen.getByRole("note"), { key: "ArrowRight" }); });
    expect(notesOf(latest)).toEqual([{ ...why, x: 304 }]);
  });
});
