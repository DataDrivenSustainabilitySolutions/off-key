import { NavigationBar } from "@/components/NavigationBar";
import { useEffect, useState, useContext, useCallback } from "react";
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
import toast from 'react-hot-toast';

export default function AnomalyTable() {
  const [data, setData] = useState<Anomaly[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const fetchContext = useContext(FetchContext);

  const fetchAllAnomalies = useCallback(async () => {
    if (!fetchContext) return;

    try {
      setIsLoading(true);
      setError(null);
      const chargers = await fetchContext.getAllChargers();
      const allAnomalies = await Promise.all(
        chargers.map((charger) =>
          fetchContext.getAnomalies(charger.charger_id)
        )
      );
      const flattenedAnomalies = allAnomalies.flat();
      setData(flattenedAnomalies);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Unknown error";
      setError(errorMessage);
      toast.error(`Failed to load anomalies: ${errorMessage}`);
    } finally {
      setIsLoading(false);
    }
  }, [fetchContext]);

  useEffect(() => {
    localStorage.setItem("off-key:last-seen-anomalies", new Date().toISOString());
    fetchAllAnomalies();
  }, [fetchAllAnomalies]);

  const handleDelete = async (anomaly: Anomaly) => {
    if (!fetchContext) return;
    if (!anomaly.anomaly_id) {
      toast.error("Cannot delete anomaly without anomaly_id");
      return;
    }
    try {
      await fetchContext.deleteAnomaly(anomaly.anomaly_id);

      toast.success('Anomaly deleted successfully');
      await fetchAllAnomalies();
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Unknown error";
      const errorMessage = `Error while deleting: ${detail}`;
      setError(errorMessage);
      toast.error(errorMessage);
    }
  };

  return (
    <>
      <NavigationBar />
      <div className="p-6">
        <h1 className="text-xl font-bold mb-4">Anomalies</h1>

        {error && <p className="text-red-500 mb-4">{error}</p>}

        {isLoading && <p className="text-gray-500 mb-4">Loading anomalies...</p>}

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
              data.map((anomaly) => (
                <TableRow
                  key={
                    anomaly.anomaly_id ||
                    `${anomaly.charger_id}-${anomaly.timestamp}-${anomaly.telemetry_type}-${anomaly.anomaly_type}`
                  }
                >
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
                      X
                    </button>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={6} className="text-center">
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
