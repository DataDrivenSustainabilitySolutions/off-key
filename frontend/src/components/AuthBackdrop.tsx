import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { BrandPattern } from "./BrandPattern";
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
      <BrandPattern className="auth-pattern" />
      <div className={cn("w-full", contentClassName)}>
        {children}
      </div>
    </div>
  );
}
