import { useEffect, useRef, useState, type MouseEvent } from "react";
import { useStore, ViewportPortal } from "@xyflow/react";
import { snap } from "./model";
import { NOTE_LIMITS, NOTE_WIDTH, type CanvasNote } from "./notes";
import { GRID_STEP } from "./semantics";

type Point = { x: number; y: number };

/** The note being written: one of the design's, or a new one at a place. */
export type NoteWriting = { id: string } | { at: Point };

type Props = {
  notes: CanvasNote[];
  writing?: NoteWriting;
  /** Notes can be written, changed and removed. */
  editable: boolean;
  /** Notes can be moved, as cards can. */
  movable: boolean;
  snapToGrid: boolean;
  onWrite: (id: string) => void;
  /** What the note says now, or undefined when the writing was given up; whether a key ended it. */
  onKeep: (text: string | undefined, byKey: boolean) => void;
  onMoveStart: () => void;
  onMove: (id: string, to: Point) => void;
  onRemove: (id: string) => void;
  onMenu: (event: MouseEvent, id: string) => void;
};

const at = (point: Point) => ({ transform: `translate(${point.x}px, ${point.y}px)`, width: NOTE_WIDTH });

/** A note while it is written: a field that grows with its text, in the note's place. */
function Writing({ place, text, onKeep }: { place: Point; text: string; onKeep: Props["onKeep"] }) {
  const [value, setValue] = useState(text);
  const field = useRef<HTMLTextAreaElement>(null);
  // Leaving the field keeps the text once, however the field is left.
  const done = useRef(false);
  useEffect(() => {
    const element = field.current;
    if (!element) return;
    element.focus({ preventScroll: true });
    element.setSelectionRange(element.value.length, element.value.length);
  }, []);
  const finish = (kept: boolean, byKey: boolean) => {
    if (done.current) return;
    done.current = true;
    onKeep(kept ? value : undefined, byKey);
  };
  return <div className="pl-note is-writing nodrag nopan nowheel" style={at(place)}>
    <div className="pl-note-grow" data-value={value}>
      <textarea ref={field} aria-label="Note" placeholder="Write a note" value={value} maxLength={NOTE_LIMITS.length} rows={2}
        aria-keyshortcuts="Control+Enter Escape"
        onChange={(event) => setValue(event.target.value)}
        onBlur={() => finish(true, false)}
        onKeyDown={(event) => {
          // Enter starts a new line; Ctrl or Cmd with Enter keeps the note, Escape leaves it as it was.
          if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(false, true); }
          else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); finish(true, true); }
        }} />
    </div>
  </div>;
}

function Note({ note, editable, movable, snapToGrid, onWrite, onMoveStart, onMove, onRemove, onMenu }:
  Omit<Props, "notes" | "writing" | "onKeep"> & { note: CanvasNote }) {
  const zoom = useStore((state) => state.transform[2]);
  const held = useRef<{ pointer: number; x: number; y: number; from: Point; moved: boolean }>(undefined);
  const place = (value: number) => (snapToGrid ? snap(value) : Math.round(value));
  return <div className={`pl-note nodrag nopan${movable ? " is-movable" : ""}`} role="note" aria-label="Note" tabIndex={0}
    data-note={note.id} style={at(note)}
    onDoubleClick={editable ? () => onWrite(note.id) : undefined}
    onContextMenu={editable ? (event) => onMenu(event, note.id) : undefined}
    onKeyDown={(event) => {
      if (event.target !== event.currentTarget || event.ctrlKey || event.metaKey || event.altKey) return;
      const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
      if (editable && (event.key === "Enter" || event.key === "F2")) onWrite(note.id);
      else if (editable && (event.key === "Delete" || event.key === "Backspace")) onRemove(note.id);
      else if (movable && step) {
        onMoveStart();
        onMove(note.id, { x: note.x + step[0]! * GRID_STEP, y: note.y + step[1]! * GRID_STEP });
      } else return;
      // The key was for the note: the canvas does not also delete or move the chosen steps.
      event.preventDefault();
      event.stopPropagation();
    }}
    onPointerDown={(event) => {
      if (!movable || event.button !== 0) return;
      held.current = { pointer: event.pointerId, x: event.clientX, y: event.clientY, from: { x: note.x, y: note.y }, moved: false };
      event.currentTarget.setPointerCapture?.(event.pointerId);
    }}
    onPointerMove={(event) => {
      const drag = held.current;
      if (!drag || drag.pointer !== event.pointerId) return;
      const [across, down] = [event.clientX - drag.x, event.clientY - drag.y];
      // A click or a double-click is no move.
      if (!drag.moved && Math.hypot(across, down) < 4) return;
      if (!drag.moved) { drag.moved = true; onMoveStart(); }
      onMove(note.id, { x: place(drag.from.x + across / zoom), y: place(drag.from.y + down / zoom) });
    }}
    onPointerUp={() => { held.current = undefined; }}
    onPointerCancel={() => { held.current = undefined; }}>
    {note.text}
  </div>;
}

/**
 * The notes of a design, drawn on the canvas with its cards. A note is text beside the steps it is
 * about: it has no ports, takes no part in choosing steps, and belongs to the layout.
 */
export function PipelineNotes({ notes, writing, onKeep, ...rest }: Props) {
  return <ViewportPortal>
    {notes.map((note) => writing && "id" in writing && writing.id === note.id
      ? <Writing key={note.id} place={note} text={note.text} onKeep={onKeep} />
      : <Note key={note.id} note={note} {...rest} />)}
    {writing && "at" in writing && <Writing key="new" place={writing.at} text="" onKeep={onKeep} />}
  </ViewportPortal>;
}
