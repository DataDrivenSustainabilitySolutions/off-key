import { createContext, type ReactNode } from "react";
import type { Link } from "./model";

/** What a wire offers besides its route. The canvas owns the state; each wire renders it. */
export type WireActions = {
  /** The wire whose step menu is open. */
  open?: string;
  setOpen: (id?: string) => void;
  /** Pointer presence on a wire's label, which React Flow does not report for its path. */
  hover: (id?: string) => void;
  /** The steps that can be inserted on a link. */
  menu: (link: Link) => ReactNode;
};

export const WireActionsContext = createContext<WireActions | undefined>(undefined);
