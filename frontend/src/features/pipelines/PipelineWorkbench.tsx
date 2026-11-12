import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ComponentProps, type CSSProperties, type ReactNode, type RefObject } from "react";
import * as Popover from "@radix-ui/react-popover";
import toast from "react-hot-toast";
import { CircleCheck, CircleDashed, Plus, TriangleAlert, X } from "lucide-react";
import type { PipelineCatalog, PipelineComponent } from "./contracts";
import { blockChoices, placeBlock, useBlocks } from "./blocks";
import { detectorMenu, fillDetectorSlot, suggestedDetector } from "./detectorSlot";
import { useForecastModels, usesForecastService, withForecastService } from "./forecastModels";
import type { GraphDocument } from "./model";
import PipelineCanvas from "./PipelineCanvas";
import { PipelineContextMenu } from "./PipelineContextMenu";
import { PipelineFeatures } from "./PipelineFeatures";
import { PipelineInspector } from "./PipelineInspector";
import { PipelineToolbox } from "./PipelineToolbox";
import { openSummary, showIssues } from "./issues";
import { startupSentence, startupSummary, type Startup } from "./startup";
import type { CoveredEdges } from "./viewport";
import { useUndoShortcuts } from "./useGraphEditor";
import { usePlaceToasts } from "@/hooks/use-toast-position";

