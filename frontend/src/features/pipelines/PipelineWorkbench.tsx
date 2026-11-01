import { useEffect, useId, useRef, useState, type ComponentProps, type ReactNode } from "react";
import * as Popover from "@radix-ui/react-popover";
import { CircleCheck, Plus, TriangleAlert, X } from "lucide-react";
import type { PipelineCatalog } from "./contracts";
import PipelineCanvas from "./PipelineCanvas";
import { PipelineInspector } from "./PipelineInspector";
import { PipelineToolbox } from "./PipelineToolbox";
import { startupSentence, startupSummary, type Startup } from "./startup";
import { useUndoShortcuts } from "./useGraphEditor";

export type InspectorPanel = "service" | "component" | null;
type Props = Omit<ComponentProps<typeof PipelineCanvas>, "components" | "issues" | "features" | "featuresStale"> & {
  catalog: PipelineCatalog;
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
};

/** One canvas-first workspace for creation, saved designs and running graphs. */
export function PipelineWorkbench({
  catalog, validation, settings, actions, inspectorPanel, onInspectorPanelChange,
  onUndo, onRedo, issuesRequest = 0, input, startup, validationError, onRetryValidation, ...props
}: Props) {
  useUndoShortcuts(!props.readOnly && !!onUndo && !!onRedo, () => onUndo?.(), () => onRedo?.());
  const [issuesOpen, setIssuesOpen] = useState(false);
  // Keep the last result on screen while an edit is re-checked, instead of flickering away.
  const [lastValidation, setLastValidation] = useState(validation);
  if (validation && validation !== lastValidation) setLastValidation(validation);
  const failed = !validation && !!validationError;
  const checking = !validation && !failed && !!lastValidation;
  const status = failed ? undefined : validation ?? lastValidation;
  const estimate = startup && startupSummary(startup);
  const issueCount = status && `${status.issues.length}${status.issues_truncated ? "+" : ""}`;
  const statusLabel = failed ? "Graph not checked" : status?.issues.length
    ? `${issueCount} graph ${status.issues.length === 1 ? "issue" : "issues"}`
    : `Graph is valid${estimate ? `, first alarm after ${estimate.replace("≈", "about")}` : ""}`;
  const [lastIssuesRequest, setLastIssuesRequest] = useState(issuesRequest);
  if (issuesRequest !== lastIssuesRequest) {
    setLastIssuesRequest(issuesRequest);
    if (issuesRequest) setIssuesOpen(true);
  }
  const [localPanel, setLocalPanel] = useState<InspectorPanel>(null);
  const [adding, setAdding] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragFrame = useRef<number | undefined>(undefined);
  const panel = inspectorPanel === undefined ? localPanel : inspectorPanel;
  const panelId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const serviceButton = useRef<HTMLButtonElement>(null);
  const componentButton = useRef<HTMLButtonElement>(null);
  const addedFromMenu = useRef(false);
  const menu = useRef<HTMLDivElement>(null);
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
  const add: Props["onAdd"] = (...args) => {
    addedFromMenu.current = adding;
    setMenu(false);
    setPanel("component");
    props.onAdd(...args);
  };
  return <div className="pl-workbench">
    <div className="pl-canvas-toolbar">
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
      </div>
      <div className="pl-actions" aria-label="Settings panels">
        {(status || failed) && <Popover.Root open={issuesOpen} onOpenChange={setIssuesOpen}>
          <Popover.Trigger className={`pl-issue-status${failed || status?.issues.length ? " has-issues" : ""}${checking ? " is-checking" : ""}`}
            aria-label={`${statusLabel}${checking ? ", checking changes" : ""}`}>
            {failed ? <><TriangleAlert size={15} aria-hidden="true" />Not checked</>
              : status?.issues.length
                ? <><TriangleAlert size={15} aria-hidden="true" />{issueCount} {status.issues.length === 1 ? "issue" : "issues"}</>
                : <><CircleCheck size={15} aria-hidden="true" />Valid{estimate && <span className="pl-issue-startup">· first alarm after {estimate}</span>}</>}
          </Popover.Trigger>
          <Popover.Portal><Popover.Content className="pl-library pl-issue-popover" align="end" sideOffset={8} collisionPadding={12}
            aria-label="Graph validation">
            <div className="pl-component-menu-heading">
              <h3>{failed ? "Graph not checked" : status?.valid ? "Valid processing graph" : "Validation errors"}</h3>
              <Popover.Close aria-label="Close validation"><X size={16} aria-hidden="true" /></Popover.Close>
            </div>
            {failed ? <>
              <p className="pl-help" role="alert">The latest changes could not be checked. {validationError}</p>
              {onRetryValidation && <button type="button" onClick={onRetryValidation}>Check again</button>}
            </> : status && <>
              {checking && <p className="pl-help" role="status">Checking the latest changes…</p>}
              {status.issues_truncated && <p className="pl-help">Additional validation messages were omitted.
                Resolve the listed issues to see the rest.</p>}
              {status.issues.length ? <ul>{status.issues.map((issue, index) => <li key={index}>
                {issue.node_id
                  ? <button type="button" onClick={() => { setIssuesOpen(false); select(issue.node_id!); }}>{issue.message}</button>
                  : <span>{issue.message}</span>}
              </li>)}</ul> : <>
                <p className="pl-help">The compiler accepts this graph.</p>
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
    </div>
    <div className={`pl-editor-grid${panel ? " pl-editor-grid--settings" : ""}`}>
      <PipelineCanvas {...props} components={catalog.components} issues={validation?.issues}
        features={(validation ?? lastValidation)?.features} featuresStale={checking || failed} onSelect={select} onAdd={add} />
      {panel && <div className="pl-settings-panel" id={panelId} onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented && !(event.target instanceof HTMLSelectElement)) {
          event.stopPropagation(); close();
        }
      }}>
        <PipelineInspector document={props.document} catalog={catalog} selected={props.selected}
          validation={validation} readOnly={props.readOnly} onSelect={select} onChange={props.onChange} input={input}
          header={<div className="pl-inspector-heading">
            <h3 ref={heading} tabIndex={-1}>{panel === "service" ? "Service settings" : "Step settings"}</h3>
            <button type="button" onClick={close} aria-label="Close settings" title="Collapse settings">
              <X size={16} aria-hidden="true" />
            </button>
          </div>}
          content={panel === "service" ? settings : undefined} />
      </div>}
    </div>
  </div>;
}
