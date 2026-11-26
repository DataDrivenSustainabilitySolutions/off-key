import { useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { Link } from "react-router-dom";
import { nextOrder, sortRows, type SortOrder } from "./listing";

export type ListColumn<Row> = {
  id: string;
  label: string;
  /** Right-aligned with tabular figures; ordered largest first on the first press. */
  numeric?: boolean;
  /** Shown on wide screens only; a phone reads it from the name's line or not at all. */
  wide?: boolean;
  /** The value the column orders by; a column without one cannot be ordered. */
  sort?: (row: Row) => string | number;
  cell: (row: Row) => ReactNode;
  /** The unit a phone shows after the value, where the header is hidden. */
  unit?: (row: Row) => string;
};

/**
 * One Dojo list: the name links to the row's page and its whole row is the target, columns order
 * on their header, and a checkbox per row picks rows for the selection bar.
 */
export function ListTable<Row>({ label, rows, rowId, name, note, href, columns, initial, selection }: {
  label: string;
  rows: Row[];
  rowId: (row: Row) => string;
  name: (row: Row) => string;
  note?: (row: Row) => ReactNode;
  href: (row: Row) => string;
  columns: ListColumn<Row>[];
  initial: SortOrder;
  selection?: { chosen: ReadonlySet<string>; toggle: (id: string, on: boolean) => void; setAll: (ids: string[], on: boolean) => void };
}) {
  const [order, setOrder] = useState(initial);
  const sortable = [{ id: "name", value: name }, ...columns.flatMap(column => column.sort ? [{ id: column.id, value: column.sort }] : [])];
  const sorted = sortRows(rows, sortable, order);
  const ids = rows.map(rowId);
  const chosen = ids.filter(id => selection?.chosen.has(id)).length;
  const header = (id: string, text: string, numeric: boolean, can: boolean) => {
    const active = order.column === id;
    if (!can) return text;
    const Arrow = active && order.descending ? ArrowDown : ArrowUp;
    return <button type="button" className="dj-sort" onClick={() => setOrder(nextOrder(order, id, numeric))}>
      {text}<Arrow size={12} aria-hidden className={active ? undefined : "dj-sort-idle"} /></button>;
  };
  const sortState = (id: string) => order.column === id ? (order.descending ? "descending" : "ascending") : undefined;
  return <div className="dj-table-scroll"><table className={`dj-table dj-table--stack dj-list${selection ? " dj-list--select" : ""}`} aria-label={label}>
    <thead><tr>
      {selection && <th scope="col" className="dj-select"><label className="dj-check-box"><input type="checkbox"
        aria-label={`Select all ${label.toLowerCase()}`} checked={chosen > 0 && chosen === ids.length}
        ref={element => { if (element) element.indeterminate = chosen > 0 && chosen < ids.length; }}
        onChange={event => selection.setAll(ids, event.target.checked)} /><span className="dj-narrow-only">Select all</span></label></th>}
      <th scope="col" aria-sort={sortState("name")}>{header("name", "Name", false, true)}</th>
      {columns.map(column => <th key={column.id} scope="col" aria-sort={sortState(column.id)}
        className={[column.numeric && "dj-num", "dj-fit", column.wide && "dj-wide-only"].filter(Boolean).join(" ")}>
        {header(column.id, column.label, !!column.numeric, !!column.sort)}</th>)}
    </tr></thead>
    <tbody>{sorted.map(row => {
      const id = rowId(row);
      const on = !!selection?.chosen.has(id);
      return <tr key={id} className={on ? "dj-row-chosen" : undefined}>
        {selection && <td className="dj-select"><label className="dj-check-box"><input type="checkbox" checked={on}
          aria-label={`Select ${name(row)}`} onChange={event => selection.toggle(id, event.target.checked)} /></label></td>}
        <td className="dj-name"><Link to={href(row)}>{name(row)}</Link>{note?.(row)}</td>
        {columns.map(column => <td key={column.id}
          className={[column.numeric && "dj-num", "dj-fit", column.wide && "dj-wide-only"].filter(Boolean).join(" ")}>
          {column.cell(row)}{column.unit && <span className="dj-narrow-unit"> {column.unit(row)}</span>}</td>)}
      </tr>;
    })}</tbody>
  </table></div>;
}
