import type { SourceAppearance } from "@/types/source-appearance";
import type { SystemDocument } from "@/types/system";
import type { ExplorerNode } from "./navigationIndex";
import { collectionByKind, validateSystemDocument } from "./systemDocument";

/** One identity across every tree context, signal list, and saved export. */
export function setSourceAppearance(document: SystemDocument, node: ExplorerNode, appearance?: SourceAppearance): SystemDocument {
  const kind = node.entityKind;
  if (kind && node.objectId) {
    const collection = collectionByKind[kind];
    if (!document[collection].some(item => item.id === node.objectId)) throw new Error("This source no longer exists.");
    return validateSystemDocument({ ...document, [collection]: document[collection].map(item =>
      item.id === node.objectId ? { ...item, appearance } : item) });
  }
  if (node.kind === "topic" && node.connectionId && node.topic !== undefined) {
    const entries = (document.topic_appearances ?? []).filter(item => item.broker_id !== node.connectionId || item.topic !== node.topic);
    if (appearance && Object.keys(appearance).length) entries.push({ broker_id: node.connectionId, topic: node.topic, appearance });
    return validateSystemDocument({ ...document, topic_appearances: entries });
  }
  throw new Error("This item does not have a customisable icon.");
}
