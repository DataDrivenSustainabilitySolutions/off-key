import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  ArrowLeft,
  CircleHelp,
  Layers,
  Maximize2,
  Settings2,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { SpatialCanvas } from "./SpatialCanvas";
import { SpatialHelp } from "./SpatialHelp";
import { InlineName } from "./InlineName";
import { SystemLiveTelemetry } from "./systemLiveTelemetry";
import { SystemLiveControls } from "./SystemLiveControls";
import { resolveTopology } from "./model";
import { loadWorkspace, saveWorkspace } from "./workspace";
import { createEmptySystem, serializeSystemDocument } from "./systemDocument";
import {
  projectSystemDocument,
  reconcileSystemWorkspace,
} from "./systemProjection";
import { SystemSidebar, type SystemFilter } from "./SystemSidebar";
import { SystemStructureEditor } from "./SystemStructureEditor";
import { SystemObjectInspector } from "./SystemObjectInspector";
import { SystemWorkspaceSettings } from "./SystemWorkspaceSettings";
import { focusSystemTopology } from "./focusedSystemTopology";
import {
  colorSystemTopology,
  automaticSystemLayout,
  scopeSystemTopology,
} from "./systemSceneView";
import { useSystemDocument } from "./useSystemDocument";
import type { SystemDocument, SystemEntityKind } from "./systemTypes";
import type { CameraPose, RenderStats, SpatialWorkspace } from "./types";
import "./spatial.css";
import "./system.css";
type Editor = { kind: SystemEntityKind; id?: string; key: number };
type Props = { onPreview: (source: "demo" | "hsl") => void };
const emptyStats: RenderStats = {
  fps: 0,
  drawCalls: 0,
  visibleNodes: 0,
  particles: 0,
};
const emptyDocument = createEmptySystem();
const ignoreObjectMove = () => undefined;
const needsAutomaticFit = (workspace: SpatialWorkspace) =>
  workspace.layoutMode !== "automatic" ||
  Object.keys(workspace.positions).length > 0 ||
  Object.values(workspace.locks).some(Boolean) ||
  workspace.groups.some((group) => group.locked || group.collapsed);
const normalizeSystemView = (
  projection: ReturnType<typeof projectSystemDocument>,
  workspace: SpatialWorkspace,
) =>
  automaticSystemLayout(
    projection.topology,
    reconcileSystemWorkspace(projection, workspace),
  );

