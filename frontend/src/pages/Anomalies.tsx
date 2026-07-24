import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, Trash2 } from "lucide-react";
import toast from "react-hot-toast";

import {
  MetricCard,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  formatAnomalyValue,
  getAnomalyValueClassName,
  getAnomalyValueLabel,
  isProbabilityAnomalyValue,
} from "@/lib/anomaly-semantics";
import { formatAnomalySensorSet } from "@/lib/anomaly-utils";
import {
  deleteAnomaly,
  getAllChargers,
  getAnomalies,
} from "@/lib/charger-api";
import { getErrorMessage } from "@/lib/errors";
import type { Anomaly } from "@/types/charger";

export default function AnomalyTable() {
  const [data, setData] = useState<Anomaly[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchAllAnomalies = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const chargers = await getAllChargers();
      const allAnomalies = await Promise.all(
        chargers.map((charger) => getAnomalies(charger.charger_id))
      );
      setData(allAnomalies.flat());
    } catch (err) {
      const errorMessage = getErrorMessage(err);
      setError(errorMessage);
      toast.error(`Failed to load anomalies: ${errorMessage}`);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem("off-key:last-seen-anomalies", new Date().toISOString());
    const timeoutId = window.setTimeout(() => {
      void fetchAllAnomalies();
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [fetchAllAnomalies]);

  const sortedData = useMemo(
    () =>
      data
        .slice()
        .sort(
          (left, right) =>
            new Date(right.timestamp).getTime() - new Date(left.timestamp).getTime()
        ),
    [data]
  );

  const affectedChargers = useMemo(
    () => new Set(data.map((anomaly) => anomaly.charger_id)).size,
    [data]
  );

  const probabilityValueCount = useMemo(
    () =>
      data.filter((anomaly) => isProbabilityAnomalyValue(anomaly.value_type))
        .length,
    [data]
  );

  const handleDelete = async (anomaly: Anomaly) => {
    if (!anomaly.anomaly_id) {
      toast.error("Cannot delete anomaly without anomaly_id");
      return;
    }
    try {
      await deleteAnomaly(anomaly.anomaly_id);

      toast.success("Anomaly deleted successfully");
      await fetchAllAnomalies();
    } catch (err) {
      const detail = getErrorMessage(err);
      const errorMessage = `Error while deleting: ${detail}`;
      setError(errorMessage);
      toast.error(errorMessage);
    }
  };

  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          eyebrow="Detection"
          title="Anomalies"
          description="Review detected anomalies across the charger fleet and jump directly into affected telemetry."
          actions={
            <Button
              variant="outline"
              onClick={fetchAllAnomalies}
              disabled={isLoading}
            >
              <RefreshCw className={isLoading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
              Refresh
            </Button>
          }
        />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
          <MetricCard
            label="Anomalies"
            value={data.length}
            helper="Current result set"
            tone={data.length > 0 ? "warning" : "default"}
          />
          <MetricCard
            label="Chargers"
            value={affectedChargers}
            helper="With detections"
            tone="info"
          />
          <MetricCard
            label="p-values"
            value={probabilityValueCount}
            helper="Tail and conformal"
          />
        </div>

        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        ) : null}

        <SectionPanel
          title="Fleet Anomalies"
          description={
            isLoading
              ? "Loading anomalies..."
              : `${sortedData.length} anomalies loaded`
          }
          contentClassName="p-0"
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableHead>Charger ID</TableHead>
                <TableHead>Timestamp</TableHead>
                <TableHead>Telemetry Type</TableHead>
                <TableHead>Sensors</TableHead>
                <TableHead>Anomaly Type</TableHead>
                <TableHead>Signal</TableHead>
                <TableHead className="text-right">Delete</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                    Loading anomalies...
                  </TableCell>
                </TableRow>
              ) : sortedData.length > 0 ? (
                sortedData.map((anomaly) => (
                  <TableRow
                    key={
                      anomaly.anomaly_id ||
                      `${anomaly.charger_id}-${anomaly.timestamp}-${anomaly.telemetry_type}-${anomaly.anomaly_type}`
                    }
                  >
                    <TableCell className="font-medium">
                      <Link
                        to={`/details/${anomaly.charger_id}`}
                        className="text-foreground hover:underline"
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
                    <TableCell>
                      <span className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-800 dark:bg-sky-950/40 dark:text-sky-200">
                        {anomaly.telemetry_type === "__multivariate__"
                          ? "multivariate"
                          : anomaly.telemetry_type}
                      </span>
                    </TableCell>
                    <TableCell
                      className="max-w-64 truncate text-xs text-muted-foreground"
                      title={formatAnomalySensorSet(anomaly.sensor_set)}
                    >
                      {formatAnomalySensorSet(anomaly.sensor_set)}
                    </TableCell>
                    <TableCell>{anomaly.anomaly_type}</TableCell>
                    <TableCell>
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-medium ${getAnomalyValueClassName(
                          anomaly.anomaly_value,
                          anomaly.value_type
                        )}`}
                        title={getAnomalyValueLabel(anomaly.value_type)}
                      >
                        {formatAnomalyValue(
                          anomaly.anomaly_value,
                          anomaly.value_type
                        )}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(anomaly)}
                        aria-label="delete"
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                    No data found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </SectionPanel>
      </PageShell>
    </>
  );
}
