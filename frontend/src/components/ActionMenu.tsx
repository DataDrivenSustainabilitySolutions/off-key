import { Fragment } from "react";
import { MoreHorizontal, type LucideIcon } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

export type MenuAction = { label: string; icon?: LucideIcon; onSelect: () => void; destructive?: boolean; separated?: boolean };

/** A quiet "⋯" button that keeps secondary and destructive actions off the page until asked for. */
export function ActionMenu({ label, actions, className = "" }: { label: string; actions: MenuAction[]; className?: string }) {
  if (!actions.length) return null;
  return <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <button type="button" className={`ex-icon-button ex-action-menu ${className}`.trim()} aria-label={label} title={label}><MoreHorizontal size={17} aria-hidden="true" /></button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" sideOffset={6} className="app-popover ex-action-menu-content">
      {actions.map(action => <Fragment key={action.label}>
        {action.separated && <div role="separator" className="app-menu-separator" />}
        <DropdownMenuItem className="app-menu-item" variant={action.destructive ? "destructive" : "default"} onSelect={action.onSelect}>
          {action.icon && <action.icon aria-hidden="true" />}{action.label}
        </DropdownMenuItem>
      </Fragment>)}
    </DropdownMenuContent>
  </DropdownMenu>;
}
