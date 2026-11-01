import type { ComponentProps, ReactNode } from "react";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import { AuthBackdrop } from "@/components/AuthBackdrop";
import { BrandHome } from "@/components/BrandHome";
import { cn } from "@/lib/utils";
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
  brandVariant?: ComponentProps<typeof BrandHome>["variant"];
  hideTitle?: boolean;
}

export function AuthLayout({
  title,
  children,
  brandVariant,
  hideTitle = false,
}: AuthLayoutProps) {
  useDocumentTitle(title);

  return (
    <AuthBackdrop contentClassName="max-w-sm">
      <Card className="w-full gap-6 border-border py-7 sm:py-8">
        <CardHeader className={hideTitle ? "gap-0" : undefined}>
          <div className={cn("flex justify-center", !hideTitle && "mb-4")}><BrandHome variant={brandVariant} /></div>
          <h1
            data-slot="card-title"
            className={hideTitle ? "sr-only" : "text-center text-xl font-medium leading-7 tracking-[-0.02em]"}
          >
            {title}
          </h1>
        </CardHeader>
        <CardContent className="pb-0">{children}</CardContent>
      </Card>
    </AuthBackdrop>
  );
}
