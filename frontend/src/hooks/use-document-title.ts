import { useEffect } from "react";

const APPLICATION_NAME = "Aberration";

/** Name the browser tab after the page, most specific part first. */
export function useDocumentTitle(...parts: Array<string | false | null | undefined>) {
  const title = [...parts.filter((part): part is string => !!part), APPLICATION_NAME].join(" · ");
  useEffect(() => { document.title = title; }, [title]);
}
