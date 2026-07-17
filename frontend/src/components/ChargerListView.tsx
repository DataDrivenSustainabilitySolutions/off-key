import { Link } from "react-router-dom";
import { Grid2X2, List, Search, Star } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { CombinedData } from "@/dataFetch/FetchContext";
import type { ChargerStatusFilter } from "@/lib/charger-list-utils";
import { formatLastSeen } from "@/lib/time-utils";
import { cn } from "@/lib/utils";

interface ChargerListControlsProps {
  searchTerm: string;
  onSearchTermChange: (value: string) => void;
  searchPlaceholder: string;
  statusLabel: string;
  statusFilter: ChargerStatusFilter;
  onStatusFilterChange: (value: ChargerStatusFilter) => void;
  countAll: number;
  countOnline: number;
  countOffline: number;
  isCardsView: boolean;
  onCardsViewChange: (checked: boolean) => void;
  viewToggleTooltip?: string;
}

const statusOptions: Array<{
  value: ChargerStatusFilter;
  label: string;
  countKey: "countAll" | "countOnline" | "countOffline";
}> = [
  { value: "all", label: "All", countKey: "countAll" },
  { value: "online", label: "Online", countKey: "countOnline" },
  { value: "offline", label: "Offline", countKey: "countOffline" },
];

export function ChargerListControls({
  searchTerm,
  onSearchTermChange,
  searchPlaceholder,
  statusLabel,
  statusFilter,
  onStatusFilterChange,
  countAll,
  countOnline,
  countOffline,
  isCardsView,
  onCardsViewChange,
  viewToggleTooltip,
}: ChargerListControlsProps) {
  const counts = { countAll, countOnline, countOffline };
  const switchControl = (
    <Switch checked={isCardsView} onCheckedChange={onCardsViewChange} />
  );

  return (
    <div className="rounded-2xl border border-border/65 bg-card p-4 shadow-[0_1px_2px_hsl(220_20%_10%/0.025)]">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="text"
            placeholder={searchPlaceholder}
            value={searchTerm}
            onChange={(event) => onSearchTermChange(event.target.value)}
            className="pl-9"
          />
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <span className="text-sm font-medium text-muted-foreground">
              {statusLabel}
            </span>
            <div className="grid grid-cols-3 rounded-xl border border-border/70 bg-muted/35 p-1">
              {statusOptions.map((option) => (
                <label
                  key={option.value}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition-[color,background-color,box-shadow]",
                    statusFilter === option.value &&
                      "bg-card text-foreground shadow-xs"
                  )}
                >
                  <input
                    type="radio"
                    value={option.value}
                    checked={statusFilter === option.value}
                    onChange={() => onStatusFilterChange(option.value)}
                    className="sr-only"
                  />
                  {option.label} ({counts[option.countKey]})
                </label>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-xl border border-border/70 bg-muted/35 px-2.5 py-1.5">
            <List className="h-4 w-4 text-muted-foreground" />
            {viewToggleTooltip ? (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>{switchControl}</TooltipTrigger>
                  <TooltipContent side="top">{viewToggleTooltip}</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              switchControl
            )}
            <Grid2X2 className="h-4 w-4 text-muted-foreground" />
          </div>
        </div>
      </div>
    </div>
  );
}

interface ChargerListResultsProps {
  loading: boolean;
  isCardsView: boolean;
  data: CombinedData[];
  favoriteChargerIds: string[];
  onToggleFavorite: (chargerId: string) => void;
  cardStatusLabel: string;
  tableStatusLabel: string;
}

function ChargerStatusBadge({ online }: { online: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        online
          ? "border-emerald-200/80 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200"
          : "border-red-200/80 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200"
      )}
    >
      <span className={cn("size-1.5 rounded-full", online ? "bg-emerald-500" : "bg-red-500")} />
      {online ? "Online" : "Offline"}
    </span>
  );
}

function FavoriteButton({
  active,
  onClick,
}: {
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={onClick}
      aria-label="Toggle favorite"
      className={cn(active && "text-amber-500 hover:text-amber-600")}
    >
      <Star className={cn("h-4 w-4", active && "fill-current")} />
    </Button>
  );
}

export function ChargerListResults({
  loading,
  isCardsView,
  data,
  favoriteChargerIds,
  onToggleFavorite,
  cardStatusLabel,
  tableStatusLabel,
}: ChargerListResultsProps) {
  if (loading) {
    return (
      <div className="flex min-h-32 items-center justify-center rounded-2xl border border-border/65 bg-card p-6 text-sm text-muted-foreground">
        <span className="mr-2 size-2 animate-pulse rounded-full bg-primary" />
        Loading data
      </div>
    );
  }

  if (isCardsView) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {data.length === 0 ? (
          <Card className="sm:col-span-2 xl:col-span-3">
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              No data found.
            </CardContent>
          </Card>
        ) : (
          data.map((card) => {
            const isFavorite = favoriteChargerIds.includes(card.charger_id);
            return (
              <Card
                key={card.charger_id}
                className="gap-0 overflow-hidden py-0 transition-[border-color,box-shadow,transform] hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md"
              >
                <CardHeader className="pb-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="truncate text-base">
                        {card.charger_id}
                      </CardTitle>
                      <CardDescription className="truncate">
                        {card.charger_name || "No name"}
                      </CardDescription>
                    </div>
                    <FavoriteButton
                      active={isFavorite}
                      onClick={() => onToggleFavorite(card.charger_id)}
                    />
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">{cardStatusLabel}</span>
                    <ChargerStatusBadge online={card.online} />
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">Last Seen</span>
                    <span className="text-right">{formatLastSeen(card.last_seen)}</span>
                  </div>
                </CardContent>
                <CardFooter className="border-t border-border/60 px-6 py-4">
                  <Button asChild variant="outline" size="sm" className="w-full">
                    <Link to={`/details/${card.charger_id}`}>More details</Link>
                  </Button>
                </CardFooter>
              </Card>
            );
          })
        )}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border/65 bg-card shadow-[0_1px_2px_hsl(220_20%_10%/0.025)]">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead>Charger ID</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>{tableStatusLabel}</TableHead>
            <TableHead>Last Seen</TableHead>
            <TableHead className="text-right">Favorite</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                No data found.
              </TableCell>
            </TableRow>
          ) : (
            data.map((charger) => {
              const isFavorite = favoriteChargerIds.includes(charger.charger_id);
              return (
                <TableRow key={charger.charger_id}>
                  <TableCell className="font-medium">
                    <Link
                      to={`/details/${charger.charger_id}`}
                      className="text-foreground hover:underline"
                    >
                      {charger.charger_id}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Link
                      to={`/details/${charger.charger_id}`}
                      className="text-foreground hover:underline"
                    >
                      {charger.charger_name || "N/A"}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <ChargerStatusBadge online={charger.online} />
                  </TableCell>
                  <TableCell>{formatLastSeen(charger.last_seen)}</TableCell>
                  <TableCell className="text-right">
                    <FavoriteButton
                      active={isFavorite}
                      onClick={() => onToggleFavorite(charger.charger_id)}
                    />
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </div>
  );
}
