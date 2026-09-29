import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";
import { useBlocker } from "react-router-dom";

import { PageHeader, PageShell } from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import { catalogRemovals } from "@/lib/catalog-changes";
import { validPolicy } from "@/lib/collection-selection";
import { getErrorMessage } from "@/lib/errors";
import type {
  Catalog,
  CatalogPreview,
  CatalogSnapshot,
} from "@/types/collection";
import { effectivePolicy, runtimeLabel } from "@/types/collection";
import { CatalogPanel } from "./sources/CatalogPanel";

const endpoint = "/v1/sources";

export default function DataSources() {
  const [snapshot, setSnapshot] = useState<CatalogSnapshot | null>(null);
  const [draft, setDraft] = useState<Catalog | null>(null);
  const [baseRevision, setBaseRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [statusError, setStatusError] = useState("");
  const initialized = useRef(false);
  const changed =
    !!draft &&
    !!snapshot &&
    JSON.stringify(draft) !== JSON.stringify(snapshot.catalog);
  const navigation = useBlocker(
    ({ currentLocation, nextLocation }) =>
      changed && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (navigation.state !== "blocked") return;
    if (window.confirm("Leave this page and discard your unsaved changes?"))
      navigation.proceed();
    else navigation.reset();
  }, [navigation]);

  useEffect(() => {
    if (!changed) return;
    const preventLoss = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [changed]);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const first = !initialized.current;
        const data = await apiUtils.get<CatalogSnapshot>(
          first ? endpoint : `${endpoint}/status`,
        );
        if (!active) return;
        setStatusError("");
        setSnapshot((current) => {
          if (current && current.revision > data.revision) return current;
          if (first) return data;
          return (
            current && {
              ...current,
              revision: data.revision,
              ingress: data.ingress,
              collection: data.collection,
            }
          );
        });
        if (!initialized.current) {
          initialized.current = true;
          setDraft(data.catalog);
          setBaseRevision(data.revision);
        }
      } catch (e) {
        if (active) setStatusError(getErrorMessage(e));
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const change = (catalog: Catalog) => {
    setDraft(catalog);
    setError("");
  };
  const task = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const importCatalog = async (catalog: Catalog) => {
    const result = await apiUtils.post<CatalogPreview>(`${endpoint}/preview`, {
      expected_revision: baseRevision,
      catalog,
    });
    change(result.catalog);
  };
  const exportCatalog = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "ambibox-catalog.json";
    link.click();
    URL.revokeObjectURL(url);
  };

  if (!snapshot || !draft)
    return (
      <>
        <NavigationBar />
        <PageShell>
          <PageHeader title="Data sources" />
          <p role={statusError ? "alert" : "status"}>
            {statusError || "Loading catalog…"}
          </p>
        </PageShell>
      </>
    );

  const chargers = draft.sources.flatMap((source) => source.chargers);
  const sensors = chargers.flatMap((charger) =>
    charger.sensors.map((sensor) => effectivePolicy(draft, charger, sensor)),
  );
  const invalid = chargers.flatMap((charger) =>
    charger.sensors
      .filter((sensor) => !validPolicy(effectivePolicy(draft, charger, sensor)))
      .map((sensor) => `${charger.label} · ${sensor.label}`),
  );
  const activeCount = sensors.filter((policy) => policy.mode !== "off").length;
  const conflict = snapshot.revision !== baseRevision;
  const runtime = [snapshot.collection, snapshot.ingress].map((state) =>
    runtimeLabel(state, snapshot.revision),
  );
  const applicationError = snapshot.collection.error || snapshot.ingress.error;
  const status = conflict
    ? "Newer changes are available"
    : snapshot.revision === 0
      ? "No saved configuration"
      : applicationError || runtime.includes("error")
        ? "Saved · Changes could not be applied"
        : runtime.includes("Disabled by operator")
          ? "Saved · Collection disabled by operator"
          : statusError || runtime.includes("Waiting for worker")
            ? "Saved · Waiting for live status"
            : runtime.every((label) => label === "applied")
              ? "Changes applied"
              : "Saved · Applying changes…";

  const save = async () => {
    if (invalid.length) return;
    setSaving(true);
    await task(async () => {
      const preview = await apiUtils.post<CatalogPreview>(
        `${endpoint}/preview`,
        {
          expected_revision: baseRevision,
          catalog: draft,
        },
      );
      const removals = catalogRemovals(snapshot.catalog, preview.catalog);
      const monitors = preview.affected_monitors;
      const consequences = [
        ...(removals.length
          ? [`Remove from the catalog:\n${removals.join("\n")}`]
          : []),
        ...(monitors.length
          ? [
              `Stop these running monitors:\n${monitors.map((monitor) => monitor.name).join("\n")}\nThey must be restarted with fresh calibration.`,
            ]
          : []),
      ];
      if (
        consequences.length &&
        !window.confirm(`${consequences.join("\n\n")}\n\nSave these changes?`)
      )
        return;
      const result = await apiUtils.put<CatalogSnapshot>(endpoint, {
        expected_revision: preview.revision,
        catalog: preview.catalog,
        pause_affected_monitors: monitors.length > 0,
      });
      setSnapshot((current) => ({
        ...result,
        can_edit: snapshot.can_edit,
        ...(current && current.revision > result.revision
          ? {
              revision: current.revision,
              ingress: current.ingress,
              collection: current.collection,
            }
          : {}),
      }));
      setDraft(result.catalog);
      setBaseRevision(result.revision);
      toast.success("Changes saved");
    });
    setSaving(false);
  };

  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          title="Data sources"
          actions={
            <Button variant="outline" onClick={exportCatalog}>
              Export catalog
            </Button>
          }
        />
        {error && (
          <p
            role="alert"
            className="rounded-lg border border-destructive p-4 text-sm text-destructive"
          >
            {error}
          </p>
        )}
        {statusError && (
          <p role="alert" className="text-sm text-destructive">
            Live status could not be refreshed: {statusError}. Retrying
            automatically.
          </p>
        )}
        {conflict && (
          <p role="alert" className="rounded-lg border p-4 text-sm">
            Someone saved a newer catalog. Export your changes if needed, then
            reload to continue.
          </p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3 text-sm">
          <p>
            <strong>{draft.sources.length} brokers</strong> · {chargers.length}{" "}
            chargers · {activeCount} of {sensors.length} measurements enabled
          </p>
          {!snapshot.can_edit && (
            <p className="text-muted-foreground">
              View only · administrator access required to edit
            </p>
          )}
        </div>
        {applicationError && (
          <p role="alert" className="text-sm text-destructive">
            {applicationError}
          </p>
        )}
        <CatalogPanel
          draft={draft}
          snapshot={snapshot}
          busy={busy || conflict}
          change={change}
          task={task}
          importCatalog={importCatalog}
        />
        {invalid.length > 0 && (
          <p role="alert" className="text-sm text-destructive">
            {invalid.join(", ")}: sampling intervals must be whole seconds from
            1 to 3600.
          </p>
        )}
        <div className="sticky bottom-3 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-background p-4 shadow-lg">
          <div className="text-sm" role="status">
            <p className="font-medium">
              {changed ? "Unsaved changes" : status}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() =>
                (!changed || window.confirm("Discard your unsaved changes?")) &&
                void task(async () => {
                  const saved = await apiUtils.get<CatalogSnapshot>(endpoint);
                  setSnapshot(saved);
                  change(saved.catalog);
                  setBaseRevision(saved.revision);
                })
              }
            >
              {changed ? "Discard changes" : "Reload saved catalog"}
            </Button>
            {snapshot.can_edit && (
              <Button
                disabled={busy || conflict || !changed || invalid.length > 0}
                onClick={() => void save()}
              >
                {saving ? "Saving…" : "Save changes"}
              </Button>
            )}
          </div>
        </div>
      </PageShell>
    </>
  );
}
