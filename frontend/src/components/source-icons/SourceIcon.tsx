import type { CSSProperties } from "react";
import type { SourceAppearance } from "@/types/source-appearance";
import { sourceIcon, type SourceIconKind } from "./catalogue";
import "./source-icons.css";

/** Decorative identity; labels and live status remain separate and accessible. */
export function SourceIcon({ kind, appearance, size = 16, color }: {
  kind: SourceIconKind; appearance?: SourceAppearance; size?: number; color?: string;
}) {
  const { icon: Icon, id } = sourceIcon(kind, appearance?.icon);
  return <Icon className="source-icon" data-icon={id} data-color={appearance?.color} size={size} strokeWidth={2}
    style={{ "--source-icon-size": `${size}px`, ...(!appearance?.color && color ? { color } : {}) } as CSSProperties} aria-hidden="true" />;
}
