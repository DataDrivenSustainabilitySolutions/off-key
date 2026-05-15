import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const MONOGRAM_CELLS = Array.from({ length: 360 }, (_, index) => index);

interface AuthBackdropProps {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}

export function AuthBackdrop({
  children,
  className,
  contentClassName,
}: AuthBackdropProps) {
  return (
    <div
      className={cn(
        "auth-backdrop flex min-h-screen items-center justify-center px-4 py-8",
        className
      )}
    >
      <div className="auth-monogram-grid" aria-hidden="true">
        {MONOGRAM_CELLS.map((cell) => (
          <span className="auth-monogram" key={cell}>
            <svg
              className="auth-monogram-icon"
              viewBox="0 0 64 64"
              focusable="false"
            >
              <path
                className="auth-monogram-bolt"
                d="M35 8 20 34h12l-3 22 16-30H33l2-18Z"
              />
            </svg>
          </span>
        ))}
      </div>
      <div className={cn("relative z-10 w-full", contentClassName)}>
        {children}
      </div>
    </div>
  );
}
