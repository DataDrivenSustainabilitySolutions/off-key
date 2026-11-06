import { useEffect, useState } from "react";

import { SettingsGroup, SettingsRow } from "@/components/SettingsGroup";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { RelativeTime } from "@/components/RelativeTime";
import type { StorageStatus } from "@/types/collection";
import { CollectionHealth } from "./CollectionHealth";

const retentionLabels = {
  telemetry: "Telemetry retention",
  monitoring_evidence: "Monitoring evidence retention",
  anomalies: "Anomaly retention",
} as const;

function formatBytes(bytes: number) {
  const gigabytes = bytes >= 1_000_000_000;
  const value = (bytes / (gigabytes ? 1_000_000_000 : 1_000_000)).toLocaleString(undefined, {
    maximumFractionDigits: 1,
  });
  return `${value} ${gigabytes ? "GB" : "MB"}`;
}

export default function SystemStatusSettings() {
  const [status, setStatus] = useState<StorageStatus | null>(null);
  const [error, setError] = useState("");
  const [request, setRequest] = useState(0);

  useEffect(() => {
    let active = true;
    void apiUtils.get<StorageStatus>("/v1/storage").then(
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

  const cap = status?.storage_cap_bytes ?? null;
  const capWarning = !!status && cap !== null && (!status.storage_cap_scheduled || status.capped_size_bytes >= cap * 0.9);

  return (
    <>
      <CollectionHealth />
      <SettingsGroup
        title="Storage and retention"
        help="Retention is managed by the operator. Cleanup runs periodically. Database size includes tables and indexes, excluding backups and logs. The storage cap, when set, removes the oldest telemetry and evidence first, even inside the retention window."
        actions={
          <Button
            variant="outline"
            size="sm"
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
        footer={status && <>Checked <RelativeTime value={status.checked_at} />.</>}
        padded={!status}
      >
        {error ? (
          <p role="alert" className="text-destructive">Storage information unavailable: {error}</p>
        ) : status ? (
          <>
            <SettingsRow label="Database size">{formatBytes(status.database_size_bytes)}</SettingsRow>
            <SettingsRow
              label="Storage cap"
              tone={capWarning ? "warning" : "default"}
              detail={
                cap === null
                  ? "Retention days only"
                  : status.storage_cap_scheduled
                    ? `${formatBytes(status.capped_size_bytes)} used by telemetry and evidence`
                    : "Cleanup paused"
              }
            >
              {cap === null ? "No cap" : formatBytes(cap)}
            </SettingsRow>
            {status.retention_policies.map((policy) => (
              <SettingsRow
                key={policy.table}
                label={retentionLabels[policy.table]}
                tone={policy.retention_days !== null && policy.scheduled ? "default" : "warning"}
                detail={policy.retention_days === null ? undefined : policy.scheduled ? "Cleanup enabled" : "Cleanup paused"}
              >
                {policy.retention_days === null
                  ? "Not configured"
                  : `${policy.retention_days.toLocaleString()} ${policy.retention_days === 1 ? "day" : "days"}`}
              </SettingsRow>
            ))}
          </>
        ) : (
          <p role="status" className="text-muted-foreground">Loading storage information…</p>
        )}
      </SettingsGroup>
    </>
  );
}
