import { useEffect, useRef } from "react";
import { clientLogger } from "@/lib/logger";
import { SpatialScene, type SpatialCanvasProps } from "./SpatialScene";

export function SpatialCanvas(props: SpatialCanvasProps) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<SpatialScene | null>(null);
  const initial = useRef(props);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    try {
      scene.current = new SpatialScene(element, initial.current);
    } catch (error) {
      const message = document.createElement("div");
      message.className = "spatial-webgl-fallback";
      message.setAttribute("role", "status");
      message.textContent =
        "The spatial view needs WebGL. You can still inspect every sensor and its charts from the object list.";
      Object.assign(message.style, {
        maxWidth: "360px",
        margin: "120px auto",
        padding: "24px",
        color: "#59687a",
        font: "14px/1.7 system-ui",
      });
      element.replaceChildren(message);
      clientLogger.warn({
        event: "spatial.rendering_unavailable",
        message: "Spatial rendering unavailable",
        error,
      });
    }
    return () => {
      scene.current?.dispose();
      scene.current = null;
      element.replaceChildren();
    };
  }, []);

  useEffect(() => {
    scene.current?.update(props);
  });

  return (
    <div
      ref={host}
      className="spatial-canvas"
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
      }}
    />
  );
}
