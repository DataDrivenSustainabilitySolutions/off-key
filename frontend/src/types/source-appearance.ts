export const SOURCE_COLORS = ["slate", "sage", "teal", "blue", "lavender", "ochre", "clay", "rose"] as const;
type SourceColor = typeof SOURCE_COLORS[number];

/** Stable icon names, never URLs or SVG markup. Unknown names use the kind's default. */
export type SourceAppearance = { icon?: string; color?: SourceColor };
export type TopicAppearance = { broker_id: string; topic: string; appearance: SourceAppearance };
