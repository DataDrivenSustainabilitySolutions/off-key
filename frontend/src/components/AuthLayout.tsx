import type { ComponentProps, ReactNode } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

export const AUTH_LABEL_CLASS = "mb-1 block text-sm";

export const AUTH_SUBMIT_BUTTON_CLASS =
  "w-full bg-gradient-to-r from-slate-400 to-slate-300 text-white font-semibold rounded-full transition-all duration-200 hover:bg-gradient-to-r hover:from-slate-500 hover:to-slate-400 hover:scale-105 cursor-pointer";

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
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <Card className="w-full max-w-md p-6">
        <CardHeader>
          <CardTitle
            className={cn("text-center text-2xl", titleClassName)}
            {...restTitleProps}
          >
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent className={contentClassName}>{children}</CardContent>
      </Card>
    </div>
  );
}
