import { useMemo, useRef, useState, type DragEvent } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  applyNodeChanges,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import { useTheme } from "@/components/theme-provider";
import type { PipelineComponent } from "./contracts";
import { connectNodes, nodeLabel, type GraphDocument } from "./model";
import "@xyflow/react/dist/style.css";

type CanvasData = {
  label: string;
  kind: string;
  component: string;
  inputType?: string | null;
  outputType?: string;
  state?: string;
  [key: string]: unknown;
};
type CanvasNode = Node<CanvasData, "component">;

function ComponentNode({ data, selected }: NodeProps<CanvasNode>) {
  return (
    <div
      className={`pl-node pl-node--${data.kind}${selected ? " is-selected" : ""}`}
    >
      {data.kind !== "source" && (
        <Handle
          type="target"
          position={Position.Left}
          title={`Input: ${data.inputType ?? "features"}`}
        />
      )}
      <span className="pl-node-kind">{data.kind}</span>
      <strong>{data.label}</strong>
      {data.state && (
        <small className="pl-node-state">{data.state.replace(/_/g, " ")}</small>
      )}
      <small className="pl-node-state">
        {data.inputType ? `${data.inputType.replace(/_/g, " ")} → ` : ""}
        {data.outputType?.replace(/_/g, " ")}
      </small>
      {data.kind !== "output" && (
        <Handle
          type="source"
          position={Position.Right}
          title={`Output: ${data.outputType ?? "features"}`}
        />
      )}
    </div>
  );
}
const nodeTypes = { component: ComponentNode };
type Props = {
  document: GraphDocument;
  components: PipelineComponent[];
  selected?: string;
  readOnly?: boolean;
  layoutEditable?: boolean;
  states?: Record<string, string>;
  onSelect: (id: string) => void;
  onChange: (document: GraphDocument, recordHistory?: boolean) => void;
  onAdd: (componentId: string, position?: { x: number; y: number }) => void;
  onBeginMove?: () => void;
};

export default function PipelineCanvas({
  document,
  components,
  selected,
  readOnly,
  layoutEditable,
  states,
  onSelect,
  onChange,
  onAdd,
  onBeginMove,
}: Props) {
  const { resolvedTheme } = useTheme();
  const [feedback, setFeedback] = useState("");
  const [flow, setFlow] = useState<ReactFlowInstance<CanvasNode>>();
  const [selectedEdges, setSelectedEdges] = useState<string[]>([]);
  const moving = useRef(false);
  const nodes = useMemo<CanvasNode[]>(
    () =>
      document.definition.nodes.map((node, index) => ({
        id: node.id,
        type: "component",
        position: document.layout.nodes[node.id] ?? { x: index * 250, y: 100 },
        selected: node.id === selected,
        data: {
          label: nodeLabel(node, components, document.layout),
          kind: node.kind,
          component: node.component,
          state: states?.[node.id],
          inputType: components.find((item) => item.id === node.component)
            ?.input_type,
          outputType: components.find((item) => item.id === node.component)
            ?.output_type,
        },
      })),
    [document, components, selected, states],
  );
  const edges = useMemo(
    () =>
      document.definition.edges.map((edge, index) => ({
        id: `${edge.source}-${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
        label:
          document.definition.nodes.find((node) => node.id === edge.target)
            ?.kind === "merge"
            ? `Features · input ${edge.order + 1}`
            : components
                .find(
                  (item) =>
                    item.id ===
                    document.definition.nodes.find(
                      (node) => node.id === edge.source,
                    )?.component,
                )
                ?.output_type?.replace(/_/g, " "),
        style: { strokeWidth: 2 },
        selectable: !readOnly,
        selected: selectedEdges.includes(
          `${edge.source}-${edge.target}-${index}`,
        ),
      })),
    [document.definition, components, readOnly, selectedEdges],
  );
  const drop = (event: DragEvent) => {
    event.preventDefault();
    if (!readOnly)
      onAdd(
        event.dataTransfer.getData("application/off-key-component"),
        flow?.screenToFlowPosition({ x: event.clientX, y: event.clientY }),
      );
  };
  return (
    <div
      className="pl-canvas-wrap"
      aria-label="Pipeline graph"
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={drop}
    >
      <ReactFlow<CanvasNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={setFlow}
        colorMode={resolvedTheme}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        nodesDraggable={layoutEditable || !readOnly}
        nodesConnectable={!readOnly}
        elementsSelectable
        onNodeClick={(_event, node) => onSelect(node.id)}
        onNodeDragStart={() => {
          moving.current = true;
          onBeginMove?.();
        }}
        onNodeDragStop={() => {
          moving.current = false;
        }}
        onNodesChange={(changes) => {
          const selection = changes.find(
            (change) => change.type === "select" && change.selected,
          );
          if (selection?.type === "select") onSelect(selection.id);
          const positions = changes.filter(
            (change) => change.type === "position",
          );
          if ((readOnly && !layoutEditable) || !positions.length) return;
          const next = applyNodeChanges<CanvasNode>(positions, nodes);
          onChange(
            {
              ...document,
              layout: {
                ...document.layout,
                nodes: Object.fromEntries(
                  next.map((node) => [
                    node.id,
                    { ...document.layout.nodes[node.id], ...node.position },
                  ]),
                ),
              },
            },
            !moving.current,
          );
        }}
        onEdgesChange={(changes) =>
          setSelectedEdges((previous) => {
            const next = new Set(previous);
            for (const change of changes)
              if (change.type === "select") {
                if (change.selected) next.add(change.id);
                else next.delete(change.id);
              }
            return [...next];
          })
        }
        onConnect={(connection) => {
          const definition = connectNodes(
            document.definition,
            connection.source,
            connection.target,
          );
          if (definition === document.definition)
            setFeedback(
              "This connection is already present, creates a cycle, or the input is occupied. Use the inspector to remove an existing connection.",
            );
          else {
            setFeedback("");
            onChange({ ...document, definition });
          }
        }}
        onBeforeDelete={async ({
          nodes: removedNodes,
          edges: removedEdges,
        }) => {
          if (readOnly) return false;
          const ids = new Set(removedNodes.map((node) => node.id));
          const edgeIds = new Set(removedEdges.map((edge) => edge.id));
          onChange({
            definition: {
              ...document.definition,
              nodes: document.definition.nodes.filter(
                (node) => !ids.has(node.id),
              ),
              edges: document.definition.edges.filter(
                (edge, index) =>
                  !ids.has(edge.source) &&
                  !ids.has(edge.target) &&
                  !edgeIds.has(edges[index]?.id ?? ""),
              ),
            },
            layout: {
              ...document.layout,
              nodes: Object.fromEntries(
                Object.entries(document.layout.nodes).filter(
                  ([id]) => !ids.has(id),
                ),
              ),
            },
          });
          setSelectedEdges([]);
          return false;
        }}
        deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
        ariaLabelConfig={{
          "node.a11yDescription.default":
            "Press Enter to select a component. Use the inspector to edit parameters and connections.",
        }}
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {feedback && (
        <p className="pl-canvas-feedback" role="status">
          {feedback}
        </p>
      )}
    </div>
  );
}
