import { Activity, useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";
import { useBlocker } from "react-router-dom";

import { PageHeader, PageShell } from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
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
  const [statusError, setStatusError] = useState("");
  const initialized = useRef(false);
  const reviewTrigger = useRef<HTMLElement | null>(null);
  const collectionTab = useRef<HTMLButtonElement>(null);
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
    if (
      window.confirm(
        "Leave this page and discard your unsaved collection draft?",
      )
    )
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
    reviewTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
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
          <p role={statusError ? "alert" : "status"}>
            {statusError || "Loading catalog…"}
          </p>
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
  const conflict = snapshot.revision !== baseRevision;

  return (
    <>
      <NavigationBar />
      <PageShell className="[&>div]:gap-5 [&>div]:py-6">
        <PageHeader
          title="Data sources"
          description="Choose what to collect from AmbiBox. Review and apply when ready."
          actions={
            <>
              <Button variant="outline" onClick={exportCatalog}>
                Export catalog
              </Button>
              {snapshot.can_edit && (
                <Button
                  disabled={busy || conflict || !changed}
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
        {statusError && (
          <p role="alert" className="text-sm text-destructive">
            Live status could not be refreshed: {statusError}. Retrying
            automatically.
          </p>
        )}
        {conflict && (
          <p role="alert" className="rounded-lg border p-4 text-sm">
            Someone saved a newer catalog. Export your draft if needed, then
            reload to continue.
          </p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3 text-sm">
          <div>
            <p>
              <strong>{chargers.length} chargers</strong> · {activeCount} of{" "}
              {sensors.length} measurements in draft
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {draft.sources.filter((source) => source.verified).length}{" "}
              observed brokers ·{" "}
              {draft.sources.filter((source) => !source.verified).length}{" "}
              candidate hosts
            </p>
          </div>
          <div className="text-xs text-muted-foreground">
            <p>
              Live collection:{" "}
              {runtimeLabel(snapshot.collection, snapshot.revision)}
            </p>
            <p className="mt-1">
              Broker routes: {runtimeLabel(snapshot.ingress, snapshot.revision)}{" "}
              · Saved revision {snapshot.revision}
            </p>
          </div>
        </div>
        {(snapshot.collection.error || snapshot.ingress.error) && (
          <p role="alert" className="text-sm text-destructive">
            {snapshot.collection.error ?? snapshot.ingress.error}
          </p>
        )}
        {preview && (
          <Sheet
            open
            onOpenChange={(open) => {
              if (!open && !busy) setPreview(null);
            }}
          >
            <SheetContent
              className="w-full overflow-y-auto sm:max-w-2xl"
              onCloseAutoFocus={(event) => {
                event.preventDefault();
                const trigger = reviewTrigger.current;
                if (trigger?.isConnected && !trigger.matches(":disabled"))
                  trigger.focus();
                else collectionTab.current?.focus();
              }}
            >
              <SheetHeader className="pr-12">
                <SheetTitle>Review collection changes</SheetTitle>
                <SheetDescription>
                  Check the exact changes below. Applying updates the running
                  collection configuration.
                </SheetDescription>
              </SheetHeader>
              {error && (
                <p role="alert" className="px-5 text-sm text-destructive">
                  {error}
                </p>
              )}
              {conflict && (
                <p role="alert" className="px-5 text-sm text-destructive">
                  Someone saved a newer catalog. Close this review, export your
                  draft if needed, then reload the saved catalog.
                </p>
              )}
              <CollectionReview
                saved={snapshot.catalog}
                preview={preview}
                pauseMonitors={pauseMonitors}
                busy={busy}
                conflict={conflict}
                onPauseMonitors={setPauseMonitors}
                onApply={() =>
                  void task(async () => {
                    const result = await apiUtils.put<CatalogSnapshot>(
                      endpoint,
                      {
                        expected_revision: preview.revision,
                        catalog: preview.catalog,
                        pause_affected_monitors: pauseMonitors,
                      },
                    );
                    setSnapshot({ ...result, can_edit: snapshot.can_edit });
                    setDraft(result.catalog);
                    setBaseRevision(result.revision);
                    setPreview(null);
                    toast.success(
                      "Configuration saved. Workers are applying it.",
                    );
                  })
                }
              />
            </SheetContent>
          </Sheet>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            ref={collectionTab}
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
              (!changed ||
                window.confirm(
                  "Discard your unsaved catalog and collection changes?",
                )) &&
              void task(async () => {
                const saved = await apiUtils.get<CatalogSnapshot>(endpoint);
                setSnapshot(saved);
                change(saved.catalog);
                setBaseRevision(saved.revision);
              })
            }
          >
            {changed ? "Discard draft" : "Reload saved catalog"}
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
            busy={busy || conflict}
            change={change}
            task={task}
            validate={validate}
          />
        </Activity>
        <Activity mode={tab === "collection" ? "visible" : "hidden"}>
          <CollectionPanel
            draft={draft}
            snapshot={snapshot}
            busy={busy || conflict}
            conflict={conflict}
            change={change}
            onCatalog={() => setTab("catalog")}
            onLoadInventory={() =>
              void task(async () =>
                change(
                  await apiUtils.get<Catalog>(`${endpoint}/ambibox-template`),
                ),
              )
            }
          />
        </Activity>
        <details className="rounded-xl border bg-card p-5">
          <summary className="cursor-pointer font-medium">
            Live diagnostics
          </summary>
          <div className="mt-5 space-y-5">
            <CollectionHealth snapshot={snapshot} />
          </div>
        </details>
        {changed && snapshot.can_edit && (
          <div className="sticky bottom-3 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-background p-4 shadow-lg">
            <p className="text-sm">
              Unsaved draft · {activeCount} measurements selected. Live
              collection is unchanged.
            </p>
            <Button
              disabled={busy || conflict}
              onClick={() => void task(() => validate(draft))}
            >
              Review and apply
            </Button>
          </div>
        )}
      </PageShell>
    </>
  );
}
