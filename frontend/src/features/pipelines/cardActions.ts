import { createContext } from "react";

/** What a card offers besides its data. The canvas owns the state; each card renders it. */
export type CardActions = {
  /** Keep the title typed on a card, or drop it when Escape cancels. */
  finishRename: (id: string, title?: string) => void;
};

export const CardActionsContext = createContext<CardActions | undefined>(undefined);
