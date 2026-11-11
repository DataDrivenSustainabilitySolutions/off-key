import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import "./auth-layout.css";

interface AuthBackdropProps {
  children: ReactNode;
  contentClassName?: string;
}

export function AuthBackdrop({
  children,
  contentClassName,
}: AuthBackdropProps) {
  return (
    <div className="auth-backdrop">
      <div className={cn("w-full", contentClassName)}>
        {children}
      </div>
    </div>
  );
}
