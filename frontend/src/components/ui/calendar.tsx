import * as React from "react"
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react"
import { DayPicker } from "react-day-picker"

import { cn } from "@/lib/utils"
import { buttonVariants } from "@/components/ui/button"

function Calendar({
  className,
  classNames,
  showOutsideDays = true,
  ...props
}: React.ComponentProps<typeof DayPicker>) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-3", className)}
      classNames={{
        root: "w-full",
        months: "flex flex-col gap-2 sm:flex-row",
        month: "w-full space-y-4",
        month_caption: "relative flex h-8 w-full items-center justify-center",
        caption_label: "text-sm font-medium",
        nav: "absolute inset-x-0 top-3 flex items-center justify-between px-3",
        button_previous: cn(
          buttonVariants({ variant: "outline" }),
          "size-7 bg-transparent p-0 opacity-50 hover:opacity-100"
        ),
        button_next: cn(
          buttonVariants({ variant: "outline" }),
          "size-7 bg-transparent p-0 opacity-50 hover:opacity-100"
        ),
        month_grid: "w-full table-fixed border-collapse",
        weekdays: "border-b",
        weekday:
          "h-8 w-8 pb-2 text-center text-[0.75rem] font-medium text-muted-foreground",
        weeks: "before:block before:h-2",
        week: "mt-2",
        day: cn(
          "relative h-9 w-9 p-0 text-center align-middle text-sm focus-within:relative focus-within:z-20",
          props.mode === "range"
            ? "first:[&[data-selected]]:rounded-l-md last:[&[data-selected]]:rounded-r-md"
            : ""
        ),
        day_button: cn(
          buttonVariants({ variant: "ghost" }),
          "size-8 p-0 font-normal"
        ),
        range_start:
          "[&_button]:rounded-l-md [&_button]:bg-primary [&_button]:text-primary-foreground [&_button]:hover:bg-primary [&_button]:hover:text-primary-foreground",
        range_end:
          "[&_button]:rounded-r-md [&_button]:bg-primary [&_button]:text-primary-foreground [&_button]:hover:bg-primary [&_button]:hover:text-primary-foreground",
        range_middle:
          "bg-accent [&_button]:rounded-none [&_button]:bg-accent [&_button]:text-accent-foreground [&_button]:hover:bg-accent",
        selected:
          "[&_button]:bg-primary [&_button]:text-primary-foreground [&_button]:hover:bg-primary [&_button]:hover:text-primary-foreground [&_button]:focus:bg-primary [&_button]:focus:text-primary-foreground",
        today: "[&_button]:bg-accent [&_button]:text-accent-foreground",
        outside:
          "text-muted-foreground opacity-50 [&_button]:text-muted-foreground",
        disabled: "text-muted-foreground opacity-50",
        hidden: "invisible",
        ...classNames,
      }}
      components={{
        Chevron: ({ className, orientation, size }) => {
          const Icon =
            orientation === "left"
              ? ChevronLeft
              : orientation === "right"
                ? ChevronRight
                : orientation === "up"
                  ? ChevronUp
                  : ChevronDown

          return <Icon className={cn("size-4", className)} size={size} />
        },
      }}
      {...props}
    />
  )
}

export { Calendar }
