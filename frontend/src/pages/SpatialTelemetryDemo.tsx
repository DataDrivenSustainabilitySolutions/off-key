import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  CircleHelp,
  Layers,
  Maximize2,
  Pause,
  Play,
  Radio,
  Settings2,
  X,
} from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { SpatialSidebar } from "@/features/spatial/SpatialSidebar";
import { SpatialHelp } from "@/features/spatial/SpatialHelp";
import { SpatialCanvas } from "@/features/spatial/SpatialCanvas";
import { TelemetryInspector } from "@/features/spatial/TelemetryInspector";
import { CollectionInspector } from "@/features/spatial/CollectionInspector";
import { WorkspacePreferences } from "@/features/spatial/WorkspacePreferences";
import {
  createDemoTopology,
  DEFAULT_CAMERA,
  resolveTopology,
} from "@/features/spatial/model";
import {
  PassiveCatalogTelemetry,
  serializeSpatialCatalog,
  type SpatialCatalogProjection,
} from "@/features/spatial/catalog";
import { loadWorkspace, saveWorkspace } from "@/features/spatial/workspace";
import { reconcileCatalogWorkspace } from "@/features/spatial/catalogWorkspace";
import {
  useCatalogNames,
  fetchSavedSpatialCatalog,
} from "@/features/spatial/useCatalogNames";
import {
  applyCatalogWorkspaceNames,
  catalogNameTarget,
  catalogGroupNameTarget,
} from "@/features/spatial/catalogNames";
import { DemoTelemetry } from "@/features/spatial/telemetry";
import {
  HslTelemetry,
  HSL_INITIAL_TOPOLOGY,
} from "@/features/spatial/live-source";
import type {
  CameraPose,
  RenderStats,
  SpatialWorkspace,
  Topology,
} from "@/features/spatial/types";
import "@/features/spatial/spatial.css";

type SourceMode = "demo" | "hsl" | "ambibox";
const ignoreMove = () => undefined;
const automaticWorkspace = (workspace: SpatialWorkspace): SpatialWorkspace => ({
  ...workspace,
  layoutMode: "automatic",
  positions: {},
  locks: {},
  groups: workspace.groups.map((group) => ({ ...group, locked: false })),
});
const emptyStats: RenderStats = {
  fps: 0,
  drawCalls: 0,
  visibleNodes: 0,
  particles: 0,
};

export default function SpatialTelemetryDemo({
  initialSource = "demo",
  onReturn,
}: {
  initialSource?: "demo" | "hsl";
  onReturn?: () => void;
}) {
  const { userId } = useAuth();
  return (
    <SpatialSession
      key={userId ?? "local"}
      userId={userId}
      initialSource={initialSource}
      onReturn={onReturn}
    />
  );
}

function hasLayout(key: string) {
  try {
    return !!window.localStorage.getItem(key);
  } catch {
    return false;
  }
}

