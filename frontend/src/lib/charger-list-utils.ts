import type { Charger } from "@/types/charger";

export type ChargerStatusFilter = "all" | "online" | "offline" | "favorites";

export const filterChargerData = (
  data: Charger[],
  searchTerm: string,
  statusFilter: ChargerStatusFilter,
  favoriteChargerIds: readonly string[]
) =>
  data
    .filter(
      (charger) =>
        charger.charger_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (charger.charger_name?.toLowerCase().includes(searchTerm.toLowerCase()) ?? false)
    )
    .filter((charger) => {
      if (statusFilter === "all") return true;
      if (statusFilter === "online") return charger.online === true;
      if (statusFilter === "offline") return charger.online === false;
      if (statusFilter === "favorites") return favoriteChargerIds.includes(charger.charger_id);
      return true;
    });

export const getChargerStatusCounts = (data: Charger[]) => ({
  all: data.length,
  online: data.filter((charger) => charger.online).length,
  offline: data.filter((charger) => !charger.online).length,
});
