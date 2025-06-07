import { NavigationBar } from "@/components/NavigationBar";
import { useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Anomaly = {
  charger_id: string;
  timestamp: string;
  telemetry_type: string;
  anomaly_type: string;
};

export default function AnomalyTable() {
  const [data, setData] = useState<Anomaly[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchAnomalies = async () => {
      try {
        const res = await fetch(
          "http://localhost:8000/v1/anomalies?charger_id=7939d75d-2ecc-40c3-aca2-fc6332873a4d"
        );
        if (!res.ok) throw new Error("Fehler beim Abrufen der Daten");
        const json = await res.json();
        setData(Array.isArray(json) ? json : []);
      } catch (err: any) {
        setError(err.message || "Unbekannter Fehler");
      }
    };

    fetchAnomalies();
  }, []);

  return (
    <>
      <NavigationBar></NavigationBar>
      <div className="p-6">
        <h1 className="text-xl font-bold mb-4">Anomalien</h1>

        {error && <p className="text-red-500 mb-4">{error}</p>}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Charger ID</TableHead>
              <TableHead>Timestamp</TableHead>
              <TableHead>Telemetry Type</TableHead>
              <TableHead>Anomaly Type</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.length > 0 ? (
              data.map((anomaly, index) => (
                <TableRow key={index}>
                  <TableCell>{anomaly.charger_id}</TableCell>
                  <TableCell>
                    {new Date(anomaly.timestamp).toLocaleString("de-DE", {
                      dateStyle: "short",
                      timeStyle: "medium",
                    })}
                  </TableCell>
                  <TableCell>{anomaly.telemetry_type}</TableCell>
                  <TableCell>{anomaly.anomaly_type}</TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={4} className="text-center">
                  Keine Daten gefunden.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
