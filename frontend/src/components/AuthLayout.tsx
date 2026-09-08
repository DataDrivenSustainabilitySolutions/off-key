import type { ComponentProps, ReactNode } from "react";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import { AuthBackdrop } from "@/components/AuthBackdrop";
import { cn } from "@/lib/utils";

export const AUTH_LINK_CLASS = "text-primary hover:underline";
export const AUTH_ERROR_CLASS = "text-red-700 dark:text-red-400";
export const AUTH_SUCCESS_CLASS = "text-emerald-700 dark:text-emerald-400";

export const AUTH_LABEL_CLASS = "mb-1 block text-sm";

export const AUTH_SUBMIT_BUTTON_CLASS =
  "w-full rounded-full bg-primary text-primary-foreground font-semibold transition-all duration-200 hover:bg-primary/90 hover:scale-[1.01] cursor-pointer";

interface AuthLayoutProps {
  title: string;
  children: ReactNode;
  contentClassName?: string;
  titleProps?: ComponentProps<"h1">;
}

export function AuthLayout({
  title,
  children,
  contentClassName,
  titleProps,
}: AuthLayoutProps) {
  const { className: titleClassName, ...restTitleProps } = titleProps ?? {};

  return (
    <AuthBackdrop contentClassName="max-w-md">
      <Card className="w-full max-w-md gap-5 border-white/35 bg-card/95 pb-7 shadow-2xl shadow-black/10 backdrop-blur-xl dark:border-white/10">
        <CardHeader>
          <h1
            data-slot="card-title"
            className={cn("text-center text-2xl leading-none font-semibold", titleClassName)}
            {...restTitleProps}
          >
            {title}
          </h1>
        </CardHeader>
        <CardContent className={cn("pb-0", contentClassName)}>{children}</CardContent>
      </Card>
    </AuthBackdrop>
  );
}
