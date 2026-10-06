import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  CircleHelp,
  Eye,
  Grid2X2,
  Layers,
  Maximize2,
  Move,
  Pause,
  Play,
  Radio,
  Settings2,
  Undo2,
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
  arrangeTopology,
  createDemoTopology,
  DEFAULT_CAMERA,
  moveGroup,
  moveNodes,
  resolveTopology,
} from "@/features/spatial/model";
import { loadWorkspace, saveWorkspace } from "@/features/spatial/workspace";
import { DemoTelemetry } from "@/features/spatial/telemetry";
import {
  HslTelemetry,
  HSL_INITIAL_TOPOLOGY,
} from "@/features/spatial/live-source";
import type {
  CameraPose,
  Point,
  RenderStats,
  SpatialWorkspace,
  Topology,
} from "@/features/spatial/types";
import "@/features/spatial/spatial.css";

type SourceMode = "demo" | "hsl";
const emptyStats: RenderStats = {
  fps: 0,
  drawCalls: 0,
  visibleNodes: 0,
  particles: 0,
};

export default function SpatialLab() {
  const { userId } = useAuth();
  const [source, setSource] = useState<SourceMode>("demo");
  const [sensorCount, setSensorCount] = useState(18);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  return (
    <SpatialWorkspaceView
      key={`${userId ?? "local"}:${source}:${sensorCount}`}
      storageKey={`aberration:spatial:v1:${userId ?? "local"}:${source}${source === "demo" && sensorCount !== 18 ? `:${sensorCount}` : ""}`}
      source={source}
      sensorCount={sensorCount}
      preferencesOpen={preferencesOpen}
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
  storageKey: string;
  source: SourceMode;
  sensorCount: number;
  preferencesOpen: boolean;
  onSource: (source: SourceMode) => void;
  onSensorCount: (count: number) => void;
};

function SpatialWorkspaceView({
  storageKey,
  source,
  sensorCount,
  preferencesOpen,
  onSource,
  onSensorCount,
}: WorkspaceProps) {
  const [workspace, setWorkspace] = useState<SpatialWorkspace>(() =>
    loadWorkspace(storageKey),
  );
  const [base, setBase] = useState<Topology>(() =>
    source === "demo" ? createDemoTopology(sensorCount) : HSL_INITIAL_TOPOLOGY,
  );
  const [status, setStatus] = useState(
    source === "demo" ? "Simulated telemetry" : "Connecting to HSL…",
  );
  const [runtime] = useState(() =>
    source === "demo"
      ? new DemoTelemetry(base.nodes)
      : new HslTelemetry({ onTopology: setBase, onStatus: setStatus }),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const [fitRequest, setFitRequest] = useState(sensorCount > 18 ? 1 : 0);
  const requestFocus = useCallback((id: string) => {
    setFocusId(id);
    setFocusRequest((current) => current + 1);
  }, []);
  const [query, setQuery] = useState("");
  const [editMode, setEditMode] = useState(false);
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
  const [canUndo, setCanUndo] = useState(false);
  const [help, setHelp] = useState(false);
  const [settings, setSettings] = useState(preferencesOpen);
  const [viewName, setViewName] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [groupEditor, setGroupEditor] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const undo = useRef<SpatialWorkspace[]>([]);
  const redo = useRef<SpatialWorkspace[]>([]);

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
  const selected = topology.nodes.find((node) => node.id === selectedId);
  const selectedGroup = workspace.groups.find(
    (group) => group.id === selected?.groupId,
  );
  const editingGroup = workspace.groups.find(
    (group) => group.id === groupEditor,
  );
  const matches = useMemo(
    () =>
      topology.nodes.filter(
        (node) =>
          node.kind !== "group" &&
          node.label.toLowerCase().includes(query.toLowerCase()),
      ),
    [topology.nodes, query],
  );
  const displayNodes = matches.slice(0, 40);
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
  const streamLabel = paused
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
    (next: SpatialWorkspace) => {
      undo.current = [...undo.current.slice(-39), workspace];
      redo.current = [];
      setWorkspace(next);
      setCanUndo(true);
    },
    [workspace],
  );
  const undoChange = useCallback(() => {
    const previous = undo.current.pop();
    if (previous) {
      redo.current.push(workspace);
      setWorkspace(previous);
      setCanUndo(undo.current.length > 0);
    }
  }, [workspace]);
  const redoChange = useCallback(() => {
    const next = redo.current.pop();
    if (next) {
      undo.current.push(workspace);
      setWorkspace(next);
      setCanUndo(true);
    }
  }, [workspace]);
  const selectNode = useCallback((id: string | null) => {
    const collection = id?.startsWith("group:") ? id.slice(6) : null;
    setSelectedId(collection ? null : id);
    setGroupEditor(collection);
    setSettings(false);
  }, []);
  const move = useCallback(
    (changes: Record<string, Point>) => commit(moveNodes(workspace, changes)),
    [commit, workspace],
  );
  const translateGroup = useCallback(
    (groupId: string, delta: Point) =>
      commit(moveGroup(base, workspace, groupId, delta)),
    [base, commit, workspace],
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
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redoChange();
        else undoChange();
        return;
      }
      if (event.key === "Escape") {
        selectNode(null);
        setHelp(false);
        setSettings(false);
      }
      if (event.key.toLowerCase() === "f") {
        if (selectedId) requestFocus(selectedId);
        else fitScene();
      }
      if (
        !editMode ||
        !selected ||
        selected.locked ||
        selectedGroup?.locked ||
        selected.kind === "group"
      )
        return;
      const step = event.shiftKey ? 5 : 0.5;
      const delta: Record<string, Point> = {
        ArrowLeft: { x: -step, z: 0 },
        ArrowRight: { x: step, z: 0 },
        ArrowUp: { x: 0, z: -step },
        ArrowDown: { x: 0, z: step },
      };
      const offset = delta[event.key];
      if (offset) {
        event.preventDefault();
        move({
          [selected.id]: {
            x: selected.position.x + offset.x,
            z: selected.position.z + offset.z,
          },
        });
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [
    editMode,
    fitScene,
    move,
    redoChange,
    selectNode,
    selected,
    selectedGroup?.locked,
    selectedId,
    undoChange,
    requestFocus,
  ]);

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
    anchor.download = "aberration-layout.json";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(href), 1000);
    setNotice("Layout exported. Telemetry is not included.");
  };

  return (
    <main className="sp-lab">
      <header className="sp-header">
        <div className="sp-brand">
          <span className="sp-brand-mark">/</span>
          <span>
            aberration<span className="sp-brand-divider">/</span>
            <span className="sp-brand-view">Spatial</span>
          </span>
          <span className="sp-draft-badge">Design lab</span>
        </div>
        <div className="sp-header-right">
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
      <div className="sp-body">
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
          onSelectNode={selectNode}
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
                {base.nodes.filter((node) => node.kind === "sensor").length}{" "}
                streams
              </p>
            </div>
            <div className="sp-live-indicator">
              <i className={isReceiving ? "active" : ""} />
              {streamLabel}
              <span>{messageRate.toFixed(1)} msg/s</span>
            </div>
          </div>
          <SpatialCanvas
            nodes={topology.nodes}
            edges={topology.edges}
            groups={workspace.groups}
            selectedId={selectedId}
            editMode={editMode}
            camera={workspace.camera}
            quality={quality}
            paused={paused}
            telemetry={runtime}
            pulseSources={pulseSources}
            onSelect={selectNode}
            onMove={move}
            onGroupMove={translateGroup}
            onCameraChange={cameraChanged}
            onStats={setStats}
            focusId={focusId}
            focusRequest={focusRequest}
            fitRequest={fitRequest}
            view={view}
          />
          <div className="sp-scene-caption">
            <span className="sp-caption-line" />
            {editMode
              ? "Drag objects or collection tiles. Pinned objects stay put."
              : "Select any object to follow its signal."}
          </div>
          <div className="sp-toolbar">
            <div className="sp-toolbar-segment">
              <button
                className={!editMode ? "is-active" : ""}
                aria-label="Inspect"
                aria-pressed={!editMode}
                onClick={() => setEditMode(false)}
              >
                <Eye size={15} />
                <span>Inspect</span>
              </button>
              <button
                className={editMode ? "is-active" : ""}
                aria-label="Arrange"
                aria-pressed={editMode}
                onClick={() => setEditMode(true)}
              >
                <Move size={15} />
                <span>Arrange</span>
              </button>
            </div>
            <span className="sp-toolbar-divider" />
            <button
              onClick={() => {
                commit(arrangeTopology(base, workspace));
                setNotice(
                  "Unpinned objects arranged. Pinned positions preserved.",
                );
              }}
              title="Arrange unpinned objects"
            >
              <Grid2X2 size={16} />
            </button>
            <button
              onClick={undoChange}
              disabled={!canUndo}
              aria-label="Undo layout change"
            >
              <Undo2 size={16} />
            </button>
            <span className="sp-toolbar-divider" />
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
            <button
              onClick={togglePause}
              aria-label={paused ? "Resume telemetry" : "Pause telemetry"}
            >
              {paused ? <Play size={16} /> : <Pause size={16} />}
            </button>
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
            <span>{Math.round(stats.fps)} fps</span>
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
            Arrival-driven pulses · visual cap{" "}
            {quality === "balanced" ? "80" : "30"}/s
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
              editMode={editMode}
              isDemo={source === "demo"}
              onFocus={() => requestFocus(selected.id)}
              onLock={() =>
                commit({
                  ...workspace,
                  locks: {
                    ...workspace.locks,
                    [selected.id]: !selected.locked,
                  },
                })
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
              onPosition={(axis, value) =>
                move({ [selected.id]: { ...selected.position, [axis]: value } })
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
              group={editingGroup}
              workspace={workspace}
              memberCount={groupMembers.length}
              rate={groupRate}
              onChange={commit}
            />
          ) : settings ? (
            <WorkspacePreferences
              workspace={workspace}
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
                if (!saveWorkspace(storageKey, imported)) return false;
                commit(imported);
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
              <h2>Follow a signal.</h2>
              <p>
                Select a sensor, broker, or collection to see what is happening.
              </p>
              <div className="sp-empty-tip">
                <Radio size={15} />
                <span>Every pulse starts with a message.</span>
              </div>
              <div className="sp-empty-tip">
                <Move size={15} />
                <span>Arrange your space. Keep your place.</span>
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
