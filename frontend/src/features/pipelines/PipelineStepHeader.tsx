import { useRef, useState, type Ref } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, CopyPlus, Ellipsis, Pencil, Power, PowerOff, Save, Trash2, Unlink, X } from "lucide-react";
import { blockChain } from "./blocks";
import { duplicateSteps } from "./clipboard";
import type { PipelineComponent, PipelineNode } from "./contracts";
import type { Menu } from "./contextMenu";
import {
  disconnectNode, duplicateBlocker, nodeLabel, nodeOptionLabeler, removeNode, retitle, stepOrder, type GraphDocument,
} from "./model";
import { PipelineContextMenu } from "./PipelineContextMenu";
import { shownComponent, switchedOff } from "./semantics";
import { SHORTCUTS } from "./shortcuts";
import { familyLabel, stepFamily } from "./steps";
import { StepTitleEditor } from "./StepTitleEditor";
import { switchOffBlocker, switchSteps } from "./stepSwitch";
import type { HistoryMode } from "./types";

type Props = {
  document: GraphDocument;
  components: PipelineComponent[];
  /** The step the settings are for; none while no step or several are chosen. */
  node?: PipelineNode;
  /** What the panel is called while it shows no single step. */
  title: string;
  readOnly?: boolean;
  /** The heading takes focus when the panel opens. */
  headingRef?: Ref<HTMLHeadingElement>;
  onSelect: (id?: string) => void;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
  onClose?: () => void;
  /** Asks to keep the steps from this one on as a block; the menu offers it where this is given. */
  onSaveBlock?: (from: string) => void;
};

/**
 * The head of a step's settings: what kind of step it is, its name, which can be changed in place,
 * what it does in one sentence, the way to the steps beside it and the things that can be done to it.
 */
