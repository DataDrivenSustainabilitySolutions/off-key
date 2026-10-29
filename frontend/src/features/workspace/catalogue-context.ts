import { createContext, useContext, type Dispatch, type RefObject, type SetStateAction } from "react";
import type { useSystemDocument } from "@/domain/system/useSystemDocument";
import type { SystemEntityKind, SystemDocument } from "@/types/system";
import type { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { ReadingHistoryCache } from "@/domain/readings/readingHistoryCache";
import type { ExplorerNode, NavigationIndex } from "@/domain/system/navigationIndex";
import type { ExplorerPreferences } from "./preferences";
import type { ListPosition } from "./ExplorerList";

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
  /** Live-only readings on the selection's brokers; the preview subscribes to all of them. */
  previewStreamIds: string[];
  /** Brokers connected live from the Sources overview; they stay in the live scope beside the selection. */
  liveBrokers: string[];
  setLiveBrokers: Dispatch<SetStateAction<string[]>>;
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
