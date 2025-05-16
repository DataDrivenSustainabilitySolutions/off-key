import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { useEffect, useState } from "react";
import axios from "axios";
import { Link, useNavigate } from "react-router-dom";
import { NavigationBar } from "@/components/NavigationBar";

interface Charger {
  charger_name: string | null;
  last_seen: string;
  online: boolean;
  charger_id: string;
  state: string;
  created: string;
}

interface telemetry_data {
  charger_id: string;
  timestamp: string;
  value: number;
}

interface CombinedChargerData {
  charger_id: string;
  charger_name: string | null;
  online: boolean;
  state: string;
  last_seen: string;
  telemetry: { [key: string]: number | null };
}

export default function ChargerTable() {
  const [data, setData] = useState<CombinedChargerData[]>([]);
  const [telemetryTypes, setTelemetryTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<
    "all" | "online" | "offline"
  >("all");
  const [isCardsView, setIsCardsView] = useState(false);
  const [favoriteChargerIds, setFavoriteChargerIds] = useState<string[]>([]);
  const navigate = useNavigate();

  const countAll = data.length;
  const countOnline = data.filter((c) => c.online).length;
  const countOffline = data.filter((c) => !c.online).length;

  // Überprüfe, ob der Benutzer die Kartenansicht aktiviert hat. Wenn ja, navigiere zur Kartenansicht
  const handleViewToggle = (checked: boolean) => {
    setIsCardsView(checked);
    if (checked) {
      navigate("/cards");
    }
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Synchronisiere die Charger-Daten
        await axios.post("http://localhost:8000/v1/chargers/sync", null, {
          timeout: 1500, // max. 1.5 Sekunden warten
        });

        // Hole die Basisdaten aller verfügbaren Charger
        const chargerRes = await axios.get<Charger[]>(
          "http://localhost:8000/v1/chargers/available"
        );
        const chargers = chargerRes.data;

        const allTypesSet = new Set<string>();

        // Hole für jeden Charger (anhand der ChargerID) die Telemetriedaten
        const combinedData: CombinedChargerData[] = await Promise.all(
          chargers.map(async (charger) => {
            try {
              const typesRes = await axios.get<string[]>(
                `http://localhost:8000/v1/telemetry/${charger.charger_id}/type`
              );
              // Hole die Telemetriedaten für den Charger und erstelle ein Set aller Typen
              const telemetryTypes = typesRes.data;
              telemetryTypes.forEach((type) => allTypesSet.add(type));

              // Hole die Telemetriedaten für den Charger und speichere den ersten/neusten Wert
              const telemetryValues = await Promise.all(
                telemetryTypes.map(async (type) => {
                  try {
                    const res = await axios.get<telemetry_data[]>(
                      `http://localhost:8000/v1/telemetry/${charger.charger_id}/${type}`
                    );
                    return { type, value: res.data[0]?.value ?? null };
                  } catch {
                    return { type, value: null };
                  }
                })
              );
              // Erstellt ein Objekt, das jedem Telemetrie-Typ seinen zugehörigen Wert zuordnet
              const telemetry: { [key: string]: number | null } = {};
              telemetryValues.forEach(({ type, value }) => {
                telemetry[type] = value;
              });

              return {
                charger_id: charger.charger_id,
                charger_name: charger.charger_name,
                online: charger.online,
                state: charger.state,
                last_seen: charger.last_seen,
                telemetry,
              };
            } catch (err) {
              console.warn(`Fehler bei Charger ${charger.charger_id}`, err);
              return {
                charger_id: charger.charger_id,
                charger_name: charger.charger_name,
                online: charger.online,
                state: charger.state,
                last_seen: charger.last_seen,
                telemetry: {},
              };
            }
          })
        );

        setData(combinedData);
        setTelemetryTypes(Array.from(allTypesSet).sort());
      } catch (err) {
        console.error("Fehler beim Laden der Daten:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 10000); // alle 10 Sekunden Daten aktualisieren

    return () => clearInterval(interval); // aufräumen beim Unmounten
  }, []);

  const filteredData = data
    // Filtere die Daten basierend auf dem Suchbegriff
    .filter(
      (c) =>
        c.charger_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (c.charger_name?.toLowerCase().includes(searchTerm.toLowerCase()) ??
          false)
    )
    // Filtere die Daten basierend auf dem Status-Filter
    .filter((c) => {
      if (statusFilter === "all") return true;
      if (statusFilter === "online") return c.online === true;
      if (statusFilter === "offline") return c.online === false;
      return true;
    });

  // Überprüfe ob der Favorit bereits gesetzt ist, wenn ja, entferne ihn. Wenn nicht, füge ihn hinzu
  const handleToggleFavorite = async (chargerId: string) => {
    const isFavorite = favoriteChargerIds.includes(chargerId);
    const updatedFavorites = isFavorite
      ? favoriteChargerIds.filter((id) => id !== chargerId)
      : [...favoriteChargerIds, chargerId];

    // Aktualisiere den Zustand der Favoriten auf der UI
    setFavoriteChargerIds(updatedFavorites);

    try {
      // Wenn der Charger bereits ein Favorit ist, entferne ihn. Ansonsten füge ihn hinzu
      if (isFavorite) {
        // DELETE request
        await axios.delete("http://localhost:8000/v1/favorites", {
          data: {
            charger_id: chargerId,
            user_id: 1,
          },
        });
      } else {
        // POST request
        await axios.post("http://localhost:8000/v1/favorites", {
          charger_id: chargerId,
          user_id: 1,
        });
      }
    } catch (err) {
      console.error("Fehler beim Speichern des Favorits:", err);
    }
  };

  return (
    <>
      <NavigationBar />
      <div className="p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <input
            type="text"
            placeholder="Nach Charger ID suchen..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="p-2 border rounded w-full md:w-1/2"
          />
          <div className="flex items-center gap-4">
            <span className="font-medium whitespace-nowrap">
              Ladesäulen Status:
            </span>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                value="all"
                checked={statusFilter === "all"}
                onChange={() => setStatusFilter("all")}
              />
              Alle ({countAll})
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                value="online"
                checked={statusFilter === "online"}
                onChange={() => setStatusFilter("online")}
              />
              Aktiv ({countOnline})
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
          <div className="flex items-center gap-2">
            <span>Table</span>
            <Switch
              checked={isCardsView}
              onCheckedChange={handleViewToggle}
              className="bg-gray-300 data-[state=checked]:bg-gray-300"
            />
            <span>Cards</span>
          </div>
        </div>
        {loading ? (
          <p className="text-gray-500">Lade Daten...</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Charger ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                {telemetryTypes.map((type) => (
                  <TableHead key={type}>{type}</TableHead>
                ))}
                <TableHead>Last Seen</TableHead>
                <TableHead>Favorit</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredData.map((c) => (
                <TableRow key={c.charger_id}>
                  <TableCell>{c.charger_id}</TableCell>
                  <TableCell>{c.charger_name || "N/A"}</TableCell>
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
                  {telemetryTypes.map((type) => (
                    <TableCell key={type}>
                      {c.telemetry[type] !== null
                        ? c.telemetry[type]?.toFixed(2)
                        : "-"}
                    </TableCell>
                  ))}
                  <TableCell>
                    {new Date(c.last_seen).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <button
                      onClick={() => handleToggleFavorite(c.charger_id)}
                      className="text-xl"
                      aria-label="Favorisieren"
                    >
                      {favoriteChargerIds.includes(c.charger_id) ? "⭐" : "☆"}
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
