import { createContext, useContext, type Dispatch, type RefObject, type SetStateAction } from "react";
import type { useSystemDocument } from "../catalogue/useSystemDocument";
import type { SystemEntityKind, SystemDocument } from "../catalogue/systemTypes";
import type { SystemLiveTelemetry } from "../catalogue/systemLiveTelemetry";
import type { ReadingHistoryCache } from "../explorer/readingHistoryCache";
import type { ExplorerNode, NavigationIndex } from "../explorer/navigationIndex";
import type { ExplorerPreferences } from "../explorer/preferences";
import type { ListPosition } from "../explorer/ExplorerList";

export type CatalogueDialog = { kind: "settings" } | { kind: "editor"; entityKind: SystemEntityKind; id?: string; key: number } | null;

export type CatalogueContextValue = {
  system: ReturnType<typeof useSystemDocument>;
  document: SystemDocument;
  index: NavigationIndex;
  selected?: ExplorerNode;
  selectionRequested: boolean;
  selectionMissing: boolean;
  streamIds?: string[];
  liveStreamIds: string[];
  telemetry: SystemLiveTelemetry;
  history: ReadingHistoryCache;
  preferences: ExplorerPreferences;
  setPreferences: Dispatch<SetStateAction<ExplorerPreferences>>;
  stored: boolean;
  scopeKey: string;
  query: string;
  setQuery: (value: string) => void;
  positions: Map<string, ListPosition>;
  browse: (key: string) => void;
  back: () => void;
  selectSource: (node?: ExplorerNode | null) => void;
  sectionHref: (path: string) => string;
  toggleFavourite: (kind: "service" | "reading", id: string) => void;
  editingLocked: boolean;
  setEditingLocked: Dispatch<SetStateAction<boolean>>;
  dialog: CatalogueDialog;
  dialogOrigin: RefObject<HTMLElement | null>;
  openSettings: () => void;
  openEditor: (kind: SystemEntityKind, id?: string) => void;
  closeDialog: () => void;
};

export const CatalogueContext = createContext<CatalogueContextValue | null>(null);
export const useOptionalCatalogue = () => useContext(CatalogueContext);
export function useCatalogue() {
  const context = useOptionalCatalogue();
  if (!context) throw new Error("Catalogue content must be rendered inside the application workspace.");
  return context;
}
