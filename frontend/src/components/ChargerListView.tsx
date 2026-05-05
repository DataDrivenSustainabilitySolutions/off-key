import { Link } from "react-router-dom";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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

const FAVORITE_ON = "\u2605";
const FAVORITE_OFF = "\u2606";

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
  const switchControl = (
    <Switch
      checked={isCardsView}
      onCheckedChange={onCardsViewChange}
      className="bg-gray-300 data-[state=checked]:bg-gray-300"
    />
  );

  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
      <input
        type="text"
        placeholder={searchPlaceholder}
        value={searchTerm}
        onChange={(event) => onSearchTermChange(event.target.value)}
        className="p-2 border rounded w-full md:w-1/2"
      />

      <div className="flex items-center gap-4">
        <span className="font-medium whitespace-nowrap">{statusLabel}</span>
        <label className="flex items-center gap-1">
          <input
            type="radio"
            value="all"
            checked={statusFilter === "all"}
            onChange={() => onStatusFilterChange("all")}
          />
          All ({countAll})
        </label>
        <label className="flex items-center gap-1">
          <input
            type="radio"
            value="online"
            checked={statusFilter === "online"}
            onChange={() => onStatusFilterChange("online")}
          />
          Online ({countOnline})
        </label>
        <label className="flex items-center gap-1">
          <input
            type="radio"
            value="offline"
            checked={statusFilter === "offline"}
            onChange={() => onStatusFilterChange("offline")}
          />
          Offline ({countOffline})
        </label>
      </div>

      <div className="flex items-center gap-2">
        <span>Table</span>
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
        <span>Cards</span>
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
    return <p className="text-gray-500">Loading data...</p>;
  }

  if (isCardsView) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {data.map((card, index) => (
          <Card key={index}>
            <CardHeader>
              <CardTitle>{card.charger_id}</CardTitle>
              <CardDescription>{card.charger_name || "No name"}</CardDescription>
            </CardHeader>
            <CardContent>
              <p>
                {cardStatusLabel}:{" "}
                <span
                  className={
                    card.online
                      ? "text-green-600 font-medium"
                      : "text-red-600 font-medium"
                  }
                >
                  {card.online ? "active" : "offline"}
                </span>
              </p>
              <p>Last Seen: {formatLastSeen(card.last_seen)}</p>
            </CardContent>
            <CardFooter>
              <Link
                to={`/details/${card.charger_id}`}
                className="text-sm text-primary underline"
              >
                More details
              </Link>
              <button
                onClick={() => onToggleFavorite(card.charger_id)}
                className="ml-auto text-xl text-black"
                aria-label="Toggle favorite"
              >
                {favoriteChargerIds.includes(card.charger_id)
                  ? FAVORITE_ON
                  : FAVORITE_OFF}
              </button>
            </CardFooter>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Charger ID</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>{tableStatusLabel}</TableHead>
          <TableHead>Last Seen</TableHead>
          <TableHead>Favorite</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((charger) => (
          <TableRow key={charger.charger_id}>
            <TableCell>
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
              <span
                className={
                  charger.online
                    ? "text-green-600 font-medium"
                    : "text-red-600 font-medium"
                }
              >
                {charger.online ? "active" : "offline"}
              </span>
            </TableCell>
            <TableCell>{formatLastSeen(charger.last_seen)}</TableCell>
            <TableCell>
              <button
                onClick={() => onToggleFavorite(charger.charger_id)}
                className="text-xl text-black"
                aria-label="Toggle favorite"
              >
                {favoriteChargerIds.includes(charger.charger_id)
                  ? FAVORITE_ON
                  : FAVORITE_OFF}
              </button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
