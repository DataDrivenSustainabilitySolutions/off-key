import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/AuthContext";
import {
  ChargerListControls,
  ChargerListResults,
} from "@/components/ChargerListView";
import {
  MetricCard,
  PageHeader,
  PageShell,
} from "@/components/DashboardLayout";
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
        if (userId === null) {
          setFavoriteChargerIds([]);
          setData([]);
          return;
        }

        const favoriteIds = await getFavorites(userId);
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
  const statusCounts = getChargerStatusCounts(data);

  const handleViewToggle = (checked: boolean) => {
    setIsCardsView(checked);
  };

  const handleToggleFavorite = async (chargerId: string) => {
    if (userId === null) {
      toast.error("Please log out and log in again to update favorites");
      return;
    }

    const isFavorite = favoriteChargerIds.includes(chargerId);
    setFavoriteChargerIds((prev) =>
      isFavorite ? prev.filter((id) => id !== chargerId) : [...prev, chargerId]
    );

    try {
      await toggleFavorite(chargerId, userId, isFavorite);
    } catch (err) {
      clientLogger.error({
        event: "favorites.toggle_failed",
        message: "Error saving favorite status",
        error: err,
        context: { chargerId, userId, isFavorite },
      });
      setFavoriteChargerIds((prev) =>
        isFavorite ? [...prev, chargerId] : prev.filter((id) => id !== chargerId)
      );
    }
  };

  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          eyebrow="Saved Stations"
          title="Favorites"
          description="Keep frequently inspected chargers close and filter them by status."
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <MetricCard label="Favorites" value={statusCounts.all} helper="Saved chargers" />
          <MetricCard label="Online" value={statusCounts.online} tone="success" />
          <MetricCard
            label="Offline"
            value={statusCounts.offline}
            tone={statusCounts.offline > 0 ? "danger" : "default"}
          />
        </div>

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
      </PageShell>
    </>
  );
}
