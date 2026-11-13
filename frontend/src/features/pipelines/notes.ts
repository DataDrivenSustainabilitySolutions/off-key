import type { PipelineLayout } from "./contracts";
import { snap, type GraphDocument } from "./model";
import { NODE_SIZE, nodePosition } from "./semantics";

/** A note on the canvas: a few lines beside the steps they are about. It is part of the layout, not of what runs. */
export type CanvasNote = NonNullable<PipelineLayout["notes"]>[number];

type Point = { x: number; y: number };

/** A note is as wide as a card, so notes and cards line up on the grid; it grows down with its text. */
export const NOTE_WIDTH = NODE_SIZE.width;
export const NOTE_LIMITS = { notes: 50, length: 2000 };

export const notesOf = (document: GraphDocument): CanvasNote[] => document.layout.notes ?? [];

/** Why a design cannot take another note; undefined when it can. */
export const noteBlocker = (document: GraphDocument) =>
  notesOf(document).length >= NOTE_LIMITS.notes ? `A design holds up to ${NOTE_LIMITS.notes} notes.` : undefined;

/** What a note says, as it is kept: without the space around it and within the length a note has. */
const noteText = (text: string) => text.trim().slice(0, NOTE_LIMITS.length);

const withNotes = (document: GraphDocument, notes: CanvasNote[]): GraphDocument => {
  const layout: PipelineLayout = { ...document.layout, notes };
  // A design without notes carries no list of them.
  if (!notes.length) delete layout.notes;
  return { ...document, layout };
};

/** Put a note on the canvas. Undefined when it would say nothing or the design holds no more. */
export function addNote(document: GraphDocument, at: Point, text: string): { document: GraphDocument; id: string } | undefined {
  const said = noteText(text);
  if (!said || noteBlocker(document)) return undefined;
  const notes = notesOf(document);
  let number = notes.length + 1;
  while (notes.some((note) => note.id === `note_${number}`)) number++;
  const id = `note_${number}`;
  return { document: withNotes(document, [...notes, { id, x: at.x, y: at.y, text: said }]), id };
}

/** Change what a note says; a note that says nothing any more is removed. */
export function setNoteText(document: GraphDocument, id: string, text: string): GraphDocument {
  const said = noteText(text);
  const notes = notesOf(document);
  const note = notes.find((item) => item.id === id);
  if (!note || note.text === said) return document;
  return withNotes(document, said ? notes.map((item) => (item.id === id ? { ...item, text: said } : item)) : notes.filter((item) => item.id !== id));
}

export function moveNote(document: GraphDocument, id: string, to: Point): GraphDocument {
  const notes = notesOf(document);
  const note = notes.find((item) => item.id === id);
  if (!note || (note.x === to.x && note.y === to.y)) return document;
  return withNotes(document, notes.map((item) => (item.id === id ? { ...item, x: to.x, y: to.y } : item)));
}

export const removeNote = (document: GraphDocument, id: string): GraphDocument =>
  notesOf(document).some((note) => note.id === id) ? withNotes(document, notesOf(document).filter((note) => note.id !== id)) : document;

/**
 * Notes after the cards were arranged anew: each goes with the card that stood nearest to it,
 * so a note stays beside the step it is about.
 */
export function notesWithCards(document: GraphDocument, arranged: PipelineLayout): PipelineLayout {
  const notes = notesOf(document);
  const cards = document.definition.nodes.map((node, index) => ({ id: node.id, ...nodePosition(document.layout, node.id, index) }));
  if (!notes.length || !cards.length) return arranged;
  const centre = (box: Point, height: number) => ({ x: box.x + NODE_SIZE.width / 2, y: box.y + height / 2 });
  return { ...arranged, notes: notes.map((note) => {
    const from = centre(note, 0);
    const near = cards.reduce((best, card) => {
      const at = centre(card, NODE_SIZE.height);
      const far = Math.hypot(at.x - from.x, at.y - from.y);
      return far < best.far ? { card, far } : best;
    }, { card: cards[0]!, far: Infinity }).card;
    const now = arranged.nodes[near.id];
    return now ? { ...note, x: snap(note.x + now.x - near.x), y: snap(note.y + now.y - near.y) } : note;
  }) };
}

/** The notes a file holds, read leniently: what is no note is left out, as is a second note with an id. */
export function readNotes(value: unknown): CanvasNote[] {
  if (!Array.isArray(value)) return [];
  const notes: CanvasNote[] = [];
  for (const item of value as unknown[]) {
    if (typeof item !== "object" || item === null) continue;
    const { id, x, y, text } = item as Record<string, unknown>;
    const said = typeof text === "string" ? noteText(text) : "";
    if (typeof id !== "string" || !id || id.length > 64 || typeof x !== "number" || typeof y !== "number"
      || !Number.isFinite(x) || !Number.isFinite(y) || !said || notes.some((note) => note.id === id)) continue;
    notes.push({ id, x, y, text: said });
    if (notes.length === NOTE_LIMITS.notes) break;
  }
  return notes;
}
