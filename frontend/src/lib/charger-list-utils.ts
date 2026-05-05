import type { CombinedData } from "@/dataFetch/FetchContext";

export type ChargerStatusFilter = "all" | "online" | "offline";

export const filterChargerData = (
  data: CombinedData[],
  searchTerm: string,
  statusFilter: ChargerStatusFilter
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
      return true;
    });

export const getChargerStatusCounts = (data: CombinedData[]) => ({
  all: data.length,
  online: data.filter((charger) => charger.online).length,
  offline: data.filter((charger) => !charger.online).length,
});
