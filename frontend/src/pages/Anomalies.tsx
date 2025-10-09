import { NavigationBar } from "@/components/NavigationBar";
import { useEffect, useState, useContext } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Link } from "react-router-dom";
import { FetchContext } from "@/dataFetch/FetchContext";
import { Anomaly } from "@/dataFetch/FetchContext";

export default function AnomalyTable() {
  const [data, setData] = useState<Anomaly[]>([]);
  const [error, setError] = useState<string | null>(null);
  const fetchContext = useContext(FetchContext);

    const fetchAllAnomalies = async () => {
    try {
      if (!fetchContext) return;

      const chargers = await fetchContext.getAllChargers();
      const allAnomalies = await Promise.all(
        chargers.map((charger) =>
          fetchContext.getAnomalies(charger.charger_id)
        )
      );
      const flattenedAnomalies = allAnomalies.flat();
      setData(flattenedAnomalies);
    } catch (err: any) {
      setError(err.message || "Unknown error");
    }
  };

  useEffect(() => {
    fetchAllAnomalies();
  }, [fetchContext]);

  const handleDelete = async (anomaly: Anomaly) => {
    if (!fetchContext) return;
    try {
      await fetchContext.deleteAnomaly(
        anomaly.charger_id,
        new Date(anomaly.timestamp),
        anomaly.telemetry_type
      );
      
      await fetchAllAnomalies();
    } catch (err: any) {
      setError("Error while deleting: " + err.message);
    }
  };

  return (
    <>
      <NavigationBar />
      <div className="p-6">
        <h1 className="text-xl font-bold mb-4">Anomalies</h1>

        {error && <p className="text-red-500 mb-4">{error}</p>}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Charger ID</TableHead>
              <TableHead>Timestamp</TableHead>
              <TableHead>Telemetry Type</TableHead>
              <TableHead>Anomaly Type</TableHead>
              <TableHead>Anomaly Value</TableHead>
              <TableHead>Delete</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.length > 0 ? (
              data.map((anomaly, index) => (
                <TableRow key={index}>
                  <TableCell>
                    <Link
                      to={`/details/${anomaly.charger_id}`}
                      className="text-black-600 hover:underline"
                    >
                    {anomaly.charger_id}
                    </Link>
                    </TableCell>
                  <TableCell>
                    {new Date(anomaly.timestamp).toLocaleString("de-DE", {
                      dateStyle: "short",
                      timeStyle: "medium",
                    })}
                  </TableCell>
                  <TableCell>{anomaly.telemetry_type}</TableCell>
                  <TableCell>{anomaly.anomaly_type}</TableCell>
                  <TableCell><span className="text-red-600 font-medium">{anomaly.anomaly_value}</span></TableCell>
                  <TableCell>
                    <button
                      onClick={() => handleDelete(anomaly)}
                      className="text-red-600 hover:text-red-800 font-bold cursor-pointer"
                      title="delete"
                    >
                      ✕
                    </button>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={4} className="text-center">
                  No data found.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
