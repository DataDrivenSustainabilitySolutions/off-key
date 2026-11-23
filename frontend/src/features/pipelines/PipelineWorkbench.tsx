import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ComponentProps, type CSSProperties,
  type KeyboardEvent, type PointerEvent, type ReactNode, type RefObject } from "react";
import * as Popover from "@radix-ui/react-popover";
import toast from "react-hot-toast";
import { CircleCheck, CircleDashed, Plus, TriangleAlert, X } from "lucide-react";
import type { PipelineCatalog, PipelineComponent } from "./contracts";
import { blockChain, blockChoices, placeBlock, useBlocks } from "./blocks";
import { detectorMenu, fillDetectorSlot, suggestedDetector } from "./detectorSlot";
import { useForecastModels, usesForecastService, withForecastService } from "./forecastModels";
import type { GraphDocument } from "./model";
import PipelineCanvas from "./PipelineCanvas";
import { PipelineContextMenu } from "./PipelineContextMenu";
import { PipelineFeatures } from "./PipelineFeatures";
import { PipelineInspector } from "./PipelineInspector";
import { PipelineSaveBlock } from "./PipelineSaveBlock";
import { PipelineToolbox } from "./PipelineToolbox";
import { openSummary, showIssues } from "./issues";
import { plural } from "./scope";
import { startupSentence, startupSummary, type Startup } from "./startup";
import type { CoveredEdges } from "./viewport";
import { useUndoShortcuts } from "./useGraphEditor";
import { usePlaceToasts } from "@/hooks/use-toast-position";

export type InspectorPanel = "brief" | "service" | "component" | "test" | null;
type Props = Omit<ComponentProps<typeof PipelineCanvas>,
  "components" | "issues" | "features" | "featuresStale" | "insets" | "selection" | "onSelectionChange" | "onSelect"
  | "blocks" | "onSaveBlock"> & {
  /** Put a step in focus, or none. A quiet change leaves the panels as they are. */
  onSelect: (id?: string, quiet?: boolean) => void;
  catalog: PipelineCatalog;
  /** Takes steps the Add step menu placed, such as a block's, so the editor records and shows them. */
  onPlace?: (placed: { document: GraphDocument; id: string }) => void;
  validation?: ComponentProps<typeof PipelineInspector>["validation"];
  settings?: ReactNode;
  /** What the design answers to, such as the proposal it came as: a panel of its own, named by its button. */
  brief?: { label: string; content: ReactNode };
  /** A panel that tries the design before it monitors anything, where the screen provides one. */
  test?: ReactNode;
  /** What the button that opens that panel shows, such as how far a test has come. */
  testLabel?: ReactNode;
  /** Shown with a step's settings, such as the values the step had in the last test. */
  stepValues?: (node: string) => ReactNode;
  actions?: ReactNode;
  inspectorPanel?: InspectorPanel;
  onInspectorPanelChange?: (panel: InspectorPanel) => void;
  /** Enables Ctrl/Cmd+Z and Shift+Ctrl/Cmd+Z for graph history. */
  onUndo?: () => void;
  onRedo?: () => void;
  /** Increment to open the issue list, e.g. after an explicit validation. */
  issuesRequest?: number;
  /** The Input step's content: the readings the service monitors. */
  input?: ReactNode;
  /** When the first alarm can come; the status chip shows it while the graph is valid. */
  startup?: Startup;
  /** Why the latest automatic check failed; the status chip offers to check again. */
  validationError?: string;
  onRetryValidation?: () => void;
  /** Fills its container: a header bar, the canvas below it and settings docked at its right edge. */
  stage?: boolean;
  /** Sits above the toolbar on a stage, such as the service name and its actions. */
  header?: ReactNode;
};

