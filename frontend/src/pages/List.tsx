import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Switch } from "@/components/ui/switch"
import { useEffect, useState } from "react";
import axios from "axios";
import { Link, useNavigate } from "react-router-dom";
import {NavigationBar} from "@/components/NavigationBar";

interface Charger {
  charger_name: string | null;
  last_seen: string;
  online: boolean;
  charger_id: string;
  state: string;
  created: string;
};

interface telemetry_data {
  charger_id: string;
  timestamp: string;
  value: number;
};

interface combined_data {
  charger_id: string;
  charger_name: string | null;
  online: boolean;
  state: string;
  last_seen: string;
  value1: number | null;
  value2: number | null;
}

export default function ChargerTable() {
  const [data, setData] = useState<combined_data[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "offline">("all");
  const countAll = data.length;
  const countOnline = data.filter((c) => c.online).length;
  const countOffline = data.filter((c) => !c.online).length;
  const [isCardsView, setIsCardsView] = useState(false);
  const navigate = useNavigate();

  const handleViewToggle = (checked: boolean) => {
    setIsCardsView(checked);
    if (checked) {
      navigate("/cards");
    }
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Hole die Basisdaten aller verfügbaren Charger
        const chargerRes = await axios.get<Charger[]>("http://localhost:8000/v1/chargers/available"); // Gibt alle Charger zurück
        const chargers = chargerRes.data;

        // Hole für jeden Charger (anhand der ChargerID) die Telemetriedaten
        const combined_data = await Promise.all(
          chargers.map(async (charger) => {
            try {
              const [value1Res, value2Res] = await Promise.all([
                axios.get<telemetry_data[]>(
                  `http://localhost:8000/v1/telemetry/${charger.charger_id}/controllerCpuUsage`
                ),
                axios.get<telemetry_data[]>(
                  `http://localhost:8000/v1/telemetry/${charger.charger_id}/controllertemperaturecpu-thermal`
                )
              ]);

              const value1 = value1Res.data[0]?.value ?? null;
              const value2 = value2Res.data[0]?.value ?? null;

              return {
                charger_id: charger.charger_id,
                charger_name: charger.charger_name,
                online: charger.online,
                state: charger.state,
                last_seen: charger.last_seen,
                value1,
                value2
              };
            } catch (err) {
              console.warn(`Fehler bei Werten für Charger ${charger.charger_id}`, err);
              return {
                charger_id: charger.charger_id,
                charger_name: charger.charger_name,
                online: charger.online,
                state: charger.state,
                last_seen: charger.last_seen,
                value1: null,
                value2: null
              };
            }
          })
        );

        setData(combined_data);
      } catch (err) {
        console.error("Fehler beim Laden der Daten:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 10000); // alle 10 Sekunden

    return () => clearInterval(interval); // aufräumen beim Unmounten
  }, []);

  const filteredData = data
  .filter((c) =>
    c.charger_id.toLowerCase().includes(searchTerm.toLowerCase()
  ) || (c.charger_name?.toLowerCase().includes(searchTerm.toLowerCase()) ?? false)
  )
  .filter((c) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "online") return c.online === true;
    if (statusFilter === "offline") return c.online === false;
    return true;
  });


  return (
    <>
    <NavigationBar /> {/* <-- Direkt ganz oben */}
    <div className="p-6">
<div className="mb-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
  {/* Suchleiste links */}
  <input
    type="text"
    placeholder="Nach Charger ID suchen..."
    value={searchTerm}
    onChange={(e) => setSearchTerm(e.target.value)}
    className="p-2 border rounded w-full md:w-1/2"
  />

{/* Status-Filter rechts */}
<div className="flex items-center gap-4">
    <span className="font-medium whitespace-nowrap">Ladesäulen Status:</span>
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
                <TableHead>Latest CPU Usage</TableHead>
                <TableHead>Latest CPU Temp</TableHead>
                <TableHead>Last Seen</TableHead>
                <TableHead>Favorit</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
            {filteredData.map((c) => (
                <TableRow key={c.charger_id}>
                  <TableCell><Link to={`/charger/${c.charger_id}`} className="text-black-600 hover:underline">{c.charger_id}</Link></TableCell>
                  <TableCell><Link to={`/charger/${c.charger_id}`} className="text-black-600 hover:underline">{c.charger_name || "N/A"}</Link></TableCell>
                  <TableCell>
                  <span className={c.online ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
                    {c.online ? "active" : "offline"}
                  </span>
                </TableCell>
                  <TableCell>{c.value1 !== null ? `${c.value1.toFixed(2)} %` : "-"}</TableCell>
                  <TableCell>{c.value2 !== null ? `${c.value2.toFixed(2)} °C` : "-"}</TableCell>
                  <TableCell>{new Date(c.last_seen).toLocaleString()}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
      </>
    );
}