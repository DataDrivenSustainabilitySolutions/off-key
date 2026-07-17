import type { ComponentProps, ReactNode } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AuthBackdrop } from "@/components/AuthBackdrop";
import { cn } from "@/lib/utils";

export const AUTH_LABEL_CLASS = "mb-1 block text-sm";

export const AUTH_SUBMIT_BUTTON_CLASS =
  "w-full rounded-full bg-primary text-primary-foreground font-semibold transition-all duration-200 hover:bg-primary/90 hover:scale-[1.01] cursor-pointer";

interface AuthLayoutProps {
  title: string;
  children: ReactNode;
  contentClassName?: string;
  titleProps?: ComponentProps<typeof CardTitle>;
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
          <CardTitle
            className={cn("text-center text-2xl", titleClassName)}
            {...restTitleProps}
          >
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent className={cn("pb-0", contentClassName)}>{children}</CardContent>
      </Card>
    </AuthBackdrop>
  );
}
