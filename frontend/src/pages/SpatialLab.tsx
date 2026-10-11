import { useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { ConfiguredSystemWorkspace } from "@/features/spatial/ConfiguredSystemWorkspace";
import SpatialTelemetryDemo from "./SpatialTelemetryDemo";

/** A saved system is the default. Public telemetry and the simulator stay optional previews. */
export default function SpatialLab() {
  const { userId } = useAuth();
  const [preview, setPreview] = useState<"demo" | "hsl">();
  return preview ? (
    <SpatialTelemetryDemo
      key={`${userId ?? "local"}:${preview}`}
      initialSource={preview}
      onReturn={() => setPreview(undefined)}
    />
  ) : (
    <ConfiguredSystemWorkspace key={userId ?? "local"} onPreview={setPreview} />
  );
}
