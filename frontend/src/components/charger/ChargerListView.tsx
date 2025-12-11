/**
 * ChargerListView Component
 *
 * Shared component for displaying charger lists in both
 * Landingpage and Favourites pages.
 *
 * Eliminates code duplication between these pages.
 */

import React, { useMemo } from "react";
import { Link } from "react-router-dom";
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
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";
import type { CombinedChargerData, StatusFilter } from "@/types/charger";

// Hook for filtering logic
export function useChargerFiltering(
  data: CombinedChargerData[],
  searchTerm: string,
  statusFilter: StatusFilter
) {
  const filteredData = useMemo(() => {
    return data
      .filter(
        (c) =>
          c.charger_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
          (c.charger_name?.toLowerCase().includes(searchTerm.toLowerCase()) ??
            false)
      )
      .filter((c) => {
        if (statusFilter === "all") return true;
        if (statusFilter === "online") return c.online === true;
        if (statusFilter === "offline") return c.online === false;
        return true;
      });
  }, [data, searchTerm, statusFilter]);

  const counts = useMemo(
    () => ({
      all: filteredData.length,
      online: filteredData.filter((c) => c.online).length,
      offline: filteredData.filter((c) => !c.online).length,
    }),
    [filteredData]
  );

  return { filteredData, counts };
}

interface ChargerListViewProps {
  data: CombinedChargerData[];
  favoriteChargerIds: string[];
  searchTerm: string;
  statusFilter: StatusFilter;
  isCardsView: boolean;
  loading: boolean;
  onSearchChange: (value: string) => void;
  onStatusFilterChange: (value: StatusFilter) => void;
  onViewToggle: (isCards: boolean) => void;
  onToggleFavorite: (chargerId: string) => void;
  title?: string;
}