export function ConfiguredSystemWorkspace({ onPreview }: Props) {
  const { userId, isAuthenticated } = useAuth();
  const storageKey = `aberration:spatial:system:v1:${userId ?? "local"}`;
  const [workspace, setWorkspace] = useState(() => loadWorkspace(storageKey));
  const initialWorkspace = useRef(workspace);
  const [savedLayout, setSavedLayout] = useState(true);
  const [fitRequest, setFitRequest] = useState(0);
  const initialDocument = useRef(true);
  const [hadLayout] = useState(() => {
    try {
      return !!window.localStorage.getItem(storageKey);
    } catch {
      return false;
    }
  });
  const receiveDocument = useCallback(
    (document: SystemDocument) => {
      const next = projectSystemDocument(document);
      let previousLayout: SpatialWorkspace | undefined;
      const firstDocument = initialDocument.current;
      if (
        firstDocument &&
        !hadLayout &&
        next.topology.nodes.length &&
        next.topology.nodes.every((node) => node.id.startsWith("ambibox:"))
      ) {
        const previousKey = `aberration:spatial:v1:${userId ?? "local"}:ambibox:ambibox-${next.datasetKey}`;
        try {
          if (window.localStorage.getItem(previousKey))
            previousLayout = loadWorkspace(previousKey);
        } catch {
          /* Use the current view when browser storage is unavailable. */
        }
      }
      const previousWorkspace =
        previousLayout ?? (hadLayout ? initialWorkspace.current : undefined);
      setWorkspace((current) =>
        normalizeSystemView(next, previousLayout ?? current),
      );
      if (firstDocument) {
        initialDocument.current = false;
        if (!previousWorkspace || needsAutomaticFit(previousWorkspace))
          setFitRequest((current) => current + 1);
      }
    },
    [hadLayout, userId],
  );
  const system = useSystemDocument({
    isAuthenticated,
    accountKey: userId,
    onDocument: receiveDocument,
  });
  const document = system.document ?? emptyDocument;
  const projection = useMemo(() => projectSystemDocument(document), [document]);
  const [telemetry] = useState(() => new SystemLiveTelemetry());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [personalGroupId, setPersonalGroupId] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor>();
  const [settings, setSettings] = useState(false);
  const [settingsVersion, setSettingsVersion] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<SystemFilter>("overview");
  const [quality, setQuality] = useState<"balanced" | "economy">("balanced");
  const [view, setView] = useState<"isometric" | "top">("isometric");
  const [focusId, setFocusId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const [stats, setStats] = useState(emptyStats);
  const [notice, setNotice] = useState("");
  const [help, setHelp] = useState(false);
  const inspector = useRef<HTMLElement>(null);
  // Camera and saved-perspective updates must not rebuild the scene topology.
  const objectLayout = useMemo(
    () => ({
      ...projection.workspace,
      groups: workspace.groups,
      personalGroups: workspace.personalGroups,
    }),
    [projection.workspace, workspace.groups, workspace.personalGroups],
  );
  const effectiveTopology = useMemo(
    () =>
      resolveTopology(
        projection.topology,
        automaticSystemLayout(projection.topology, objectLayout),
      ),
    [projection.topology, objectLayout],
  );
  const allTopology = useMemo(
    () => colorSystemTopology(effectiveTopology, objectLayout, personalGroupId),
    [effectiveTopology, objectLayout, personalGroupId],
  );
  const allNodes = allTopology.nodes;
  const personalGroup = workspace.personalGroups?.find(
    (item) => item.id === personalGroupId,
  );
  const scopedTopology = useMemo(() => {
    const members = personalGroup
      ? new Set(personalGroup.memberIds)
      : groupId
        ? new Set(
            document.groups.find((item) => item.id === groupId)?.member_ids ??
              [],
          )
        : undefined;
    return scopeSystemTopology(allTopology, members);
  }, [allTopology, personalGroup, groupId, document.groups]);
  const focusedScene = useMemo(
    () => focusSystemTopology(scopedTopology, selectedId),
    [scopedTopology, selectedId],
  );
  const topology = focusedScene.topology;
  const selected = allNodes.find((node) => node.id === selectedId);
  const scopeCounts = useMemo(() => {
    const readings = scopedTopology.nodes.filter(
      (node) =>
        node.system?.kind === "stream" &&
        (!selected ||
          (selected.system?.kind === "device"
            ? node.system.deviceId === selected.id
            : selected.system?.kind === "connection"
              ? node.system.connectionId === selected.id
              : node.id === selected.id)),
    );
    return {
      readings: readings.length,
      topics: new Set(
        readings.map((node) =>
          JSON.stringify([node.system?.connectionId, node.system?.topic]),
        ),
      ).size,
    };
  }, [scopedTopology, selected]);
  const group = document.groups.find((entry) => entry.id === groupId);
  const hasInspector = !!(selected || group || editor || settings);
  const revision = system.snapshot?.revision ?? 0;
  const canStartLive = isAuthenticated && system.snapshot?.can_edit === true;
  useEffect(() => {
    telemetry.configure(
      document,
      revision,
      isAuthenticated ? String(userId ?? "signed-in") : "",
      canStartLive,
    );
  }, [telemetry, document, revision, isAuthenticated, userId, canStartLive]);
  useEffect(() => () => telemetry.stop(), [telemetry]);
  useEffect(() => {
    telemetry.setPriority(selectedId);
  }, [telemetry, selectedId]);
  useEffect(() => {
    const visibility = () => {
      if (window.document.hidden) telemetry.pause();
      else telemetry.resume();
    };
    const leave = () => telemetry.stop();
    window.document.addEventListener("visibilitychange", visibility);
    window.addEventListener("pagehide", leave);
    return () => {
      window.document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("pagehide", leave);
    };
  }, [telemetry]);
  const disabledReason =
    system.status === "sign-in-required"
      ? "Sign in to edit the saved system."
      : system.status === "read-only"
        ? "An administrator can edit this system."
        : "The saved system is currently unavailable.";
  useEffect(() => {
    const view = automaticSystemLayout(projection.topology, workspace);
    const timer = window.setTimeout(
      () => setSavedLayout(saveWorkspace(storageKey, view)),
      250,
    );
    const persist = () => saveWorkspace(storageKey, view);
    window.addEventListener("pagehide", persist);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("pagehide", persist);
    };
  }, [workspace, storageKey, projection.topology]);
  useEffect(() => {
    inspector.current?.scrollTo({ top: 0 });
  }, [selectedId, groupId, editor?.key, settings]);
  const updateView = useCallback(
    (next: SpatialWorkspace) =>
      setWorkspace(automaticSystemLayout(projection.topology, next)),
    [projection.topology],
  );
  const clearInspector = () => {
    setSelectedId(null);
    setGroupId(null);
    setEditor(undefined);
    setSettings(false);
  };
  const selectObject = (id: string | null, focus = false) => {
    if (id && !scopedTopology.nodes.some((node) => node.id === id)) {
      setPersonalGroupId(null);
    }
    setSelectedId(id);
    setGroupId(null);
    if (id && focus) {
      setFocusId(id);
      setFocusRequest((current) => current + 1);
    }
    setEditor(undefined);
    setSettings(false);
  };
  const openEditor = (kind: SystemEntityKind, id?: string) => {
    setEditor({ kind, id, key: Date.now() });
    setSettings(false);
  };
  const exportConfiguration = async (includeLayout: boolean) => {
    const canonical = await system.refresh();
    if (!canonical) {
      setNotice(
        "The saved configuration could not be read. No file was exported.",
      );
      return;
    }
    const contents = includeLayout
      ? JSON.stringify(
          {
            format: "aberration-workspace",
            schema_version: 1,
            system: canonical,
            layout: normalizeSystemView(
              projectSystemDocument(canonical),
              workspace,
            ),
          },
          null,
          2,
        )
      : serializeSystemDocument(canonical);
    const url = URL.createObjectURL(
      new Blob([contents], { type: "application/json" }),
    );
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = includeLayout
      ? "aberration-workspace.json"
      : "aberration-system.json";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice(
      includeLayout
        ? "Workspace exported with its saved configuration and view."
        : "Latest saved configuration exported.",
    );
  };
  const importConfiguration = async (
    next: SystemDocument,
    layout?: SpatialWorkspace,
    expectedRevision = revision,
  ) => {
    if (!(await system.save(next, expectedRevision))) return false;
    if (layout)
      setWorkspace(normalizeSystemView(projectSystemDocument(next), layout));
    setSelectedId(null);
    setGroupId(null);
    setPersonalGroupId(null);
    setEditor(undefined);
    if (!layout || needsAutomaticFit(layout))
      setFitRequest((current) => current + 1);
    setNotice(
      "Configuration imported and saved. No live connection was started.",
    );
    return true;
  };
  const rename = async (kind: SystemEntityKind, id: string, label: string) => {
    if (!(await system.rename(kind, id, label)))
      throw new Error("Name was not saved.");
  };
  const statsLine = `${stats.drawCalls} draw calls · ${stats.visibleNodes} objects`;
  return (
    <main className="sp-lab sp-system">
      <header className="sp-header">
        <div className="sp-brand">
          <span className="sp-logo-mark">/</span>
          <strong>aberration</strong>
          <span className="sp-brand-divider">/</span>
          <span>Spatial</span>
          <span className="sp-draft-badge">Design lab</span>
        </div>
        <div className="sp-header-right">
          <span className="sp-save-state">
            <i />
            {system.saving
              ? "Saving configuration…"
              : system.snapshot?.storage_origin === "saved"
                ? "Saved system"
                : "System definition"}
          </span>
          <Link to="/">Dashboard ↗</Link>
          <button aria-label="Help and controls" onClick={() => setHelp(true)}>
            <CircleHelp size={17} />
          </button>
        </div>
      </header>
      <div className={`sp-body${hasInspector ? "" : " sp-fleet-overview"}`}>
        <SystemSidebar
          document={document}
          workspace={workspace}
          nodes={allNodes}
          query={query}
          filter={filter}
          selectedId={selectedId}
          selectedGroup={groupId}
          canEdit={system.canEdit && !system.saving}
          saved={system.snapshot?.storage_origin === "saved"}
          onQuery={setQuery}
          onFilter={setFilter}
          onSelect={(id) => selectObject(id, true)}
          onGroup={(id) => {
            setPersonalGroupId(null);
            setGroupId(id);
            setSelectedId(null);
            setEditor(undefined);
            setSettings(false);
          }}
          onCreate={(kind) => openEditor(kind)}
          onLayout={updateView}
          personalGroupId={personalGroupId}
          onPersonalGroup={(id) => {
            clearInspector();
            setPersonalGroupId(id);
            setFitRequest((current) => current + 1);
          }}
        />
        <section
          className="sp-stage"
          aria-label="Interactive spatial system overview"
        >
          <div className="sp-stage-heading">
            <div>
              <span className="sp-overline">{document.label}</span>
              <p>
                {document.connections.length} brokers <span>·</span>{" "}
                {document.devices.length} entities <span>·</span>{" "}
                {document.streams.length} readings
              </p>
            </div>
            <SystemLiveControls
              telemetry={telemetry}
              canStart={canStartLive}
              canView={isAuthenticated}
              disabled={
                !system.snapshot || system.saving || !document.streams.length
              }
            />
          </div>
          <div className="sp-system-scene-context">
            <button
              aria-label="Return to system overview"
              disabled={!selected && !group && !personalGroup}
              onClick={() => {
                clearInspector();
                setPersonalGroupId(null);
                setFocusId(null);
                setFitRequest((current) => current + 1);
              }}
            >
              {(selected || group || personalGroup) && <ArrowLeft size={13} />}
              Overview
            </button>
            {(personalGroup || group || selected) && <span>/</span>}
            <span>
              {personalGroup?.name ?? group?.label ?? selected?.label}
            </span>
            <small>
              {scopeCounts.readings} readings · {scopeCounts.topics} MQTT topics
            </small>
          </div>
          <SpatialCanvas
            nodes={topology.nodes}
            edges={topology.edges}
            groups={focusedScene.groups}
            selectedId={selectedId ?? (groupId ? `group:${groupId}` : null)}
            editMode={false}
            camera={workspace.camera}
            quality={quality}
            paused={false}
            telemetry={telemetry}
            pulseSources={focusedScene.pulseSources}
            pulseRoutes={focusedScene.pulseRoutes}
            onSelect={(id) => selectObject(id)}
            onMove={ignoreObjectMove}
            onCameraChange={(camera: CameraPose) =>
              setWorkspace((current) => ({ ...current, camera }))
            }
            onStats={setStats}
            focusId={focusId}
            focusRequest={focusRequest}
            fitRequest={fitRequest}
            view={view}
          />
          {!projection.topology.nodes.length && (
            <div className="sp-system-empty">
              <Box size={28} />
              <h2>
                {system.status === "loading"
                  ? "Opening your saved system…"
                  : "Every system starts with a connection."}
              </h2>
              <p>
                {system.status === "sign-in-required"
                  ? "Sign in to build and save your own system."
                  : system.status === "unavailable"
                    ? system.error
                    : "Add a broker, then define the streams you want to follow."}
              </p>
              {system.canEdit && (
                <button
                  className="sp-system-primary"
                  onClick={() => openEditor("connection")}
                >
                  Add connection
                </button>
              )}
              {system.status === "sign-in-required" && (
                <Link to="/login">Sign in ↗</Link>
              )}
              <button onClick={() => onPreview("demo")}>
                Explore simulated telemetry
              </button>
              <button onClick={() => onPreview("hsl")}>
                Explore public MQTT
              </button>
            </div>
          )}
          <div className="sp-scene-caption">
            <span className="sp-caption-line" />
            Select an entity to browse topics. Pick a reading for its chart.
          </div>
          <div className="sp-toolbar">
            <button
              aria-label="Top view"
              aria-pressed={view === "top"}
              onClick={() =>
                setView((current) => (current === "top" ? "isometric" : "top"))
              }
            >
              <Layers size={15} />
            </button>
            <button
              aria-label="Fit scene"
              onClick={() => setFitRequest((current) => current + 1)}
            >
              <Maximize2 size={15} />
            </button>
            <button
              aria-label="Workspace preferences"
              aria-pressed={settings}
              onClick={() => {
                clearInspector();
                setSettings(true);
                setSettingsVersion((current) => current + 1);
              }}
            >
              <Settings2 size={15} />
            </button>
          </div>
          <div className="sp-performance">
            <span>
              {stats.fps ? `${stats.fps} fps · on demand` : "Idle · on demand"}
            </span>
            <span>{statsLine}</span>
            <span>{stats.particles} pulses</span>
            <select
              aria-label="Render quality"
              value={quality}
              onChange={(event) =>
                setQuality(event.target.value as typeof quality)
              }
            >
              <option value="balanced">Balanced</option>
              <option value="economy">Economy</option>
            </select>
          </div>
          {!!notice && (
            <button
              className="sp-notice"
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              {notice}
              <X size={12} />
            </button>
          )}
          {!savedLayout && (
            <p className="sp-layout-save-error" role="alert">
              This browser could not save your view or personal groups. Export
              the workspace to keep a copy.
            </p>
          )}
        </section>
        <aside
          className={`sp-inspector${hasInspector ? " is-open" : ""}`}
          aria-label="Object inspector"
          ref={inspector}
        >
          <div className="sp-inspector-heading">
            <span className="sp-overline">
              {editor
                ? "Structure editor"
                : settings
                  ? "Workspace preferences"
                  : group
                    ? "Group"
                    : "Inspector"}
            </span>
            {hasInspector && (
              <button
                aria-label="Close inspector"
                disabled={system.saving}
                onClick={clearInspector}
              >
                <X size={16} />
              </button>
            )}
          </div>
          {editor ? (
            <SystemStructureEditor
              key={editor.key}
              document={document}
              kind={editor.kind}
              entityId={editor.id}
              revision={revision}
              canEdit={system.canEdit}
              saving={system.saving}
              saveError={system.error}
              onSave={system.save}
              onDone={() => {
                setEditor(undefined);
                setNotice("Ready to inspect your saved definition.");
              }}
            />
          ) : settings ? (
            <SystemWorkspaceSettings
              key={settingsVersion}
              document={document}
              revision={revision}
              workspace={workspace}
              view={view}
              onView={setView}
              canEdit={system.canEdit}
              saving={system.saving}
              saveError={system.error}
              onSave={system.save}
              onLayout={updateView}
              onCreate={openEditor}
              onExport={exportConfiguration}
              onImport={importConfiguration}
              onRefresh={() => {
                void system
                  .refresh()
                  .then(() => setSettingsVersion((current) => current + 1));
              }}
              onNotice={setNotice}
              onPreview={onPreview}
            />
          ) : selected ? (
            <SystemObjectInspector
              key={selected.id}
              node={selected}
              document={document}
              telemetry={telemetry}
              workspace={workspace}
              onLayout={updateView}
              color={
                selected.color ??
                workspace.groups.find((item) => item.id === selected.groupId)
                  ?.color
              }
              canEdit={system.canEdit}
              disabledReason={disabledReason}
              saveError={system.error}
              onRename={(label) =>
                rename(selected.system!.kind, selected.id, label)
              }
              onEdit={openEditor}
              onSelect={(id) => selectObject(id, true)}
              onFocus={() => {
                setFocusId(selected.id);
                setFocusRequest((current) => current + 1);
              }}
            />
          ) : group ? (
            <div className="sp-inspector-content">
              <span className="sp-overline">Group</span>
              <h2>
                <InlineName
                  value={group.label}
                  onSave={(label) => rename("group", group.id, label)}
                  editable={system.canEdit}
                  disabledReason={disabledReason}
                  saveError={system.error}
                  ariaLabel="Rename group"
                />
              </h2>
              <p className="sp-system-intro">
                {group.member_ids.length} catalog members. Personal selections
                and colors are in My groups.
              </p>
              <button
                className="sp-wide-button"
                disabled={!system.canEdit}
                onClick={() => openEditor("group", group.id)}
              >
                Edit group and members
              </button>
              <div className="sp-catalog-topics">
                {group.member_ids.slice(0, 40).map((id) => (
                  <button key={id} onClick={() => selectObject(id, true)}>
                    {allNodes.find((node) => node.id === id)?.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </aside>
      </div>
      <SpatialHelp open={help} onOpenChange={setHelp} configuredSystem />
    </main>
  );
}
