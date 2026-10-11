import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

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
        "auth-backdrop flex min-h-dvh items-center justify-center px-5 py-10",
        className
      )}
    >
      <div className="auth-monogram-pattern" aria-hidden="true" />
      <div className={cn("relative z-10 w-full", contentClassName)}>
        {children}
      </div>
    </div>
  );
}
