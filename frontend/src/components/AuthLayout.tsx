import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { AuthBackdrop } from "@/components/AuthBackdrop";
import { useDocumentTitle } from "@/hooks/use-document-title";

export const AUTH_LINK_CLASS = "text-primary underline-offset-4 hover:underline";
export const AUTH_ERROR_CLASS = "text-red-700 dark:text-red-400";
export const AUTH_SUCCESS_CLASS = "text-emerald-700 dark:text-emerald-400";

export const AUTH_LABEL_CLASS = "mb-1.5 block text-[13px] font-medium";

export const AUTH_SUBMIT_BUTTON_CLASS =
  "w-full bg-primary text-primary-foreground hover:bg-primary/90";

interface AuthLayoutProps {
  title: string;
  children: ReactNode;
}

export function AuthLayout({ title, children }: AuthLayoutProps) {
  useDocumentTitle(title);

  return (
    <AuthBackdrop contentClassName="auth-panel">
      <a className="auth-return" href="https://aberration.app/">
        <ArrowLeft size={15} strokeWidth={1.5} aria-hidden="true" />
        Back to website
      </a>
      <main aria-labelledby="auth-title">
        <header className="auth-heading">
          <p className="auth-eyebrow">Dashboard</p>
          <h1 id="auth-title">{title}</h1>
        </header>
        {children}
      </main>
    </AuthBackdrop>
  );
}
