import { Activity, useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";

import {
  MetricCard,
  PageHeader,
  PageShell,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import type {
  Catalog,
  CatalogPreview,
  CatalogSnapshot,
} from "@/types/collection";
import { effectivePolicy, runtimeLabel } from "@/types/collection";
import { CatalogPanel } from "./sources/CatalogPanel";
import { CollectionPanel } from "./sources/CollectionPanel";
import { CollectionReview } from "./sources/CollectionReview";
import { StorageSummary } from "./sources/StorageSummary";
import { CollectionHealth } from "./sources/CollectionHealth";

const endpoint = "/v1/sources";

export default function DataSources() {
  const [snapshot, setSnapshot] = useState<CatalogSnapshot | null>(null);
  const [draft, setDraft] = useState<Catalog | null>(null);
  const [baseRevision, setBaseRevision] = useState(0);
  const [tab, setTab] = useState<"collection" | "catalog">("collection");
  const [preview, setPreview] = useState<CatalogPreview | null>(null);
  const [pauseMonitors, setPauseMonitors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const initialized = useRef(false);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const first = !initialized.current;
        const data = await apiUtils.get<CatalogSnapshot>(
          first ? endpoint : `${endpoint}/status`,
        );
        if (!active) return;
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
        if (active) setError(getErrorMessage(e));
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
    setPreview(null);
    setPauseMonitors(false);
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
  const validate = async (catalog: Catalog) => {
    const result = await apiUtils.post<CatalogPreview>(`${endpoint}/preview`, {
      expected_revision: baseRevision,
      catalog,
    });
    setPreview(result);
    setDraft(result.catalog);
    setPauseMonitors(false);
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
          <p role={error ? "alert" : "status"}>{error || "Loading catalog…"}</p>
        </PageShell>
      </>
    );
  const chargers = draft.sources.flatMap((source) => source.chargers);
  const sensors = chargers.flatMap((charger) =>
    charger.sensors.map((sensor) => ({
      sensor,
      policy: effectivePolicy(draft, charger, sensor),
    })),
  );
  const activeCount = sensors.filter(
    (item) => item.policy.mode !== "off",
  ).length;
  const changed = JSON.stringify(draft) !== JSON.stringify(snapshot.catalog);
  const conflict = snapshot.revision !== baseRevision;

  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          title="Data sources"
          eyebrow="AmbiBox"
          description="Choose chargers and measurements to collect. Saving applies the selection before telemetry reaches storage and monitoring."
          actions={
            <>
              <Button variant="outline" onClick={exportCatalog}>
                Export catalog
              </Button>
              {snapshot.can_edit && (
                <Button
                  disabled={busy || conflict}
                  onClick={() => void task(() => validate(draft))}
                >
                  Review changes
                </Button>
              )}
            </>
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
        {conflict && (
          <p role="alert" className="rounded-lg border p-4 text-sm">
            Someone saved a newer catalog. Export your draft if needed, then
            reload to continue.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-4">
          <MetricCard
            label="Catalog"
            value={chargers.length}
            helper={`${draft.sources.filter((source) => source.verified).length} observed brokers · ${draft.sources.filter((source) => !source.verified).length} candidate hosts`}
          />
          <MetricCard
            label="Selected sensors"
            value={activeCount}
            helper={`of ${sensors.length} in this draft`}
          />
          <MetricCard
            label="Collection"
            value={
              <span className="text-base">
                {runtimeLabel(snapshot.collection, snapshot.revision)}
              </span>
            }
            helper={`Saved revision ${snapshot.revision}${changed ? " · unsaved edits" : ""}`}
          />
          <MetricCard
            label="Broker routes"
            value={
              <span className="text-base">
                {runtimeLabel(snapshot.ingress, snapshot.revision)}
              </span>
            }
            helper={
              snapshot.ingress.error ??
              `${Object.values(snapshot.ingress.sources ?? {}).filter((source) => source.status === "connected").length} connected`
            }
          />
        </div>
        <CollectionHealth snapshot={snapshot} />
        <StorageSummary />
        {(snapshot.collection.error || snapshot.ingress.error) && (
          <p role="alert" className="text-sm text-destructive">
            {snapshot.collection.error ?? snapshot.ingress.error}
          </p>
        )}
        {preview && (
          <CollectionReview
            saved={snapshot.catalog}
            preview={preview}
            pauseMonitors={pauseMonitors}
            busy={busy}
            conflict={conflict}
            onPauseMonitors={setPauseMonitors}
            onApply={() =>
              void task(async () => {
                const result = await apiUtils.put<CatalogSnapshot>(endpoint, {
                  expected_revision: preview.revision,
                  catalog: preview.catalog,
                  pause_affected_monitors: pauseMonitors,
                });
                setSnapshot({ ...result, can_edit: snapshot.can_edit });
                setDraft(result.catalog);
                setBaseRevision(result.revision);
                setPreview(null);
                toast.success("Configuration saved. Workers are applying it.");
              })
            }
          />
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={tab === "collection" ? "default" : "outline"}
            onClick={() => setTab("collection")}
          >
            Collection
          </Button>
          <Button
            variant={tab === "catalog" ? "default" : "outline"}
            onClick={() => setTab("catalog")}
          >
            Catalog
          </Button>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() =>
              void task(async () => {
                const saved = await apiUtils.get<CatalogSnapshot>(endpoint);
                setSnapshot(saved);
                change(saved.catalog);
                setBaseRevision(saved.revision);
              })
            }
          >
            Reload saved catalog
          </Button>
          {!snapshot.can_edit && (
            <span className="text-sm text-muted-foreground">
              View only · an administrator can change collection
            </span>
          )}
        </div>
        <Activity mode={tab === "catalog" ? "visible" : "hidden"}>
          <CatalogPanel
            draft={draft}
            canEdit={snapshot.can_edit}
            busy={busy}
            change={change}
            task={task}
            validate={validate}
          />
        </Activity>
        <Activity mode={tab === "collection" ? "visible" : "hidden"}>
          <CollectionPanel
            draft={draft}
            snapshot={snapshot}
            busy={busy}
            change={change}
          />
        </Activity>
      </PageShell>
    </>
  );
}
