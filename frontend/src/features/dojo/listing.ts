import { useMemo, useState } from "react";

/** A column a list can be ordered by, with how to read its value from a row. */
export type SortColumn<Row> = { id: string; value: (row: Row) => string | number };
export type SortOrder = { column: string; descending: boolean };

/** Rows in the chosen order; text compares by locale, numbers by size, equal rows keep their order. */
export function sortRows<Row>(rows: Row[], columns: SortColumn<Row>[], order: SortOrder): Row[] {
  const column = columns.find(item => item.id === order.column);
  if (!column) return rows;
  const sign = order.descending ? -1 : 1;
  return rows.map((row, index) => ({ row, index })).sort((a, b) => {
    const left = column.value(a.row); const right = column.value(b.row);
    const difference = typeof left === "number" && typeof right === "number" ? left - right
      : String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
    return difference * sign || a.index - b.index;
  }).map(item => item.row);
}

/** The next order after a header is pressed: a new column starts with its natural direction, the same one flips. */
export function nextOrder(order: SortOrder, column: string, descendingFirst: boolean): SortOrder {
  return order.column === column ? { column, descending: !order.descending } : { column, descending: descendingFirst };
}

/** Ids chosen in a list. Ids that left the list drop out on their own. */
export function useSelection(ids: string[]) {
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const present = useMemo(() => new Set(ids.filter(id => chosen.has(id))), [ids, chosen]);
  return {
    chosen: present,
    toggle: (id: string, on: boolean) => setChosen(previous => {
      const next = new Set(previous);
      if (on) next.add(id); else next.delete(id);
      return next;
    }),
    setAll: (some: string[], on: boolean) => setChosen(previous => {
      const next = new Set(previous);
      for (const id of some) if (on) next.add(id); else next.delete(id);
      return next;
    }),
    clear: () => setChosen(new Set()),
  };
}
