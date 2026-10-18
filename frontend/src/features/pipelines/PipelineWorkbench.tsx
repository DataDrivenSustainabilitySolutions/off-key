import { useEffect, useId, useRef, useState, type ComponentProps, type ReactNode } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Plus, X } from "lucide-react";
import type { PipelineCatalog } from "./contracts";
import PipelineCanvas from "./PipelineCanvas";
import { PipelineInspector } from "./PipelineInspector";
import { PipelineToolbox } from "./PipelineToolbox";

export type InspectorPanel = "service" | "component" | null;
type Props = Omit<ComponentProps<typeof PipelineCanvas>, "components" | "issues"> & {
  catalog: PipelineCatalog;
  validation?: ComponentProps<typeof PipelineInspector>["validation"];
  settings?: ReactNode;
  actions?: ReactNode;
  inspectorPanel?: InspectorPanel;
  onInspectorPanelChange?: (panel: InspectorPanel) => void;
};

/** One canvas-first workspace for creation, saved designs and running graphs. */
export function PipelineWorkbench({
  catalog, validation, settings, actions, inspectorPanel, onInspectorPanelChange, ...props
}: Props) {
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
  useEffect(() => { if (panel) heading.current?.focus({ preventScroll: true }); }, [panel]);
  const close = () => {
    setPanel(null);
    (panel === "service" ? serviceButton : componentButton).current?.focus();
  };
  const select = (id: string) => {
    setPanel("component");
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
          <Popover.Trigger><Plus size={16} aria-hidden="true" />Add component</Popover.Trigger>
          <Popover.Portal><div className={`pl-component-portal${dragging ? " is-dragging" : ""}`}>
            <Popover.Content className="pl-library pl-component-menu" align="start" sideOffset={8}
            aria-label="Add component" onCloseAutoFocus={(event) => {
              if (addedFromMenu.current) {
                event.preventDefault();
                addedFromMenu.current = false;
                heading.current?.focus({ preventScroll: true });
              }
            }}>
            <div className="pl-component-menu-heading"><h3>Components</h3>
              <Popover.Close aria-label="Close components"><X size={16} aria-hidden="true" /></Popover.Close>
            </div>
            <PipelineToolbox catalog={catalog} definition={props.document.definition} onAdd={add}
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
        {settings && <button type="button" ref={serviceButton} aria-label="Service settings"
          aria-expanded={panel === "service"} aria-controls={panelId}
          onClick={() => panel === "service" ? close() : setPanel("service")}>Service</button>}
        <button type="button" ref={componentButton} aria-label="Component settings"
          aria-expanded={panel === "component"} aria-controls={panelId}
          onClick={() => panel === "component" ? close() : setPanel("component")}>Component</button>
      </div>
    </div>
    <div className={`pl-editor-grid${panel ? " pl-editor-grid--settings" : ""}`}>
      <PipelineCanvas {...props} components={catalog.components} issues={validation?.issues}
        onSelect={select} onAdd={add} />
      {panel && <div className="pl-settings-panel" id={panelId} onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented && !(event.target instanceof HTMLSelectElement)) {
          event.stopPropagation(); close();
        }
      }}>
        <PipelineInspector document={props.document} catalog={catalog} selected={props.selected}
          validation={validation} readOnly={props.readOnly} onSelect={select} onChange={props.onChange}
          header={<div className="pl-inspector-heading">
            <h3 ref={heading} tabIndex={-1}>{panel === "service" ? "Service settings" : "Component settings"}</h3>
            <button type="button" onClick={close} aria-label="Close settings" title="Collapse settings">
              <X size={16} aria-hidden="true" />
            </button>
          </div>}
          content={panel === "service" ? settings : undefined} />
      </div>}
    </div>
  </div>;
}
