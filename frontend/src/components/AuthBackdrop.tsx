import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface AuthBackdropProps {
  children: ReactNode;
  contentClassName?: string;
}

export function AuthBackdrop({
  children,
  contentClassName,
}: AuthBackdropProps) {
  return (
    <div className="auth-backdrop flex min-h-dvh items-center justify-center px-5 py-10">
      <div className="auth-monogram-pattern" aria-hidden="true" />
      <div className={cn("relative z-10 w-full", contentClassName)}>
        {children}
      </div>
    </div>
  );
}
