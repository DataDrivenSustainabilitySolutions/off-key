import { useAuth } from "@/auth/AuthContext";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import toast from "react-hot-toast";

import {
  MetricCard,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
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
import { useCatalogue } from "@/features/workspace/catalogue-context";
import { SourceScope } from "@/features/workspace/SourceScope";
import { filterSourceReports, reportLabels } from "@/features/workspace/reporting-scope";
import { withCatalogueSource } from "@/features/workspace/catalogue-navigation";

export default function AnomalyTable() {
  const { isAdmin } = useAuth();
  const { streamIds, system, selected } = useCatalogue();
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
      setError(getErrorMessage(err));
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

  const columns = isAdmin ? 6 : 5;
  const scopedData = useMemo(() => filterSourceReports(data, streamIds, system.snapshot?.runtime), [data, streamIds, system.snapshot?.runtime]);
  const sortedData = useMemo(
    () =>
      scopedData
        .slice()
        .sort(
          (left, right) =>
            new Date(right.timestamp).getTime() - new Date(left.timestamp).getTime()
        ),
    [scopedData]
  );

  const affectedChargers = useMemo(
    () => new Set(scopedData.map((anomaly) => anomaly.charger_id)).size,
    [scopedData]
  );

  const probabilityValueCount = useMemo(
    () =>
      scopedData.filter((anomaly) => isProbabilityAnomalyValue(anomaly.value_type))
        .length,
    [scopedData]
  );

  const labels = useMemo(() => reportLabels(system.snapshot?.document, system.snapshot?.runtime), [system.snapshot]);
  const formatTime = (timestamp: string) => new Date(timestamp).toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
  const metric = (value: number) => isLoading || (error && !data.length) ? "—" : value;

  const handleDelete = async (anomaly: Anomaly) => {
    if (!anomaly.anomaly_id) {
      toast.error("This anomaly has no ID and cannot be deleted.");
      return;
    }
    if (!window.confirm(`Delete the anomaly for ${labels.entity(anomaly.charger_id)} at ${formatTime(anomaly.timestamp)}? This cannot be undone.`)) return;
    try {
      await deleteAnomaly(anomaly.anomaly_id);

      toast.success("Anomaly deleted");
      await fetchAllAnomalies();
    } catch (err) {
      toast.error(`The anomaly could not be deleted: ${getErrorMessage(err)}`);
    }
  };

  return (
    <>
      <PageShell>
        <PageHeader
          title="Reporting"
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

        <SourceScope />
        {system.error && <p role="alert" className="flex flex-wrap items-center gap-x-3 text-sm text-destructive">Catalogue status unavailable: {system.error}
          <Button variant="link" className="h-auto px-0 sm:h-auto" onClick={() => void system.refresh()}>Retry catalogue</Button>
        </p>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
          <MetricCard
            label="Anomalies"
            value={metric(scopedData.length)}
            tone={scopedData.length > 0 ? "warning" : "default"}
          />
          <MetricCard
            label="Affected entities"
            value={metric(affectedChargers)}
            tone="info"
          />
          <MetricCard
            label="p-values"
            value={metric(probabilityValueCount)}
          />
        </div>

        {error ? (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
            <span>Anomalies could not be loaded: {error}</span>
            <Button variant="outline" size="sm" onClick={fetchAllAnomalies} disabled={isLoading}>Try again</Button>
          </div>
        ) : null}

        <SectionPanel
          title="Events"
          contentClassName="p-0"
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableHead>Entity</TableHead>
                <TableHead>Timestamp</TableHead>
                <TableHead>Readings</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Signal</TableHead>
                {isAdmin && <TableHead className="text-right"><span className="sr-only">Actions</span></TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={columns} className="h-24 text-center text-muted-foreground">
                    Loading anomalies…
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
                        to={withCatalogueSource(`/details/${anomaly.charger_id}`, selected)}
                        className="text-foreground hover:underline"
                      >
                        {labels.entity(anomaly.charger_id)}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {formatTime(anomaly.timestamp)}
                    </TableCell>
                    <TableCell className="max-w-96">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="shrink-0 rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-800 dark:bg-sky-950/40 dark:text-sky-200">
                          {anomaly.telemetry_type === "__multivariate__"
                            ? "multivariate"
                            : labels.reading(anomaly.charger_id, anomaly.telemetry_type)}
                        </span>
                        {/* A single reading is already named by its badge. */}
                        {(anomaly.telemetry_type === "__multivariate__" || (anomaly.sensor_set?.length ?? 0) > 1) && (
                          <span
                            className="min-w-0 truncate text-xs text-muted-foreground"
                            title={formatAnomalySensorSet(anomaly.sensor_set?.map((key) => labels.reading(anomaly.charger_id, key)))}
                          >
                            {formatAnomalySensorSet(anomaly.sensor_set?.map((key) => labels.reading(anomaly.charger_id, key)))}
                          </span>
                        )}
                      </div>
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
                    {isAdmin && <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => handleDelete(anomaly)}
                        aria-label={`Delete anomaly for ${labels.entity(anomaly.charger_id)} at ${formatTime(anomaly.timestamp)}`}
                      >
                        Delete
                      </Button>
                    </TableCell>}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={columns} className="h-24 text-center text-muted-foreground">
                    {error ? "Anomalies could not be loaded." : "No anomalies recorded."}
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
