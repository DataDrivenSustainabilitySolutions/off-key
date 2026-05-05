import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/AuthContext";
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

  const { userId } = useAuth();
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
        const chargers = await getAllChargers();
        if (cancelled) {
          return;
        }

        const combined = await getCombinedChargerData(chargers);
        if (cancelled) {
          return;
        }

        setData(combined);
        if (userId) {
          const favs = await getFavorites(userId);
          if (cancelled) {
            return;
          }
          setFavoriteChargerIds(favs);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        clientLogger.error({
          event: "landingpage.load_failed",
          message: "Failed to load landing page data",
          error,
          context: { userId },
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
  }, [getAllChargers, getCombinedChargerData, getFavorites, userId]);

  const filteredData = filterChargerData(data, searchTerm, statusFilter);
  const statusCounts = getChargerStatusCounts(filteredData);

  const handleViewToggle = (checked: boolean) => {
    setIsCardsView(checked);
  };

  const handleToggleFavorite = async (chargerId: string) => {
    if (!userId) {
      toast.error("Please log in to favorite chargers");
      return;
    }

    const isFavorite = favoriteChargerIds.includes(chargerId);
    setFavoriteChargerIds((prev) =>
      isFavorite ? prev.filter((id) => id !== chargerId) : [...prev, chargerId]
    );

    try {
      await toggleFavorite(chargerId, userId, isFavorite);
      toast.success(isFavorite ? "Removed from favorites" : "Added to favorites");
    } catch (err) {
      clientLogger.error({
        event: "favorites.toggle_failed",
        message: "Error saving favorite",
        error: err,
        context: { chargerId, isFavorite },
      });
      toast.error("Failed to update favorite status");
      setFavoriteChargerIds((prev) =>
        isFavorite ? [...prev, chargerId] : prev.filter((id) => id !== chargerId)
      );
    }
  };

  return (
    <>
      <NavigationBar />

      <div className="p-6">
        <ChargerListControls
          searchTerm={searchTerm}
          onSearchTermChange={setSearchTerm}
          searchPlaceholder="Search by Charger ID..."
          statusLabel="Charger State:"
          statusFilter={statusFilter}
          onStatusFilterChange={setStatusFilter}
          countAll={statusCounts.all}
          countOnline={statusCounts.online}
          countOffline={statusCounts.offline}
          isCardsView={isCardsView}
          onCardsViewChange={handleViewToggle}
          viewToggleTooltip={
            isCardsView ? "Switch to table view" : "Switch to card view"
          }
        />

        <ChargerListResults
          loading={loading}
          isCardsView={isCardsView}
          data={filteredData}
          favoriteChargerIds={favoriteChargerIds}
          onToggleFavorite={handleToggleFavorite}
          cardStatusLabel="State"
          tableStatusLabel="State"
        />
      </div>
    </>
  );
}