export function PipelineStepHeader({ document, components, node, title, readOnly, headingRef, onSelect, onChange, onClose,
  onSaveBlock }: Props) {
  // The step being renamed, so the field closes when another step takes its place.
  const [renaming, setRenaming] = useState<string>();
  const rename = useRef<HTMLButtonElement>(null);
  // The menu belongs to the design it was opened on; any edit closes it.
  const [menu, setMenu] = useState<{ x: number; y: number; definition: GraphDocument["definition"] }>();
  const actions = useRef<HTMLButtonElement>(null);
  const closing = useRef(false);
  const order = stepOrder(document);
  const optionLabel = nodeOptionLabeler(document, components);
  const at = node ? order.indexOf(node.id) : -1;
  const off = !!switchedOff(document.layout, node);
  // A step that is switched off is named as what it was.
  const component = shownComponent(node, components, document.layout);
  const label = node ? nodeLabel(node, components, document.layout) : title;
  const operation = component?.label ?? node?.component;
  const connected = !!node && document.definition.edges.some((edge) => edge.source === node.id || edge.target === node.id);
  const stepMenu = (step: PipelineNode): Menu => ({ label, items: [
    { key: "duplicate", label: "Duplicate", icon: CopyPlus, keys: SHORTCUTS.duplicate,
      blocked: duplicateBlocker(document.definition, step.id, components),
      run: () => {
        const copy = duplicateSteps(document, [step.id], components);
        if (!copy?.ids[0]) return;
        onChange(copy.document);
        onSelect(copy.ids[0]);
      } },
    // Listed for the steps it is for; elsewhere it would only say that it cannot be done.
    ...(step.kind === "transform" ? [{ key: "switch", label: off ? "Switch on" : "Switch off", icon: off ? Power : PowerOff,
      keys: SHORTCUTS.switch, blocked: off ? undefined : switchOffBlocker(document, step.id, components),
      run: () => {
        const turned = switchSteps(document, [step.id], components);
        if (turned) onChange(turned.document);
      } }] : []),
    ...(onSaveBlock ? [{ key: "block", label: "Save as block", icon: Save,
      blocked: blockChain(document.definition, step.id).length ? undefined : "A block holds steps between the input and a detector.",
      run: () => onSaveBlock(step.id) }] : []),
    { key: "disconnect", label: "Disconnect", icon: Unlink, blocked: connected ? undefined : "This step has no connections.",
      run: () => onChange(disconnectNode(document, step.id)) },
    { key: "remove", label: "Remove step", icon: Trash2, keys: SHORTCUTS.remove, destructive: true, separated: true,
      run: () => onChange(removeNode(document, step.id)) },
  ] });
  const shownMenu = node && menu?.definition === document.definition ? menu : undefined;
  return <header className="pl-step-head">
    <div className="pl-step-bar">
      {node && <span className={`pl-step-kind${off ? " is-off" : ""}`}>
        {familyLabel(stepFamily(node, component))}{off && <small>Switched off</small>}
      </span>}
      <div className="pl-step-controls">
      {order.length > 0 && <div className="pl-step-nav" role="group" aria-label="Steps">
        {node && <button type="button" aria-label="Previous step" title="Previous step" disabled={at <= 0}
          onClick={() => onSelect(order[at - 1])}><ChevronLeft size={16} aria-hidden="true" /></button>}
        {/* Where the step stands among the others; choosing from it goes straight to any of them. */}
        <label className="pl-step-jump" title="Go to a step">
          <span aria-hidden="true">{node ? `${at + 1} of ${order.length}` : "Go to a step"}<ChevronDown size={12} /></span>
          <select aria-label="Selected step" value={node?.id ?? ""} onChange={(event) => onSelect(event.target.value || undefined)}>
            {!node && <option value="">Choose a step</option>}
            {order.map((id) => <option key={id} value={id}>
              {optionLabel(document.definition.nodes.find((item) => item.id === id))}
            </option>)}
          </select>
        </label>
        {node && <button type="button" aria-label="Next step" title="Next step" disabled={at >= order.length - 1}
          onClick={() => onSelect(order[at + 1])}><ChevronRight size={16} aria-hidden="true" /></button>}
      </div>}
      {node && !readOnly && <button type="button" ref={actions} aria-label="Step actions" title="Step actions"
        aria-haspopup="menu" aria-expanded={!!shownMenu}
        // Pressing the button while its menu is open closes the menu, as pressing anywhere else does.
        onPointerDown={() => { closing.current = !!shownMenu; }}
        onClick={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          if (!closing.current) setMenu({ x: box.left, y: box.bottom + 4, definition: document.definition });
          closing.current = false;
        }}><Ellipsis size={16} aria-hidden="true" /></button>}
      {onClose && <button type="button" onClick={onClose} aria-label="Close settings" title="Collapse settings">
        <X size={16} aria-hidden="true" />
      </button>}
      </div>
    </div>
    <div className="pl-step-title">
      {node && renaming === node.id
        ? <StepTitleEditor title={label} operation={operation ?? ""} onFinish={(typed) => {
          setRenaming(undefined);
          // Back on the button, so the keyboard carries on where the rename started.
          requestAnimationFrame(() => rename.current?.focus({ preventScroll: true }));
          const titled = typed === undefined ? undefined : retitle(document, components, node.id, typed);
          if (titled) onChange(titled, true);
        }} />
        : <>
          <h3 ref={headingRef} tabIndex={-1} title={label}
            onDoubleClick={node && !readOnly ? () => setRenaming(node.id) : undefined}>{label}</h3>
          {node && !readOnly && <button type="button" ref={rename} className="pl-step-rename" aria-label="Rename step" title="Rename"
            onClick={() => setRenaming(node.id)}><Pencil size={14} aria-hidden="true" /></button>}
        </>}
    </div>
    {node && label !== operation && <p className="pl-step-operation">{operation}</p>}
    {component?.description && <p className="pl-step-lede" title={component.description}>{component.description}</p>}
    {shownMenu && node && <PipelineContextMenu x={shownMenu.x} y={shownMenu.y} menu={stepMenu(node)}
      onClose={(restore) => {
        setMenu(undefined);
        if (restore) actions.current?.focus({ preventScroll: true });
      }} />}
  </header>;
}
