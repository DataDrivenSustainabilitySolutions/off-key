import { useEffect } from "react";

const APPLICATION_NAME = "Aberration";

const compose = (parts: Array<string | false | null | undefined>) =>
  [...parts.filter((part): part is string => !!part), APPLICATION_NAME].join(" · ");

// An overlay above the page names the tab while it is open; the page's own title
// is kept underneath and returns when the overlay closes.
let pageTitle: string | null = null;
let overlayTitle: string | null = null;
const apply = () => { document.title = overlayTitle ?? pageTitle ?? APPLICATION_NAME; };

/** Name the browser tab after the page, most specific part first. */
export function useDocumentTitle(...parts: Array<string | false | null | undefined>) {
  const title = compose(parts);
  useEffect(() => { pageTitle = title; apply(); }, [title]);
}

/** Name the browser tab after an open overlay, or give it back to the page with nothing. */
export function useOverlayDocumentTitle(label: string | undefined) {
  useEffect(() => {
    if (!label) return;
    overlayTitle = compose([label]);
    apply();
    return () => { overlayTitle = null; apply(); };
  }, [label]);
}
