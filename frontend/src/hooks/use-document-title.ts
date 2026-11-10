import { useEffect } from "react";

const APPLICATION_NAME = "Aberration";
type TitlePart = string | false | null | undefined;

function compose(parts: TitlePart[]) {
  const labels = parts.filter((part): part is string => typeof part === "string")
    .map(part => part.replace(/\s+/g, " ").trim()).filter(Boolean);
  if (!labels.length) return undefined;
  return [...new Set(labels.filter(label => label !== APPLICATION_NAME)), APPLICATION_NAME].join(" · ");
}

// Detail views take precedence over their workspace, and settings over both.
// Keep mounted owners so closing a view restores the latest underlying title.
const titles = new Map<symbol, { title: string; priority: number }>();
function apply() {
  let current: { title: string; priority: number } | undefined;
  for (const entry of titles.values()) {
    if (!current || entry.priority >= current.priority) current = entry;
  }
  document.title = current?.title ?? APPLICATION_NAME;
}

function useTitle(priority: number, parts: TitlePart[]) {
  const title = compose(parts);
  useEffect(() => {
    if (!title) return;
    const owner = Symbol();
    titles.set(owner, { title, priority });
    apply();
    return () => { titles.delete(owner); apply(); };
  }, [priority, title]);
}

/** Name the browser tab after the page, most specific part first. */
export function useDocumentTitle(...parts: TitlePart[]) {
  useTitle(0, parts);
}

/** A named detail view overrides its workspace, including during parent updates. */
export function useDetailDocumentTitle(...parts: TitlePart[]) {
  useTitle(1, parts);
}

/** Name the browser tab after an open overlay, or give it back to the page with nothing. */
export function useOverlayDocumentTitle(label: string | undefined) {
  useTitle(2, [label]);
}
