import { useEffect, useState } from "react";

/** About six pixels per mean; round the budget so small resizes do not refetch. */
export function useHistoryWidth() {
  const [node, ref] = useState<HTMLElement | null>(null);
  const [buckets, setBuckets] = useState(100);
  useEffect(() => {
    if (!node || typeof ResizeObserver === "undefined") return;
    const update = () => {
      const width = node.getBoundingClientRect().width;
      if (width) setBuckets(Math.max(20, Math.min(1000, Math.round((width - 60) / 120) * 20)));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  return { ref, buckets };
}
