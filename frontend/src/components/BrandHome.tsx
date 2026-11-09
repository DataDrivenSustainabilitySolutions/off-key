import { Link } from "react-router-dom";

export function BrandHome({ variant = "mark", onNavigate }: { variant?: "mark" | "wordmark"; onNavigate?: () => void }) {
  const wordmark = variant === "wordmark";
  return (
    <Link className={`brand-home${wordmark ? " brand-home-wordmark" : ""}`} to="/" aria-label="Aberration home" title="Dashboard home" onClick={onNavigate}>
      <svg className={wordmark ? "brand-wordmark" : "brand-mark"} viewBox={wordmark ? "0 0 478 100" : "0 0 64 64"} aria-hidden="true" focusable="false">
        <use href={wordmark ? "/brand/wordmark.svg#wordmark" : "/brand/logo.svg#mark"} />
      </svg>
    </Link>
  );
}