function SpatialSession({
  userId,
  initialSource,
  onReturn,
}: {
  userId: number | null;
  initialSource: "demo" | "hsl";
  onReturn?: () => void;
}) {
  const catalogKey = `aberration:spatial:catalog:v1:${userId ?? "local"}`;
  const [catalog, setCatalog] = useState<SpatialCatalogProjection>();
  const [catalogVersion, setCatalogVersion] = useState(0);
  const [importNotice, setImportNotice] = useState("");
  const [source, setSource] = useState<SourceMode>(initialSource);
  const [sensorCount, setSensorCount] = useState(18);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  return (
    <SpatialWorkspaceView
      key={`${userId ?? "local"}:${source}:${sensorCount}:${catalogVersion}`}
      storageKey={`aberration:spatial:v1:${userId ?? "local"}:${source}${source === "demo" && sensorCount !== 18 ? `:${sensorCount}` : source === "ambibox" ? `:${catalog?.datasetKey}` : ""}`}
      source={source}
      sensorCount={sensorCount}
      catalog={catalog}
      importNotice={importNotice}
      onCatalog={(imported) => {
        let cached = false;
        try {
          window.localStorage.setItem(
            catalogKey,
            serializeSpatialCatalog(imported),
          );
          cached = true;
        } catch {
          /* The preview remains usable without browser storage. */
        }
        setCatalog(imported);
        setCatalogVersion((current) => current + 1);
        setSource("ambibox");
        setPreferencesOpen(false);
        setImportNotice(
          cached
            ? "Catalog loaded. Presentation saved locally; collection settings were not applied."
            : "Catalog imported for this session. Browser storage is unavailable.",
        );
      }}
      onCanonicalCatalog={(updated) => {
        try {
          window.localStorage.setItem(
            catalogKey,
            serializeSpatialCatalog(updated),
          );
        } catch {
          /* Database names remain canonical without a browser cache. */
        }
        setCatalog(updated);
      }}
      preferencesOpen={preferencesOpen}
      onReturn={onReturn}
      onSource={(next) => {
        setPreferencesOpen(true);
        setSource(next);
      }}
      onSensorCount={(count) => {
        setPreferencesOpen(true);
        setSensorCount(count);
      }}
    />
  );
}

type WorkspaceProps = {
  onReturn?: () => void;
  storageKey: string;
  source: SourceMode;
  sensorCount: number;
  preferencesOpen: boolean;
  catalog?: SpatialCatalogProjection;
  importNotice: string;
  onCatalog: (catalog: SpatialCatalogProjection) => void;
  onCanonicalCatalog: (catalog: SpatialCatalogProjection) => void;
  onSource: (source: SourceMode) => void;
  onSensorCount: (count: number) => void;
};

