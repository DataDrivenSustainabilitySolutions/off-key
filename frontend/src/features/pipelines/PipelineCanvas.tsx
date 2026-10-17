import { useMemo, useRef, useState, type DragEvent } from "react";
import {
  Background,
  Controls,
  ControlButton,
  ReactFlow,
  applyNodeChanges,
  type ReactFlowInstance,
} from "@xyflow/react";
import { LocateFixed } from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import type { PipelineComponent, PipelineValidation } from "./contracts";
import { connectNodes, connectionIssue, type GraphDocument } from "./model";
import { edgeId } from "./semantics";
import { presentGraph } from "./graphPresentation";
import { PipelineNodeCard, type CanvasNode } from "./PipelineNodeCard";
import { PipelineLegend } from "./PipelineLegend";
import "@xyflow/react/dist/style.css";

const nodeTypes = { component: PipelineNodeCard };
type Props = {
  document: GraphDocument;
  components: PipelineComponent[];
  selected?: string;
  readOnly?: boolean;
  layoutEditable?: boolean;
  states?: Record<string, string>;
  mode?: "design" | "run";
  issues?: PipelineValidation["issues"];
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
  mode = "design",
  issues,
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
  const graph = useMemo(
    () => presentGraph(document, components, states, issues),
    [document, components, states, issues],
  );
  const nodes = useMemo(
    () =>
      graph.nodes.map((node) => ({ ...node, selected: node.id === selected })),
    [graph.nodes, selected],
  );
  const edges = useMemo(
    () =>
      graph.edges.map((edge) => ({
        ...edge,
        selectable: !readOnly,
        selected: selectedEdges.includes(edge.id),
      })),
    [graph.edges, readOnly, selectedEdges],
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
      <PipelineLegend
        kinds={graph.kinds}
        running={mode === "run"}
        hasRuntimeState={!!states}
      />
      <div className="pl-flow-surface">
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
          isValidConnection={(connection) =>
            !readOnly &&
            !connectionIssue(
              document.definition,
              connection.source,
              connection.target,
              components,
            )
          }
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
            const issue = connectionIssue(
              document.definition,
              connection.source,
              connection.target,
              components,
            );
            if (issue) {
              setFeedback(issue);
              return;
            }
            const definition = connectNodes(
              document.definition,
              connection.source,
              connection.target,
              components,
            );
            setFeedback("");
            onChange({ ...document, definition });
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
                  (edge) =>
                    !ids.has(edge.source) &&
                    !ids.has(edge.target) &&
                    !edgeIds.has(edgeId(edge)),
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
          <Controls showInteractive={false}>
            <ControlButton
              aria-label="Locate selected component"
              title="Locate selected component"
              disabled={!selected || !flow}
              onClick={() => {
                if (selected)
                  void flow?.fitView({
                    nodes: [{ id: selected }],
                    minZoom: 0.8,
                    maxZoom: 1,
                    padding: 0.5,
                  });
              }}
            >
              <LocateFixed size={16} />
            </ControlButton>
          </Controls>
        </ReactFlow>
      </div>
      {feedback && (
        <p className="pl-canvas-feedback" role="status">
          {feedback}
        </p>
      )}
    </div>
  );
}