export const ChargerListView: React.FC<ChargerListViewProps> = ({
  data,
  favoriteChargerIds,
  searchTerm,
  statusFilter,
  isCardsView,
  loading,
  onSearchChange,
  onStatusFilterChange,
  onViewToggle,
  onToggleFavorite,
  title,
}) => {
  const { filteredData, counts } = useChargerFiltering(
    data,
    searchTerm,
    statusFilter
  );

  return (
    <div className="p-6">
      {title && <h1 className="text-xl font-bold mb-4">{title}</h1>}

      {/* Search and filters */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
        <input
          type="text"
          placeholder="Search by Charger ID..."
          value={searchTerm}
          onChange={(e) => onSearchChange(e.target.value)}
          className="p-2 border rounded w-full md:w-1/2"
        />

        <div className="flex items-center gap-4">
          <span className="font-medium whitespace-nowrap">Charger State:</span>
          <StatusFilterRadio
            value="all"
            currentFilter={statusFilter}
            count={counts.all}
            onChange={onStatusFilterChange}
          />
          <StatusFilterRadio
            value="online"
            currentFilter={statusFilter}
            count={counts.online}
            onChange={onStatusFilterChange}
          />
          <StatusFilterRadio
            value="offline"
            currentFilter={statusFilter}
            count={counts.offline}
            onChange={onStatusFilterChange}
          />
        </div>

        <ViewToggle isCardsView={isCardsView} onToggle={onViewToggle} />
      </div>

      {/* Content */}
      {loading ? (
        <p className="text-gray-500">Loading data...</p>
      ) : isCardsView ? (
        <ChargerCardGrid
          chargers={filteredData}
          favoriteChargerIds={favoriteChargerIds}
          onToggleFavorite={onToggleFavorite}
        />
      ) : (
        <ChargerTable
          chargers={filteredData}
          favoriteChargerIds={favoriteChargerIds}
          onToggleFavorite={onToggleFavorite}
        />
      )}
    </div>
  );
};

// Sub-components

interface StatusFilterRadioProps {
  value: StatusFilter;
  currentFilter: StatusFilter;
  count: number;
  onChange: (value: StatusFilter) => void;
}

const StatusFilterRadio: React.FC<StatusFilterRadioProps> = ({
  value,
  currentFilter,
  count,
  onChange,
}) => (
  <label className="flex items-center gap-1">
    <input
      type="radio"
      value={value}
      checked={currentFilter === value}
      onChange={() => onChange(value)}
    />
    {value.charAt(0).toUpperCase() + value.slice(1)} ({count})
  </label>
);

interface ViewToggleProps {
  isCardsView: boolean;
  onToggle: (isCards: boolean) => void;
}

const ViewToggle: React.FC<ViewToggleProps> = ({ isCardsView, onToggle }) => (
  <TooltipProvider>
    <div className="flex items-center gap-2">
      <span>Table</span>
      <Tooltip>
        <TooltipTrigger asChild>
          <Switch
            checked={isCardsView}
            onCheckedChange={onToggle}
            className="bg-gray-300 data-[state=checked]:bg-gray-300"
          />
        </TooltipTrigger>
        <TooltipContent side="top">
          {isCardsView ? "Switch to table view" : "Switch to card view"}
        </TooltipContent>
      </Tooltip>
      <span>Cards</span>
    </div>
  </TooltipProvider>
);

interface ChargerCardGridProps {
  chargers: CombinedChargerData[];
  favoriteChargerIds: string[];
  onToggleFavorite: (chargerId: string) => void;
}

const ChargerCardGrid: React.FC<ChargerCardGridProps> = ({
  chargers,
  favoriteChargerIds,
  onToggleFavorite,
}) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
    {chargers.map((charger, index) => (
      <Card key={index}>
        <CardHeader>
          <CardTitle>{charger.charger_id}</CardTitle>
          <CardDescription>{charger.charger_name || "No name"}</CardDescription>
        </CardHeader>
        <CardContent>
          <p>
            State:{" "}
            <span
              className={
                charger.online
                  ? "text-green-600 font-medium"
                  : "text-red-600 font-medium"
              }
            >
              {charger.online ? "active" : "offline"}
            </span>
          </p>
          <p>Last Seen: {new Date(charger.last_seen).toLocaleString()}</p>
        </CardContent>
        <CardFooter>
          <Link
            to={`/details/${charger.charger_id}`}
            className="text-sm text-primary underline"
          >
            More details
          </Link>
          <FavoriteButton
            isFavorite={favoriteChargerIds.includes(charger.charger_id)}
            onClick={() => onToggleFavorite(charger.charger_id)}
          />
        </CardFooter>
      </Card>
    ))}
  </div>
);

interface ChargerTableProps {
  chargers: CombinedChargerData[];
  favoriteChargerIds: string[];
  onToggleFavorite: (chargerId: string) => void;
}

const ChargerTable: React.FC<ChargerTableProps> = ({
  chargers,
  favoriteChargerIds,
  onToggleFavorite,
}) => (
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Charger ID</TableHead>
        <TableHead>Name</TableHead>
        <TableHead>State</TableHead>
        <TableHead>Last Seen</TableHead>
        <TableHead>Favorite</TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      {chargers.map((charger) => (
        <TableRow key={charger.charger_id}>
          <TableCell>
            <Link
              to={`/details/${charger.charger_id}`}
              className="text-black-600 hover:underline"
            >
              {charger.charger_id}
            </Link>
          </TableCell>
          <TableCell>
            <Link
              to={`/details/${charger.charger_id}`}
              className="text-black-600 hover:underline"
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
          <TableCell>
            {new Date(charger.last_seen).toLocaleString()}
          </TableCell>
          <TableCell>
            <FavoriteButton
              isFavorite={favoriteChargerIds.includes(charger.charger_id)}
              onClick={() => onToggleFavorite(charger.charger_id)}
            />
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  </Table>
);

interface FavoriteButtonProps {
  isFavorite: boolean;
  onClick: () => void;
}

const FavoriteButton: React.FC<FavoriteButtonProps> = ({
  isFavorite,
  onClick,
}) => (
  <button
    onClick={onClick}
    className="ml-auto text-xl text-black"
    aria-label="Toggle favorite"
  >
    {isFavorite ? "★" : "☆"}
  </button>
);

export default ChargerListView;
