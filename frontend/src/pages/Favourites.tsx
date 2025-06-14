import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter,
} from "@/components/ui/card";
import { NavigationBar } from "@/components/NavigationBar";
import { useFetch } from "@/dataFetch/UseFetch";
import type { CombinedData } from "@/dataFetch/FetchContext";

import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

export default function ChargerTable() {
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "offline">("all");
  const [isCardsView, setIsCardsView] = useState(false);
  const [favoriteChargerIds, setFavoriteChargerIds] = useState<string[]>([]);
  const [data, setData] = useState<CombinedData[]>([]);

  const {
    getAllChargers,
    getCombinedChargerData,
    toggleFavorite,
    getFavorites,
  } = useFetch();

  useEffect(() => {
    async function loadData() {
      setLoading(true);
      try {
        const favoriteIds = await getFavorites(1);
        setFavoriteChargerIds(favoriteIds);

        const chargers = await getAllChargers();
        const combined = await getCombinedChargerData(chargers);
        const favs = combined.filter((c) => favoriteIds.includes(c.charger_id));
        setData(favs);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [getAllChargers, getCombinedChargerData, getFavorites]);

  const filteredData = data
    .filter((c) =>
      c.charger_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (c.charger_name?.toLowerCase().includes(searchTerm.toLowerCase()) ?? false)
    )
    .filter((c) => {
      if (statusFilter === "all") return true;
      if (statusFilter === "online") return c.online === true;
      if (statusFilter === "offline") return c.online === false;
      return true;
    });

  const countAll = filteredData.length;
  const countOnline = filteredData.filter((c) => c.online).length;
  const countOffline = filteredData.filter((c) => !c.online).length;

  const handleViewToggle = (checked: boolean) => {
    setIsCardsView(checked);
  };

  const handleToggleFavorite = async (chargerId: string) => {
    const isFavorite = favoriteChargerIds.includes(chargerId);
    setFavoriteChargerIds((prev) =>
      isFavorite ? prev.filter((id) => id !== chargerId) : [...prev, chargerId]
    );

    try {
      await toggleFavorite(chargerId, 1, isFavorite);
    } catch (err) {
      console.error("Error saving favorite status:", err);
      setFavoriteChargerIds((prev) =>
        isFavorite ? [...prev, chargerId] : prev.filter((id) => id !== chargerId)
      );
    }
  };

  return (
    <>
      <NavigationBar />
      <div className="p-6">
        <h1 className="text-xl font-bold mb-4">Favorites</h1>

        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <input
            type="text"
            placeholder="Search for charger ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="p-2 border rounded w-full md:w-1/2"
          />

          <div className="flex items-center gap-4">
            <span className="font-medium whitespace-nowrap">Charger state:</span>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                value="all"
                checked={statusFilter === "all"}
                onChange={() => setStatusFilter("all")}
              />
              All ({countAll})
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                value="online"
                checked={statusFilter === "online"}
                onChange={() => setStatusFilter("online")}
              />
              Online ({countOnline})
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                value="offline"
                checked={statusFilter === "offline"}
                onChange={() => setStatusFilter("offline")}
              />
              Offline ({countOffline})
            </label>
          </div>

          <TooltipProvider>
            <div className="flex items-center gap-2">
              <span>Table</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Switch
                    checked={isCardsView}
                    onCheckedChange={handleViewToggle}
                    className="bg-gray-300 data-[state=checked]:bg-gray-300"
                  />
                </TooltipTrigger>
                <TooltipContent>
                  {isCardsView ? "Switch to table view" : "Switch to card view"}
                </TooltipContent>
              </Tooltip>
              <span>Cards</span>
            </div>
          </TooltipProvider>
        </div>

        {loading ? (
          <p className="text-gray-500">Loading data...</p>
        ) : isCardsView ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredData.map((card, index) => (
              <Card key={index}>
                <CardHeader>
                  <CardTitle>{card.charger_id}</CardTitle>
                  <CardDescription>{card.charger_name || "No name"}</CardDescription>
                </CardHeader>
                <CardContent>
                  <p>
                    Status:{" "}
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
                  <p>Last Seen: {new Date(card.last_seen).toLocaleString()}</p>
                </CardContent>
                <CardFooter>
                  <Link
                    to={`/details/${card.charger_id}`}
                    className="text-sm text-primary underline"
                  >
                    More details
                  </Link>
                  <button
                    onClick={() => handleToggleFavorite(card.charger_id)}
                    className="ml-auto text-xl text-black"
                    aria-label="Toggle favorite"
                  >
                    {favoriteChargerIds.includes(card.charger_id) ? "★" : "☆"}
                  </button>
                </CardFooter>
              </Card>
            ))}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Charger ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last Seen</TableHead>
                <TableHead>Favorite</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredData.map((c) => (
                <TableRow key={c.charger_id}>
                  <TableCell>
                    <Link
                      to={`/details/${c.charger_id}`}
                      className="text-black-600 hover:underline"
                    >
                      {c.charger_id}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Link
                      to={`/details/${c.charger_id}`}
                      className="text-black-600 hover:underline"
                    >
                      {c.charger_name || "N/A"}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <span
                      className={
                        c.online
                          ? "text-green-600 font-medium"
                          : "text-red-600 font-medium"
                      }
                    >
                      {c.online ? "active" : "offline"}
                    </span>
                  </TableCell>
                  <TableCell>{new Date(c.last_seen).toLocaleString()}</TableCell>
                  <TableCell>
                    <button
                      onClick={() => handleToggleFavorite(c.charger_id)}
                      className="text-xl text-black"
                      aria-label="Toggle favorite"
                    >
                      {favoriteChargerIds.includes(c.charger_id) ? "★" : "☆"}
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </>
  );
}