function SpatialWorkspaceView({
  onReturn,
  storageKey,
  source,
  sensorCount,
  preferencesOpen,
  catalog,
  importNotice,
  onCatalog,
  onCanonicalCatalog,
  onSource,
  onSensorCount,
}: WorkspaceProps) {
  const { isAuthenticated, userId } = useAuth();
  const [workspace, setWorkspace] = useState<SpatialWorkspace>(() => {
    const saved = loadWorkspace(storageKey);
    return automaticWorkspace(
      source === "ambibox" && catalog
        ? reconcileCatalogWorkspace(catalog, saved)
        : saved,
    );
  });
  const [base, setBase] = useState<Topology>(() =>
    source === "ambibox" && catalog
      ? catalog.topology
      : source === "demo"
        ? createDemoTopology(sensorCount)
        : HSL_INITIAL_TOPOLOGY,
  );
  const names = useCatalogNames({
    projection: source === "ambibox" ? catalog : undefined,
    isAuthenticated,
    accountKey: userId,
    onCanonicalNames: (updated) => {
      setBase(updated.topology);
      setWorkspace((current) => applyCatalogWorkspaceNames(current, updated));
      onCanonicalCatalog(updated);
    },
  });
  const nameDisabledReason =
    names.status === "loading"
      ? "Loading saved catalog names…"
      : names.status === "sign-in-required"
        ? "Sign in to rename saved catalog objects."
        : names.status === "read-only"
          ? "Administrator access is required to rename catalog objects."
          : names.status === "unavailable"
            ? "Database unavailable. Names are read-only."
            : "This object is not in the saved database catalog.";
  const [status, setStatus] = useState(
    source === "ambibox"
      ? "AmbiBox catalog · preview only"
      : source === "demo"
        ? "Simulated telemetry"
        : "Connecting to HSL…",
  );
  const [runtime] = useState(() =>
    source === "ambibox"
      ? new PassiveCatalogTelemetry()
      : source === "demo"
        ? new DemoTelemetry(base.nodes)
        : new HslTelemetry({ onTopology: setBase, onStatus: setStatus }),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const [fitRequest, setFitRequest] = useState(
    source === "ambibox"
      ? hasLayout(storageKey)
        ? 0
        : 1
      : sensorCount > 18
        ? 1
        : 0,
  );
  const requestFocus = useCallback((id: string) => {
    setFocusId(id);
    setFocusRequest((current) => current + 1);
  }, []);
  const [query, setQuery] = useState("");
  const [paused, setPaused] = useState(false);
  const [quality, setQuality] = useState<"balanced" | "economy">("balanced");
  const [view, setView] = useState<"isometric" | "top">(() =>
    Math.hypot(
      workspace.camera.position[0] - workspace.camera.target[0],
      workspace.camera.position[2] - workspace.camera.target[2],
    ) < 0.1
      ? "top"
      : "isometric",
  );
  const [saved, setSaved] = useState({ workspace, available: true });
  const [stats, setStats] = useState(emptyStats);
  const [now, setNow] = useState(() => Date.now());
  const [help, setHelp] = useState(false);
  const [settings, setSettings] = useState(preferencesOpen);
  const [viewName, setViewName] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [groupEditor, setGroupEditor] = useState<string | null>(null);
  const [notice, setNotice] = useState(importNotice);
  const inspectorRef = useRef<HTMLElement>(null);

  useEffect(() => {
    inspectorRef.current?.scrollTo({ top: 0 });
  }, [selectedId, settings, groupEditor]);

  useEffect(() => {
    runtime.start();
    return () => runtime.dispose();
  }, [runtime]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        setSaved({
          workspace,
          available: saveWorkspace(storageKey, workspace),
        }),
      250,
    );
    return () => window.clearTimeout(timer);
  }, [workspace, storageKey]);

  useEffect(() => {
    const persist = () => {
      saveWorkspace(storageKey, workspace);
    };
    window.addEventListener("pagehide", persist);
    return () => window.removeEventListener("pagehide", persist);
  }, [storageKey, workspace]);

  const pulseSources = useMemo(() => {
    const collapsed = new Set(
      workspace.groups
        .filter((group) => group.collapsed)
        .map((group) => group.id),
    );
    return Object.fromEntries(
      base.nodes
        .filter((node) =>
          collapsed.has(workspace.memberships[node.id] ?? node.groupId),
        )
        .map((node) => [
          node.id,
          `group:${workspace.memberships[node.id] ?? node.groupId}`,
        ]),
    );
  }, [base.nodes, workspace.groups, workspace.memberships]);
  const topology = useMemo(
    () => resolveTopology(base, workspace),
    [base, workspace],
  );
  const allNodes = useMemo(
    () =>
      resolveTopology(base, {
        ...workspace,
        groups: workspace.groups.map((group) => ({
          ...group,
          collapsed: false,
        })),
      }).nodes,
    [base, workspace],
  );
  const selected = allNodes.find((node) => node.id === selectedId);
  const selectedGroup = workspace.groups.find(
    (group) => group.id === selected?.groupId,
  );
  const editingGroup = workspace.groups.find(
    (group) => group.id === groupEditor,
  );
  const selectedNameTarget = selected ? catalogNameTarget(selected) : undefined;
  const groupNameTarget =
    editingGroup && catalog
      ? catalogGroupNameTarget(catalog, editingGroup.id)
      : undefined;
  const groupNameValue = groupNameTarget
    ? base.nodes.find((node) =>
        groupNameTarget.kind === "charger"
          ? node.kind === "charger" &&
            node.catalog?.chargerId === groupNameTarget.charger_id
          : node.kind === "broker" &&
            node.catalog?.sourceId === groupNameTarget.source_id,
      )?.label
    : undefined;
  const matches = useMemo(
    () =>
      allNodes.filter(
        (node) =>
          node.kind !== "group" &&
          [
            node.label,
            node.catalog?.sensorKey,
            node.catalog?.upstreamTopic,
            node.catalog?.category,
          ].some((field) =>
            field?.toLowerCase().includes(query.trim().toLowerCase()),
          ),
      ),
    [allNodes, query],
  );
  const displayNodes = (
    source === "ambibox" && !query.trim()
      ? matches.filter((node) => node.kind === "charger")
      : matches
  ).slice(0, 40);
  const messageRate = base.nodes
    .filter((node) => node.kind === "broker")
    .reduce((sum, node) => sum + (runtime.getSnapshot(node.id)?.rate ?? 0), 0);
  const groupMembers = editingGroup
    ? base.nodes.filter(
        (node) =>
          (workspace.memberships[node.id] ?? node.groupId) === editingGroup.id,
      )
    : [];
  const groupRate = groupMembers
    .filter((node) => node.kind === "sensor")
    .reduce((sum, node) => sum + (runtime.getSnapshot(node.id)?.rate ?? 0), 0);
  const isReceiving = !paused && messageRate > 0;
  const streamLabel =
    source === "ambibox"
      ? "Catalog only"
      : paused
        ? "Paused"
        : isReceiving
          ? "Receiving"
          : source === "hsl" && status.includes("fail")
            ? "Disconnected"
            : source === "hsl" && !status.startsWith("Live")
              ? "Connecting"
              : "Waiting";
  const snapshot = selected ? runtime.getSnapshot(selected.id) : undefined;

  const commit = useCallback(
    (next: SpatialWorkspace) => setWorkspace(automaticWorkspace(next)),
    [],
  );
  const selectNode = useCallback(
    (id: string | null) => {
      const collection = id?.startsWith("group:") ? id.slice(6) : null;
      const node = allNodes.find((item) => item.id === id);
      if (
        node &&
        workspace.groups.some(
          (group) => group.id === node.groupId && group.collapsed,
        )
      ) {
        commit({
          ...workspace,
          groups: workspace.groups.map((group) =>
            group.id === node.groupId ? { ...group, collapsed: false } : group,
          ),
        });
      }
      setSelectedId(collection ? null : id);
      setGroupEditor(collection);
      setSettings(false);
    },
    [allNodes, commit, workspace],
  );
  const inspectCatalogObject = useCallback(
    (id: string) => {
      selectNode(id);
      if (source === "ambibox")
        setWorkspace((current) => ({
          ...current,
          camera: {
            ...current.camera,
            zoom: Math.max(1.1, current.camera.zoom),
          },
        }));
      requestFocus(id);
    },
    [requestFocus, selectNode, source],
  );
  const cameraChanged = useCallback(
    (camera: CameraPose) => setWorkspace((current) => ({ ...current, camera })),
    [],
  );
  const fitScene = useCallback(
    () => setFitRequest((current) => current + 1),
    [],
  );

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLElement &&
        event.target.closest("input, textarea, select, [contenteditable]")
      )
        return;
      if (event.key === "Escape") {
        selectNode(null);
        setHelp(false);
        setSettings(false);
      }
      if (event.key.toLowerCase() === "f") {
        if (selectedId) requestFocus(selectedId);
        else fitScene();
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [fitScene, selectNode, selectedId, requestFocus]);

  const togglePause = () => {
    const next = !paused;
    runtime.setPaused(next);
    setPaused(next);
  };
  const savePerspective = () => {
    if (!viewName.trim()) return;
    commit({
      ...workspace,
      perspectives: [
        ...workspace.perspectives,
        {
          id: crypto.randomUUID(),
          name: viewName.trim().slice(0, 40),
          camera: workspace.camera,
          view,
        },
      ].slice(-12),
    });
    setViewName("");
    setNotice("Perspective saved on this browser.");
  };
  const exportLayout = () => {
    const blob = new Blob([JSON.stringify(workspace, null, 2)], {
      type: "application/json",
    });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "aberration-view.json";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(href), 1000);
    setNotice("View exported. Telemetry is not included.");
  };

  return (
    <main className="sp-lab">
      <header className="sp-header">
        <div className="sp-brand">
          <span className="sp-brand-mark">/</span>
          <span>
            aberration<span className="sp-brand-divider">/</span>
            <span className="sp-brand-view">
              {source === "ambibox" ? "AmbiBox" : "Spatial"}
            </span>
          </span>
          <span className="sp-draft-badge">Design lab</span>
        </div>
        <div className="sp-header-right">
          {onReturn && <button onClick={onReturn}>Saved system</button>}
          <span className="sp-save-state">
            <i />
            {saved.workspace !== workspace
              ? "Saving…"
              : saved.available
                ? "Saved on this browser"
                : "Browser storage unavailable"}
          </span>
          <a href="/">
            Dashboard <ArrowUpRightIcon />
          </a>
          <button aria-label="Help and controls" onClick={() => setHelp(!help)}>
            <CircleHelp size={18} />
          </button>
        </div>
      </header>
      <div
        className={`sp-body${source === "ambibox" && !selected && !settings && !editingGroup ? " sp-fleet-overview" : ""}`}
      >
        <SpatialSidebar
          workspace={workspace}
          nodes={base.nodes}
          query={query}
          groupEditor={groupEditor}
          selectedId={selectedId}
          displayNodes={displayNodes}
          matchCount={matches.length}
          paused={paused}
          status={status}
          source={source}
          onQueryChange={setQuery}
          onCreateCollection={() => {
            setSettings(true);
            setGroupEditor(null);
          }}
          onSelectGroup={(id) => {
            setGroupEditor(id);
            setSelectedId(null);
            setSettings(false);
          }}
          onSelectNode={
            source === "ambibox" ? inspectCatalogObject : selectNode
          }
          onChange={commit}
        />
        <section
          className="sp-stage"
          aria-label="Interactive spatial system overview"
        >
          <div className="sp-stage-heading">
            <div>
              <span className="sp-overline">System overview</span>
              <p>
                {base.nodes.filter((node) => node.kind === "broker").length}{" "}
                brokers <span>·</span>{" "}
                {source === "ambibox" && (
                  <>
                    {catalog?.summary.chargers} chargers <span>·</span>{" "}
                  </>
                )}
                {base.nodes.filter((node) => node.kind === "sensor").length}{" "}
                {source === "ambibox" ? "topics" : "streams"}
              </p>
            </div>
            <div className="sp-live-indicator">
              <i className={isReceiving ? "active" : ""} />
              {streamLabel}
              {source !== "ambibox" && (
                <span>{messageRate.toFixed(1)} msg/s</span>
              )}
            </div>
          </div>
          <SpatialCanvas
            nodes={topology.nodes}
            edges={topology.edges}
            groups={workspace.groups}
            selectedId={
              selectedId ?? (groupEditor ? `group:${groupEditor}` : null)
            }
            editMode={false}
            camera={workspace.camera}
            quality={quality}
            paused={paused}
            telemetry={runtime}
            pulseSources={pulseSources}
            onSelect={selectNode}
            onMove={ignoreMove}
            onCameraChange={cameraChanged}
            onStats={setStats}
            focusId={focusId}
            focusRequest={focusRequest}
            fitRequest={fitRequest}
            view={view}
          />
          <div className="sp-scene-caption">
            <span className="sp-caption-line" />
            {source === "ambibox"
              ? "Select a charger to explore its catalog. Expand to reveal broker connections."
              : "Select any object to follow its signal."}
          </div>
          <div className="sp-toolbar">
            <button
              className={view === "top" ? "is-active" : ""}
              aria-pressed={view === "top"}
              aria-label="Top view"
              onClick={() => setView(view === "top" ? "isometric" : "top")}
            >
              <Layers size={16} />
            </button>
            <button onClick={fitScene} aria-label="Fit scene">
              <Maximize2 size={16} />
            </button>
            {source !== "ambibox" && (
              <button
                onClick={togglePause}
                aria-label={paused ? "Resume telemetry" : "Pause telemetry"}
              >
                {paused ? <Play size={16} /> : <Pause size={16} />}
              </button>
            )}
            <span className="sp-toolbar-divider" />
            <button
              className={settings ? "is-active" : ""}
              aria-label="Workspace preferences"
              onClick={() => {
                setSettings(!settings);
                setGroupEditor(null);
                setSelectedId(null);
              }}
            >
              <Settings2 size={16} />
            </button>
          </div>
          <div className="sp-performance">
            <span>
              {stats.fps ? `${Math.round(stats.fps)} fps` : "Idle · on demand"}
            </span>
            <span>{stats.drawCalls} draw calls</span>
            <span>{stats.visibleNodes} objects</span>
            <span>{stats.particles} pulses</span>
            <select
              aria-label="Render quality"
              value={quality}
              onChange={(event) =>
                setQuality(event.target.value as "balanced" | "economy")
              }
            >
              <option value="balanced">Balanced</option>
              <option value="economy">Economy</option>
            </select>
          </div>
          <div className="sp-pulse-legend">
            {source === "ambibox" ? (
              "Exact catalog structure · awaiting a live connection"
            ) : (
              <>
                Arrival-driven pulses · visual cap{" "}
                {quality === "balanced" ? "80" : "30"}/s
              </>
            )}
          </div>
          {notice && (
            <button
              className="sp-notice"
              onClick={() => setNotice("")}
              aria-label="Dismiss notification"
            >
              {notice}
              <X size={12} />
            </button>
          )}
        </section>
        <aside
          ref={inspectorRef}
          className={`sp-inspector ${selected || settings || editingGroup ? "is-open" : ""}`}
          aria-label="Object inspector"
        >
          <div className="sp-inspector-heading">
            <span className="sp-overline">
              {settings
                ? "Workspace preferences"
                : editingGroup
                  ? "Collection settings"
                  : "Inspector"}
            </span>
            {(selected || settings || editingGroup) && (
              <button
                aria-label="Close inspector"
                onClick={() => {
                  selectNode(null);
                  setSettings(false);
                  setGroupEditor(null);
                }}
              >
                <X size={16} />
              </button>
            )}
          </div>
          {selected ? (
            <TelemetryInspector
              key={selected.id}
              node={selected}
              group={selectedGroup}
              groups={workspace.groups}
              snapshot={snapshot}
              now={now}
              isDemo={source === "demo"}
              isCatalogPreview={source === "ambibox"}
              related={base.nodes.filter((node) =>
                selected.catalog?.chargerId
                  ? node.catalog?.chargerId === selected.catalog.chargerId
                  : node.catalog?.sourceId === selected.catalog?.sourceId,
              )}
              onSelectRelated={inspectCatalogObject}
              onFocus={() => inspectCatalogObject(selected.id)}
              nameEditable={names.canRename(selectedNameTarget)}
              nameSaveError={names.error}
              nameDisabledReason={nameDisabledReason}
              onRename={
                selectedNameTarget
                  ? async (name) => {
                      if (!(await names.rename(selectedNameTarget, name)))
                        throw new Error("Name was not saved.");
                    }
                  : undefined
              }
              onGroup={(groupId) =>
                commit({
                  ...workspace,
                  memberships: {
                    ...workspace.memberships,
                    [selected.id]: groupId,
                  },
                })
              }
              onRate={(value) => {
                if (runtime instanceof DemoTelemetry) {
                  runtime.setRate(selected.id, value);
                  setBase((current) => ({
                    ...current,
                    nodes: current.nodes.map((node) =>
                      node.id === selected.id
                        ? { ...node, baseRate: value }
                        : node,
                    ),
                  }));
                }
              }}
            />
          ) : editingGroup ? (
            <CollectionInspector
              key={editingGroup.id}
              group={editingGroup}
              workspace={workspace}
              memberCount={groupMembers.length}
              rate={source === "ambibox" ? undefined : groupRate}
              previewOnly={source === "ambibox"}
              members={groupMembers}
              onSelectMember={inspectCatalogObject}
              onChange={commit}
              nameEditable={names.canRename(groupNameTarget)}
              nameSaveError={names.error}
              nameValue={groupNameValue}
              nameDisabledReason={nameDisabledReason}
              onRename={
                groupNameTarget
                  ? async (name) => {
                      if (!(await names.rename(groupNameTarget, name)))
                        throw new Error("Name was not saved.");
                    }
                  : undefined
              }
            />
          ) : settings ? (
            <WorkspacePreferences
              allowCatalogImport={false}
              workspace={workspace}
              catalog={catalog}
              onCatalog={onCatalog}
              onOpenSavedCatalog={
                isAuthenticated ? fetchSavedSpatialCatalog : undefined
              }
              namePersistenceStatus={
                names.status === "ready"
                  ? `Connected to database · catalog revision ${names.revision}. Names are shared catalog metadata.`
                  : nameDisabledReason
              }
              namePersistenceError={names.error}
              onRefreshNames={
                isAuthenticated
                  ? () => {
                      void names.refresh();
                    }
                  : undefined
              }
              source={source}
              sensorCount={sensorCount}
              viewName={viewName}
              newGroupName={newGroupName}
              onSource={onSource}
              onSensorCount={onSensorCount}
              onViewName={setViewName}
              onNewGroupName={setNewGroupName}
              onSavePerspective={savePerspective}
              onRestorePerspective={(perspective) => {
                setView(perspective.view ?? "isometric");
                setWorkspace((current) => ({
                  ...current,
                  camera: perspective.camera,
                }));
              }}
              onChange={commit}
              onCreateGroup={() => {
                const id = `custom-${crypto.randomUUID()}`;
                commit({
                  ...workspace,
                  groups: [
                    ...workspace.groups,
                    {
                      id,
                      name: newGroupName.trim(),
                      color: "#6288b5",
                      collapsed: false,
                      locked: false,
                    },
                  ],
                });
                setNewGroupName("");
                setGroupEditor(id);
                setSettings(false);
              }}
              onExport={exportLayout}
              onImport={(imported) => {
                const reconciled = automaticWorkspace(
                  source === "ambibox" && catalog
                    ? reconcileCatalogWorkspace(catalog, imported)
                    : imported,
                );
                if (!saveWorkspace(storageKey, reconciled)) return false;
                commit(reconciled);
                setView("isometric");
                return true;
              }}
              onResetCamera={() => {
                setWorkspace((current) => ({
                  ...current,
                  camera: DEFAULT_CAMERA,
                }));
                setView("isometric");
              }}
              onNotice={setNotice}
            />
          ) : (
            <div className="sp-inspector-empty">
              <div className="sp-empty-object">
                <Box size={30} />
              </div>
              <h2>
                {source === "ambibox"
                  ? "Explore your fleet."
                  : "Follow a signal."}
              </h2>
              <p>
                {source === "ambibox"
                  ? "Select a charger to open its exact topic definitions. Expand a collection to reveal its broker and streams."
                  : "Select a sensor, broker, or collection to see what is happening."}
              </p>
              <div className="sp-empty-tip">
                <Radio size={15} />
                <span>
                  {source === "ambibox"
                    ? `${catalog?.summary.streams} definitions. Live readings appear when connected.`
                    : "Every pulse starts with a message."}
                </span>
              </div>
              <button
                className="sp-wide-button"
                onClick={() => setSettings(true)}
              >
                <Settings2 size={15} />
                Customise workspace
              </button>
            </div>
          )}
        </aside>
      </div>
      <SpatialHelp open={help} onOpenChange={setHelp} />
    </main>
  );
}

function ArrowUpRightIcon() {
  return <span aria-hidden="true">↗</span>;
}