/** A phone holds a step's settings in a sheet, one part at a time; anything wider, in a drawer under the canvas. */
const PHONE = "(max-width: 680px)";
const onPhone = () => typeof window !== "undefined" && window.matchMedia(PHONE).matches;
const watchPhone = (listener: () => void) => {
  const media = window.matchMedia(PHONE);
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
};
/** How tall the drawer opens, and how far it can be pulled, in pixels. */
const DRAWER = { initial: 340, min: 200, max: 720, step: 24 } as const;

/** The step settings' height under the canvas, which the grip at their top changes by pointer or keyboard. */
function useDrawerHeight() {
  const [height, setHeight] = useState<number>(DRAWER.initial);
  const pull = useRef<{ y: number; height: number }>(undefined);
  const set = (next: number) => setHeight(Math.round(Math.min(DRAWER.max, Math.max(DRAWER.min, next))));
  const grip = {
    role: "separator", "aria-orientation": "horizontal", "aria-label": "Resize step settings", tabIndex: 0,
    "aria-valuemin": DRAWER.min, "aria-valuemax": DRAWER.max, "aria-valuenow": height,
    onPointerDown: (event: PointerEvent<HTMLDivElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      pull.current = { y: event.clientY, height: event.currentTarget.parentElement?.offsetHeight || height };
    },
    onPointerMove: (event: PointerEvent<HTMLDivElement>) => {
      if (pull.current) set(pull.current.height + pull.current.y - event.clientY);
    },
    onPointerUp: () => { pull.current = undefined; },
    onPointerCancel: () => { pull.current = undefined; },
    onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => {
      const next = { ArrowUp: height + DRAWER.step, ArrowDown: height - DRAWER.step, Home: DRAWER.min, End: DRAWER.max }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      set(next);
    },
  } as const;
  return { height, grip };
}

