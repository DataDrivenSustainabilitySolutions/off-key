import { useState, type ComponentProps, type ReactNode } from "react";
import type { PipelineCatalog } from "./contracts";
import PipelineCanvas from "./PipelineCanvas";
import { PipelineInspector } from "./PipelineInspector";
import { PipelineToolbox } from "./PipelineToolbox";

type Props = Omit<ComponentProps<typeof PipelineCanvas>, "components" | "issues"> & {
  catalog: PipelineCatalog;
  validation?: ComponentProps<typeof PipelineInspector>["validation"];
  settings?: ReactNode;
  inspectorPanel?: "service" | "component";
  onInspectorPanelChange?: (panel: "service" | "component") => void;
};

/** Creation and saved revisions share the same canvas, toolbox, and inspector. */
export function PipelineWorkbench({ catalog, validation, settings, inspectorPanel, onInspectorPanelChange, ...props }: Props) {
  const [localPanel, setLocalPanel] = useState<"service" | "component">(settings ? "service" : "component");
  const panel = inspectorPanel ?? localPanel;
  const setPanel = (next: "service" | "component") => { setLocalPanel(next); onInspectorPanelChange?.(next); };
  const select = (id: string) => { setPanel("component"); props.onSelect(id); };
  const add: Props["onAdd"] = (...args) => { setPanel("component"); props.onAdd(...args); };
  const tabs = settings && <div className="pl-inspector-tabs" role="group" aria-label="Inspector view">
    {(["service", "component"] as const).map((tab) => <button key={tab} type="button" aria-pressed={panel === tab}
      onClick={() => setPanel(tab)}>
      {tab === "service" ? "Service settings" : "Component settings"}
    </button>)}
  </div>;
  return <div className={`pl-editor-grid${props.readOnly ? " pl-editor-grid--readonly" : ""}`}>
    {!props.readOnly && <PipelineToolbox catalog={catalog} definition={props.document.definition} onAdd={add} />}
    <PipelineCanvas {...props} components={catalog.components} issues={validation?.issues} onSelect={select} onAdd={add} />
    <PipelineInspector document={props.document} catalog={catalog} selected={props.selected}
      validation={validation} readOnly={props.readOnly} onSelect={select} onChange={props.onChange}
      header={tabs} content={settings && panel === "service"
        ? settings
        : undefined} />
  </div>;
}
