import "./brand-pattern.css";

/** The faint brand weave at the bottom of the workspace and the sign-in pages; decoration only. */
export function BrandPattern({ className }: { className?: string }) {
  return <div className={className ? `brand-pattern ${className}` : "brand-pattern"} aria-hidden="true" />;
}
