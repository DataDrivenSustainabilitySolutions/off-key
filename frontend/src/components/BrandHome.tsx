import { Link } from "react-router-dom";

export function BrandHome() {
  return (
    <Link className="brand-home" to="/" aria-label="Aberration home" title="Dashboard home">
      <svg className="brand-mark" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
        <use href="/brand/logo.svg#mark" />
      </svg>
    </Link>
  );
}
