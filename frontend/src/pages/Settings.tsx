import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  MetricCard,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import type { StorageStatus } from "@/types/collection";

export default function Settings() {
  const [status, setStatus] = useState<StorageStatus | null>(null);
  const [error, setError] = useState("");
  const [request, setRequest] = useState(0);

  useEffect(() => {
    let active = true;
    void apiUtils.get<StorageStatus>("/v1/sources/storage").then(
      (result) => {
        if (active) setStatus(result);
      },
      (reason) => {
        if (active) setError(getErrorMessage(reason));
      },
    );
    return () => {
      active = false;
    };
  }, [request]);

  const gigabytes = status && status.database_size_bytes >= 1_000_000_000;
  const size = status && (
    status.database_size_bytes / (gigabytes ? 1_000_000_000 : 1_000_000)
  ).toLocaleString(undefined, { maximumFractionDigits: 1 });

  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          title="Settings"
          actions={
            <Button variant="outline" asChild>
              <Link to="/account">Back to account</Link>
            </Button>
          }
        />
        <SectionPanel
          title="Storage and retention"
          help="Your operator manages retention. Cleanup runs periodically, so expiry is not an exact deletion deadline. Retention covers telemetry and monitoring evidence; size includes all tables and indexes, but excludes backups and server logs."
          actions={
            <Button
              variant="outline"
              disabled={!status && !error}
              onClick={() => {
                setStatus(null);
                setError("");
                setRequest((current) => current + 1);
              }}
            >
              Refresh storage
            </Button>
          }
        >
          {error ? (
            <p role="alert">Storage information unavailable: {error}</p>
          ) : status ? (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <MetricCard
                  label="Database size"
                  value={`${size} ${gigabytes ? "GB" : "MB"}`}
                />
                {status.retention_policies.map((policy) => (
                  <MetricCard
                    key={policy.table}
                    label={
                      policy.table === "telemetry"
                        ? "Telemetry retention"
                        : "Monitoring evidence retention"
                    }
                    value={
                      policy.retention_days === null
                        ? "Not configured"
                        : `${policy.retention_days.toLocaleString()} ${policy.retention_days === 1 ? "day" : "days"}`
                    }
                    helper={
                      policy.retention_days === null
                        ? undefined
                        : policy.scheduled
                          ? "Cleanup enabled"
                          : "Cleanup paused"
                    }
                    tone={
                      policy.retention_days !== null && policy.scheduled
                        ? "default"
                        : "warning"
                    }
                  />
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Checked {new Date(status.checked_at).toLocaleString()}.
              </p>
            </>
          ) : (
            <p role="status">Loading storage information…</p>
          )}
        </SectionPanel>
      </PageShell>
    </>
  );
}
