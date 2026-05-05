import { useEffect, useState } from "react";
import {
  ChargerListControls,
  ChargerListResults,
} from "@/components/ChargerListView";
import {
  filterChargerData,
  getChargerStatusCounts,
  type ChargerStatusFilter,
} from "@/lib/charger-list-utils";
import { NavigationBar } from "@/components/NavigationBar";
import { useFetch } from "@/dataFetch/UseFetch";
import type { CombinedData } from "@/dataFetch/FetchContext";
import { clientLogger } from "@/lib/logger";

export default function ChargerTable() {
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<ChargerStatusFilter>("all");
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
    let cancelled = false;

    async function loadData() {
      if (!cancelled) {
        setLoading(true);
      }

      try {
        const favoriteIds = await getFavorites(1);
        if (cancelled) {
          return;
        }
        setFavoriteChargerIds(favoriteIds);

        const chargers = await getAllChargers();
        if (cancelled) {
          return;
        }
        const combined = await getCombinedChargerData(chargers);
        if (cancelled) {
          return;
        }

        const favs = combined.filter((charger) =>
          favoriteIds.includes(charger.charger_id)
        );
        setData(favs);
      } catch (error) {
        if (cancelled) {
          return;
        }

        clientLogger.error({
          event: "favorites.load_failed",
          message: "Failed to load favorites page data",
          error,
        });
        setData([]);
        setFavoriteChargerIds([]);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadData();

    return () => {
      cancelled = true;
    };
  }, [getAllChargers, getCombinedChargerData, getFavorites]);

  const filteredData = filterChargerData(data, searchTerm, statusFilter);
  const statusCounts = getChargerStatusCounts(filteredData);

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
      clientLogger.error({
        event: "favorites.toggle_failed",
        message: "Error saving favorite status",
        error: err,
        context: { chargerId, userId: 1, isFavorite },
      });
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
        <ChargerListControls
          searchTerm={searchTerm}
          onSearchTermChange={setSearchTerm}
          searchPlaceholder="Search for charger ID..."
          statusLabel="Charger state:"
          statusFilter={statusFilter}
          onStatusFilterChange={setStatusFilter}
          countAll={statusCounts.all}
          countOnline={statusCounts.online}
          countOffline={statusCounts.offline}
          isCardsView={isCardsView}
          onCardsViewChange={handleViewToggle}
        />

        <ChargerListResults
          loading={loading}
          isCardsView={isCardsView}
          data={filteredData}
          favoriteChargerIds={favoriteChargerIds}
          onToggleFavorite={handleToggleFavorite}
          cardStatusLabel="Status"
          tableStatusLabel="Status"
        />
      </div>
    </>
  );
}
