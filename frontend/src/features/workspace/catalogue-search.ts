import { createContext } from "react";

/** Opens and focuses the shared catalogue search from a workspace action. */
export const CatalogueSearchContext = createContext<(() => void) | null>(null);