/** How far a stage's header and settings reach over its canvas, in pixels. */
function useCoveredEdges(stage: boolean, canvas: RefObject<HTMLElement | null>, top: RefObject<HTMLElement | null>,
  panel: RefObject<HTMLElement | null>, open: boolean) {
  const [covered, setCovered] = useState<CoveredEdges>();
  useLayoutEffect(() => {
    if (!stage) return;
    const measure = () => {
      const area = canvas.current?.getBoundingClientRect();
      const header = top.current?.getBoundingClientRect();
      // On a phone a brief is read in place of the canvas: a canvas that is not shown keeps clear of nothing.
      const shown = !!canvas.current && getComputedStyle(canvas.current).visibility !== "hidden";
      const settings = open && shown ? panel.current?.getBoundingClientRect() : undefined;
      if (!area || !header) return;
      // Beside the canvas the settings cover its right edge; as a bottom sheet, its bottom.
      const side = !!settings?.width && settings.left > area.left + 1;
      const next = {
        top: Math.max(0, Math.round(header.bottom - area.top)),
        right: side ? Math.max(0, Math.round(area.right - settings.left)) : 0,
        bottom: settings?.height && !side ? Math.max(0, Math.round(area.bottom - settings.top)) : 0,
      };
      setCovered((previous) => previous?.top === next.top && previous.right === next.right
        && previous.bottom === next.bottom ? previous : next);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    for (const element of [canvas.current, top.current, panel.current]) if (element) observer.observe(element);
    return () => observer.disconnect();
  }, [stage, canvas, top, panel, open]);
  return covered;
}

/** One canvas-first workspace for creation, saved designs and running graphs. */
export function PipelineWorkbench({
  catalog: offered, validation, settings, brief, test, testLabel, stepValues, actions, inspectorPanel, onInspectorPanelChange,
  onUndo, onRedo, issuesRequest = 0, input, startup, validationError, onRetryValidation, stage = false, header, onPlace, ...props
}: Props) {
  // A step whose model lives in the forecast service is offered only where the deployment
  // has one; a design that is only shown asks when it holds such a step.
  const forecast = useForecastModels(props.readOnly
    ? props.document.definition.nodes.some((node) => usesForecastService(node.component))
    : offered.components.some((component) => usesForecastService(component.id)));
  const catalog = useMemo(
    () => ({ ...offered, components: withForecastService(offered.components, forecast.catalog) }),
    [offered, forecast.catalog],
  );
  // Saved blocks are offered wherever a step can be added, and a card's menu saves one more.
  const library = useBlocks(!props.readOnly);
  // The step whose chain is being saved as a block, asked for from a card's menu or a step's settings.
  const [savingFrom, setSavingFrom] = useState<string>();
  const saveBlock = props.readOnly ? undefined : setSavingFrom;
  useUndoShortcuts(!props.readOnly && !!onUndo && !!onRedo, () => onUndo?.(), () => onRedo?.());
  const [issuesOpen, setIssuesOpen] = useState(false);
  // Keep the last result on screen while an edit is re-checked, instead of flickering away.
  const [lastValidation, setLastValidation] = useState(validation);
  if (validation && validation !== lastValidation) setLastValidation(validation);
  const failed = !validation && !!validationError;
  const checking = !validation && !failed && !!lastValidation;
  const latest = validation ?? lastValidation;
  const status = failed ? undefined : latest;
  const estimate = startup && startupSummary(startup);
  // Errors block applying the design and warnings do not. Steps still to choose or
  // connect block it too, and read as the work that is left rather than as faults.
  const shown = useMemo(() => showIssues(props.document, catalog.components, status?.issues),
    [props.document, catalog.components, status]);
  const errors = shown.filter((issue) => issue.tone === "error").length;
  const open = shown.filter((issue) => issue.tone === "open");
  const warnings = shown.filter((issue) => issue.tone === "warning").length;
  const issueCount = status && `${errors}${status.issues_truncated ? "+" : ""}`;
  const warningCount = warnings ? plural(warnings, "warning") : "";
  const openText = open.length ? openSummary(open) : "";
  const statusLabel = failed ? "Design not checked" : errors
    ? `${issueCount} design ${errors === 1 ? "issue" : "issues"}`
    : openText ? `Design is not complete: ${openText.charAt(0).toLowerCase()}${openText.slice(1)}`
      : `Design is complete${warningCount ? `, ${warningCount}` : ""}${
        estimate ? `, first alarm after ${estimate.replace("≈", "about").replace("≥", "at least")}` : ""}`;
  const [lastIssuesRequest, setLastIssuesRequest] = useState(issuesRequest);
  if (issuesRequest !== lastIssuesRequest) {
    setLastIssuesRequest(issuesRequest);
    if (issuesRequest) setIssuesOpen(true);
  }
  const [localPanel, setLocalPanel] = useState<InspectorPanel>(null);
  // The graph, or one row per feature the detector receives; both show the same design.
  const [view, setView] = useState<"graph" | "features">("graph");
  const [adding, setAdding] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragFrame = useRef<number | undefined>(undefined);
  const panel = inspectorPanel === undefined ? localPanel : inspectorPanel;
  const panelId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const briefButton = useRef<HTMLButtonElement>(null);
  const serviceButton = useRef<HTMLButtonElement>(null);
  // The status is where the detectors open from when its list asks for one.
  const [statusButton, setStatusButton] = useState<HTMLButtonElement | null>(null);
  const componentButton = useRef<HTMLButtonElement>(null);
  const testButton = useRef<HTMLButtonElement>(null);
  const addedFromMenu = useRef(false);
  const menu = useRef<HTMLDivElement>(null);
  const top = useRef<HTMLDivElement>(null);
  const settingsPanel = useRef<HTMLDivElement>(null);
  const stageCanvas = useRef<HTMLDivElement>(null);
  const insets = useCoveredEdges(stage, stageCanvas, top, settingsPanel, !!panel);
  const phone = useSyncExternalStore(watchPhone, onPhone, () => false);
  const drawer = panel === "component" && !phone;
  const { height: drawerHeight, grip } = useDrawerHeight();
  // The stage's own actions sit at the top right, where toasts would cover them.
  usePlaceToasts(stage ? "bottom-center" : undefined);
  useEffect(() => () => { if (dragFrame.current !== undefined) cancelAnimationFrame(dragFrame.current); }, []);
  const finishDrag = () => {
    if (dragFrame.current !== undefined) cancelAnimationFrame(dragFrame.current);
    dragFrame.current = undefined;
    setDragging(false);
  };
  const setMenu = (open: boolean) => {
    setAdding(open);
    if (!open) finishDrag();
  };
  const setPanel = (next: InspectorPanel) => {
    setLocalPanel(next);
    onInspectorPanelChange?.(next);
  };
  // What is left to do is listed at the status, which stands with the design. Where a brief is read
  // in place of the design, as on a phone, the design takes its turn when that list is asked for.
  const showDesign = useRef(() => {});
  useEffect(() => { showDesign.current = () => { if (panel === "brief") setPanel(null); }; });
  useEffect(() => {
    const canvas = stageCanvas.current;
    if (issuesRequest && canvas && getComputedStyle(canvas).visibility === "hidden") showDesign.current();
  }, [issuesRequest]);
  // Opening a panel moves focus into it; a panel that is open from the start leaves focus alone.
  const shownPanel = useRef(panel);
  useEffect(() => {
    if (panel && panel !== shownPanel.current) heading.current?.focus({ preventScroll: true });
    shownPanel.current = panel;
  }, [panel]);
  const toggle = (which: Exclude<InspectorPanel, null>) => panel === which ? close() : setPanel(which);
  const close = () => {
    setPanel(null);
    (panel === "brief" ? briefButton : panel === "service" ? serviceButton : panel === "test" ? testButton : componentButton).current?.focus();
  };
  // Steps chosen together on the canvas. The group stands while the step in focus is one of
  // them, so focusing another step from anywhere lets it go.
  const [group, setGroup] = useState<string[]>([]);
  const focus = props.selected;
  const nodes = props.document.definition.nodes;
  const selection = useMemo(() => {
    const chosen = focus && group.includes(focus) ? group.filter((id) => nodes.some((node) => node.id === id)) : [];
    return chosen.length > 1 ? chosen : focus ? [focus] : [];
  }, [group, focus, nodes]);
  const select = (id?: string) => {
    setGroup([]);
    if (id) setPanel("component");
    props.onSelect(id);
  };
  // Letting go of a step on the canvas closes its settings too, instead of leaving them empty.
  const selectOnCanvas = (id?: string) => {
    if (!id && panel === "component") setPanel(null);
    select(id);
  };
  // Gathering steps opens no settings; the last one gathered comes into focus when the one that was has left.
  const choose = (ids: string[]) => {
    if (!ids.length) return selectOnCanvas();
    setGroup(ids);
    if (!focus || !ids.includes(focus)) props.onSelect(ids[ids.length - 1], true);
  };
  // The detectors to choose from, opened at the place the design keeps for one or at the
  // status that asks for one. The choice belongs to the design it was opened on.
  const [choosing, setChoosing] = useState<{ x: number; y: number; from: Element;
    definition: Props["document"]["definition"] }>();
  const choice = choosing?.definition === props.document.definition ? choosing : undefined;
  const chooseDetector = (anchor: Element) => {
    const box = anchor.getBoundingClientRect();
    setChoosing({ x: box.left, y: box.bottom + 6, from: anchor, definition: props.document.definition });
  };
  const chooseFromStatus = () => {
    setIssuesOpen(false);
    if (statusButton) chooseDetector(statusButton);
  };
  /** Put a detector where the design expects one, connected on both sides. */
  const placeDetector = (component: PipelineComponent) => {
    const filled = fillDetectorSlot(props.document, component, catalog.components);
    if (!filled) return false;
    props.onChange(filled.document);
    setView("graph");
    select(filled.id);
    if (filled.notice) toast(filled.notice, { id: "pipeline-detector" });
    return true;
  };
  // A new step is placed and wired on the graph, with its settings open.
  const openAdded = () => {
    addedFromMenu.current = adding;
    setMenu(false);
    setPanel("component");
    setView("graph");
  };
  const add: Props["onAdd"] = (componentId, position) => {
    openAdded();
    // A detector picked from the menu goes to its place; one dropped on the canvas stays where it was dropped.
    const component = position ? undefined : catalog.components.find((item) => item.id === componentId);
    if (component?.kind === "detector" && placeDetector(component)) return;
    props.onAdd(componentId, position);
  };
  const place = (placed: { document: GraphDocument; id: string }) => {
    openAdded();
    if (onPlace) return onPlace(placed);
    props.onChange(placed.document);
    props.onSelect(placed.id);
  };
  const toolbar = <div className="pl-canvas-toolbar">
    <div className="pl-actions">
      {!props.readOnly && <Popover.Root open={adding} onOpenChange={setMenu}>
        <Popover.Trigger><Plus size={16} aria-hidden="true" />Add step</Popover.Trigger>
        <Popover.Portal><div className={`pl-component-portal${dragging ? " is-dragging" : ""}`}>
          <Popover.Content ref={menu} className="pl-library pl-component-menu" align="start" sideOffset={8} collisionPadding={12}
          aria-label="Add a step" onOpenAutoFocus={(event) => {
            // Typing narrows the steps at once; Close stays one Shift+Tab away.
            const search = menu.current?.querySelector<HTMLInputElement>("input[type='search']");
            if (!search) return;
            event.preventDefault();
            search.focus();
          }} onCloseAutoFocus={(event) => {
            if (addedFromMenu.current) {
              event.preventDefault();
              addedFromMenu.current = false;
              heading.current?.focus({ preventScroll: true });
            }
          }}>
          <div className="pl-component-menu-heading"><h3>Add a step</h3>
            <Popover.Close aria-label="Close steps"><X size={16} aria-hidden="true" /></Popover.Close>
          </div>
          <PipelineToolbox components={catalog.components} document={props.document} onAdd={add}
            blocks={adding ? blockChoices(library.blocks, catalog.components,
              (block) => placeBlock(props.document, block, catalog.components, undefined, props.selected)) : []}
            onPlace={place}
            onSelect={(id) => { setMenu(false); select(id); }}
            onDragStart={() => {
              // Keep the source visible until the browser captures its drag image.
              dragFrame.current = requestAnimationFrame(() => {
                dragFrame.current = undefined;
                setDragging(true);
              });
            }}
            onDragEnd={() => setMenu(false)} />
        </Popover.Content></div></Popover.Portal>
      </Popover.Root>}
      {actions}
      <div className="pl-segmented pl-view-switch" role="group" aria-label="View">
        {(["graph", "features"] as const).map((item) => <button type="button" key={item}
          aria-pressed={view === item} onClick={() => setView(item)}>
          {item === "graph" ? "Graph" : "Features"}
        </button>)}
      </div>
    </div>
    <div className="pl-actions" aria-label="Settings panels">
      {(status || failed) && <Popover.Root open={issuesOpen} onOpenChange={setIssuesOpen}>
        <Popover.Trigger ref={setStatusButton} className={`pl-issue-status${failed || errors ? " has-issues" : warnings && !open.length ? " has-warnings" : ""}${
          checking ? " is-checking" : ""}`}
          aria-label={`${statusLabel}${checking ? ", checking changes" : ""}`}>
          {failed ? <><TriangleAlert size={15} aria-hidden="true" />Not checked</>
            : errors
              ? <><TriangleAlert size={15} aria-hidden="true" />{issueCount} {errors === 1 ? "issue" : "issues"}</>
              : openText ? <><CircleDashed size={15} aria-hidden="true" />{openText}</>
                : <><CircleCheck size={15} aria-hidden="true" />Complete
                  {warningCount && <span className="pl-issue-warnings">· {warningCount}</span>}
                  {estimate && <span className="pl-issue-startup">· first alarm after {estimate}</span>}</>}
        </Popover.Trigger>
        <Popover.Portal><Popover.Content className="pl-library pl-issue-popover" align="end" sideOffset={8} collisionPadding={12}
          aria-label="Design check">
          <div className="pl-component-menu-heading">
            <h3>{failed ? "Design not checked" : errors ? "Needs attention" : open.length ? "Left to do" : "Design is complete"}</h3>
            <Popover.Close aria-label="Close design check"><X size={16} aria-hidden="true" /></Popover.Close>
          </div>
          {failed ? <>
            <p className="pl-help" role="alert">The latest changes could not be checked. {validationError}</p>
            {onRetryValidation && <button type="button" onClick={onRetryValidation}>Check again</button>}
          </> : status && <>
            {checking && <p className="pl-help" role="status">Checking the latest changes…</p>}
            {status.issues_truncated && <p className="pl-help">Some messages were left out.
              Resolve the listed ones to see the rest.</p>}
            {shown.length > 0 && <ul>{shown.map((issue, index) => {
              // Warnings are marked by name too, not only by their colour.
              const label = issue.tone === "warning" ? `Warning: ${issue.message}` : undefined;
              const act = issue.detector && !props.readOnly
                ? chooseFromStatus
                : issue.node_id ? () => { setIssuesOpen(false); select(issue.node_id); } : undefined;
              return <li key={index} className={issue.tone === "error" ? undefined : `is-${issue.tone}`}>
                {act ? <button type="button" aria-label={label} onClick={act}>{issue.message}</button>
                  : <span aria-label={label}>{issue.message}</span>}
              </li>;
            })}</ul>}
            {!errors && !open.length && <>
              {!warnings && <p className="pl-help">Every step is connected and set up.</p>}
              {startup && <p className="pl-help">{startupSentence(startup)}</p>}
            </>}
          </>}
        </Popover.Content></Popover.Portal>
      </Popover.Root>}
      {brief && <button type="button" ref={briefButton} className="pl-brief-button"
        aria-expanded={panel === "brief"} aria-controls={panelId}
        onClick={() => toggle("brief")}>{brief.label}</button>}
      {settings && <button type="button" ref={serviceButton} aria-label="Service settings"
        aria-expanded={panel === "service"} aria-controls={panelId}
        onClick={() => toggle("service")}>Service</button>}
      <button type="button" ref={componentButton} aria-label="Step settings"
        aria-expanded={panel === "component"} aria-controls={panelId}
        onClick={() => toggle("component")}>Step</button>
      {test && <button type="button" ref={testButton} className="pl-test-button"
        aria-expanded={panel === "test"} aria-controls={panelId}
        onClick={() => toggle("test")}>{testLabel ?? "Test"}</button>}
    </div>
  </div>;
  // On a phone the brief and the design take turns on the screen, so two tabs say which one shows.
  // A wide screen shows both side by side and has no use for them.
  const tabs = stage && brief && <div className="pl-segmented pl-stage-tabs" role="group" aria-label="Show">
    <button type="button" aria-pressed={panel === "brief"} aria-controls={panelId}
      onClick={() => { if (panel !== "brief") setPanel("brief"); }}>{brief.label}</button>
    <button type="button" aria-pressed={panel !== "brief"}
      onClick={() => { if (panel === "brief") setPanel(null); }}>Design</button>
  </div>;
  const canvas = view === "features"
    ? <PipelineFeatures document={props.document} components={catalog.components} report={latest}
      stale={checking || failed} selected={props.selected} readOnly={props.readOnly} onSelect={select}
      onChange={(document) => props.onChange(document)} />
    : <PipelineCanvas {...props} components={catalog.components} issues={validation?.issues}
      features={latest?.features} featuresStale={checking || failed}
      selection={selection} onSelect={selectOnCanvas} onSelectionChange={choose} onAdd={add} insets={insets}
      onConfigure={select} onChooseDetector={chooseDetector}
      blocks={library.blocks} onSaveBlock={saveBlock} />;
  // What a panel is called, in its heading and on the button that closes it. A step's settings are headed by the step.
  const panelTitle = panel === "brief" ? brief?.label ?? "" : panel === "service" ? "Service settings" : "Test on history";
  const panelName = panel === "brief" ? panelTitle.toLowerCase() : panel === "test" ? "test" : "settings";
  const settingsContent = panel && <div className={`pl-settings-panel${panel === "brief" ? " pl-settings-panel--brief" : ""}${
    drawer ? " pl-settings-panel--drawer" : ""}`}
    id={panelId} ref={settingsPanel} style={drawer ? { height: drawerHeight } : undefined} onKeyDown={(event) => {
    if (event.key === "Escape" && !event.defaultPrevented && !(event.target instanceof HTMLSelectElement)) {
      event.stopPropagation(); close();
    }
  }}>
    {drawer && <div className="pl-drawer-grip" {...grip} />}
    <PipelineInspector document={props.document} catalog={catalog} selected={props.selected} selection={selection}
      validation={validation} lastValidation={lastValidation} readOnly={props.readOnly} onSelect={select}
      onChange={props.onChange} input={input} forecast={forecast} values={stepValues}
      headingRef={heading} onClose={close} onSaveBlock={saveBlock} layout={drawer ? "drawer" : "side"}
      header={panel !== "component" && <div className="pl-inspector-heading">
        <h3 ref={heading} tabIndex={-1}>{panelTitle}</h3>
        <button type="button" onClick={close} aria-label={`Close ${panelName}`} title={`Collapse ${panelName}`}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>}
      content={panel === "brief" ? brief?.content : panel === "service" ? settings : panel === "test" ? test : undefined} />
  </div>;
  const blockDialog = savingFrom && blockChain(props.document.definition, savingFrom).length > 0
    && <PipelineSaveBlock document={props.document} components={catalog.components} from={savingFrom} onSave={library.save}
      onClose={() => setSavingFrom(undefined)} />;
  const detectorChoice = choice && <PipelineContextMenu x={choice.x} y={choice.y}
    menu={detectorMenu(catalog.components, suggestedDetector(catalog), placeDetector)}
    onClose={(restore) => {
      setChoosing(undefined);
      if (restore && choice.from instanceof HTMLElement) choice.from.focus({ preventScroll: true });
    }} />;
  // The header comes first in the page, as it does on screen, so Tab reaches it before the canvas.
  if (stage) return <div className={`pl-workbench pl-stage pl-stage--${view}${panel === "brief" ? " pl-stage--reading" : ""}${
    drawer ? " pl-stage--drawer" : ""}`}
    style={{ "--pl-covered-right": `${insets?.right ?? 0}px`, "--pl-covered-bottom": `${insets?.bottom ?? 0}px` } as CSSProperties}>
    <div className="pl-stage-top" ref={top}>{header}{tabs}{toolbar}</div>
    <div className="pl-stage-canvas" ref={stageCanvas}>{canvas}</div>
    <div className="pl-stage-body">{settingsContent}</div>
    {detectorChoice}
    {blockDialog}
  </div>;
  return <div className="pl-workbench">
    {toolbar}
    <div className={`pl-editor-grid${drawer ? " pl-editor-grid--drawer" : panel ? " pl-editor-grid--settings" : ""}`}>
      {canvas}
      {settingsContent}
    </div>
    {detectorChoice}
    {blockDialog}
  </div>;
}