export type InspectorPanel = "service" | "component" | null;
type Props = Omit<ComponentProps<typeof PipelineCanvas>,
  "components" | "issues" | "features" | "featuresStale" | "insets" | "blocks" | "onSaveBlock"> & {
  catalog: PipelineCatalog;
  /** Takes steps the Add step menu placed, such as a block's, so the editor records and shows them. */
  onPlace?: (placed: { document: GraphDocument; id: string }) => void;
  validation?: ComponentProps<typeof PipelineInspector>["validation"];
  settings?: ReactNode;
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

/** How far a stage's header and settings reach over its canvas, in pixels. */
function useCoveredEdges(stage: boolean, canvas: RefObject<HTMLElement | null>, top: RefObject<HTMLElement | null>,
  panel: RefObject<HTMLElement | null>, open: boolean) {
  const [covered, setCovered] = useState<CoveredEdges>();
  useLayoutEffect(() => {
    if (!stage) return;
    const measure = () => {
      const area = canvas.current?.getBoundingClientRect();
      const header = top.current?.getBoundingClientRect();
      const settings = open ? panel.current?.getBoundingClientRect() : undefined;
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
  catalog: offered, validation, settings, actions, inspectorPanel, onInspectorPanelChange,
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
  useUndoShortcuts(!props.readOnly && !!onUndo && !!onRedo, () => onUndo?.(), () => onRedo?.());
  const [issuesOpen, setIssuesOpen] = useState(false);
  // Keep the last result on screen while an edit is re-checked, instead of flickering away.
  const [lastValidation, setLastValidation] = useState(validation);
  if (validation && validation !== lastValidation) setLastValidation(validation);
  const failed = !validation && !!validationError;
  const checking = !validation && !failed && !!lastValidation;
  const status = failed ? undefined : validation ?? lastValidation;
  const estimate = startup && startupSummary(startup);
  // Errors block applying the design and warnings do not. Steps still to choose or
  // connect block it too, and read as the work that is left rather than as faults.
  const shown = useMemo(() => showIssues(props.document, catalog.components, status?.issues),
    [props.document, catalog.components, status]);
  const errors = shown.filter((issue) => issue.tone === "error").length;
  const open = shown.filter((issue) => issue.tone === "open");
  const warnings = shown.filter((issue) => issue.tone === "warning").length;
  const issueCount = status && `${errors}${status.issues_truncated ? "+" : ""}`;
  const warningCount = warnings ? `${warnings} ${warnings === 1 ? "warning" : "warnings"}` : "";
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
  const serviceButton = useRef<HTMLButtonElement>(null);
  // The status is where the detectors open from when its list asks for one.
  const [statusButton, setStatusButton] = useState<HTMLButtonElement | null>(null);
  const componentButton = useRef<HTMLButtonElement>(null);
  const addedFromMenu = useRef(false);
  const menu = useRef<HTMLDivElement>(null);
  const top = useRef<HTMLDivElement>(null);
  const settingsPanel = useRef<HTMLDivElement>(null);
  const stageCanvas = useRef<HTMLDivElement>(null);
  const insets = useCoveredEdges(stage, stageCanvas, top, settingsPanel, !!panel);
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
  // Opening a panel moves focus into it; a panel that is open from the start leaves focus alone.
  const shownPanel = useRef(panel);
  useEffect(() => {
    if (panel && panel !== shownPanel.current) heading.current?.focus({ preventScroll: true });
    shownPanel.current = panel;
  }, [panel]);
  const close = () => {
    setPanel(null);
    (panel === "service" ? serviceButton : componentButton).current?.focus();
  };
  const select = (id?: string) => {
    if (id) setPanel("component");
    props.onSelect(id);
  };
  // Letting go of a step on the canvas closes its settings too, instead of leaving them empty.
  const selectOnCanvas = (id?: string) => {
    if (!id && panel === "component") setPanel(null);
    select(id);
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
  const add: Props["onAdd"] = (componentId, position) => {
    addedFromMenu.current = adding;
    setMenu(false);
    setPanel("component");
    // A new step is placed and wired on the graph.
    setView("graph");
    // A detector picked from the menu goes to its place; one dropped on the canvas stays where it was dropped.
    const component = position ? undefined : catalog.components.find((item) => item.id === componentId);
    if (component?.kind === "detector" && placeDetector(component)) return;
    props.onAdd(componentId, position);
  };
  const place = (placed: { document: GraphDocument; id: string }) => {
    addedFromMenu.current = adding;
    setMenu(false);
    setPanel("component");
    setView("graph");
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
      {settings && <button type="button" ref={serviceButton} aria-label="Service settings"
        aria-expanded={panel === "service"} aria-controls={panelId}
        onClick={() => panel === "service" ? close() : setPanel("service")}>Service</button>}
      <button type="button" ref={componentButton} aria-label="Step settings"
        aria-expanded={panel === "component"} aria-controls={panelId}
        onClick={() => panel === "component" ? close() : setPanel("component")}>Step</button>
    </div>
  </div>;
  const canvas = view === "features"
    ? <PipelineFeatures document={props.document} components={catalog.components} report={validation ?? lastValidation}
      stale={checking || failed} selected={props.selected} readOnly={props.readOnly} onSelect={select}
      onChange={(document) => props.onChange(document)} />
    : <PipelineCanvas {...props} components={catalog.components} issues={validation?.issues}
      features={(validation ?? lastValidation)?.features} featuresStale={checking || failed} onSelect={selectOnCanvas} onAdd={add} insets={insets}
      onConfigure={select} onChooseDetector={chooseDetector} blocks={library.blocks} onSaveBlock={props.readOnly ? undefined : library.save} />;
  const settingsContent = panel && <div className="pl-settings-panel" id={panelId} ref={settingsPanel} onKeyDown={(event) => {
    if (event.key === "Escape" && !event.defaultPrevented && !(event.target instanceof HTMLSelectElement)) {
      event.stopPropagation(); close();
    }
  }}>
    <PipelineInspector document={props.document} catalog={catalog} selected={props.selected}
      validation={validation} lastValidation={lastValidation} readOnly={props.readOnly} onSelect={select}
      onChange={props.onChange} input={input} forecast={forecast}
      header={<div className="pl-inspector-heading">
        <h3 ref={heading} tabIndex={-1}>{panel === "service" ? "Service settings" : "Step settings"}</h3>
        <button type="button" onClick={close} aria-label="Close settings" title="Collapse settings">
          <X size={16} aria-hidden="true" />
        </button>
      </div>}
      content={panel === "service" ? settings : undefined} />
  </div>;
  const detectorChoice = choice && <PipelineContextMenu x={choice.x} y={choice.y}
    menu={detectorMenu(catalog.components, suggestedDetector(catalog), placeDetector)}
    onClose={(restore) => {
      setChoosing(undefined);
      if (restore && choice.from instanceof HTMLElement) choice.from.focus({ preventScroll: true });
    }} />;
  // The header comes first in the page, as it does on screen, so Tab reaches it before the canvas.
  if (stage) return <div className={`pl-workbench pl-stage pl-stage--${view}`}
    style={{ "--pl-covered-right": `${insets?.right ?? 0}px` } as CSSProperties}>
    <div className="pl-stage-top" ref={top}>{header}{toolbar}</div>
    <div className="pl-stage-canvas" ref={stageCanvas}>{canvas}</div>
    <div className="pl-stage-body">{settingsContent}</div>
    {detectorChoice}
  </div>;
  return <div className="pl-workbench">
    {toolbar}
    <div className={`pl-editor-grid${panel ? " pl-editor-grid--settings" : ""}`}>
      {canvas}
      {settingsContent}
    </div>
    {detectorChoice}
  </div>;
}
