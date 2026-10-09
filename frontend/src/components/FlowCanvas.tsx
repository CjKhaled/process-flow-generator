import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useReactFlow,
  type Edge,
} from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { layout, SIZES, type Positions } from "../layout";
import type { FlowView } from "../types";
import { FlowNode, type FlowNodeType } from "./FlowNode";

interface Props {
  views: FlowView[];
  view: FlowView | null;
  tab: string;
  selected: string | null;
  onTab: (flowId: string) => void;
  onSelect: (nodeId: string | null) => void;
}

const nodeTypes = { flow: FlowNode };

/** How many steps the first view of a flow fits to. */
const OPENING_NODES = 6;

export function FlowCanvas(props: Props) {
  return (
    <section className="flow">
      <div className="tabs">
        {props.views.map((view) => (
          <button key={view.id} className={view.id === props.tab ? "active" : ""} onClick={() => props.onTab(view.id)}>
            {view.label}
            {view.nodes.some((node) => node.open_question) && <span className="dot" title="Has an open question" />}
          </button>
        ))}
      </div>
      {props.view ? (
        <ReactFlowProvider>
          <Canvas {...props} view={props.view} />
        </ReactFlowProvider>
      ) : (
        <p className="muted pad">The flow will appear here once your description has been read.</p>
      )}
    </section>
  );
}

function Canvas({ view, selected, onTab, onSelect }: Props & { view: FlowView }) {
  const [positions, setPositions] = useState<Positions>({});
  const [laidOut, setLaidOut] = useState<string | null>(null);
  const fitted = useRef<string | null>(null);
  const { fitView } = useReactFlow();

  // Lay out again whenever the flow changes shape. The signature leaves labels out on
  // purpose: a reworded step should not move the diagram.
  const signature = useMemo(
    () =>
      [view.id, ...view.nodes.map((node) => `${node.id}:${node.kind}`), ...view.edges.map((e) => `${e.source}>${e.target}`)].join(
        "|",
      ),
    [view],
  );

  useEffect(() => {
    let current = true;
    void layout(view).then((next) => {
      if (current) {
        setPositions(next);
        setLaidOut(signature);
      }
    });
    return () => {
      current = false;
    };
    // The signature stands for the view: re-running on every new payload object would
    // re-layout a flow that has not changed.
  }, [signature]);

  // Fit once per tab, and never again while the user is looking at it: an answer that adds
  // a step should not throw away where they had panned to. Waiting for the nodes to be
  // measured matters -- fitting before that fits to nothing.
  const measured = useNodesInitialized();
  useEffect(() => {
    if (measured && laidOut === signature && fitted.current !== view.id) {
      fitted.current = view.id;
      // The opening steps, not the whole flow: a long process fitted whole is too small to
      // read, and the start is where a reader begins. The rest is a pan away.
      const opening = view.nodes.slice(0, OPENING_NODES).map((node) => ({ id: node.id }));
      void fitView({ nodes: opening, padding: 0.12, maxZoom: 1, duration: 200 });
    }
  }, [measured, laidOut, signature, view.id, view.nodes, fitView]);

  const nodes: FlowNodeType[] = useMemo(
    () =>
      view.nodes
        .filter((node) => positions[node.id])
        .map((node) => ({
          id: node.id,
          type: "flow" as const,
          position: positions[node.id],
          data: { node, onOpen: onTab },
          selected: node.id === selected,
          draggable: false,
          connectable: false,
          ...SIZES[node.kind],
        })),
    [view.nodes, positions, selected, onTab],
  );

  const edges: Edge[] = useMemo(
    () =>
      view.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label ?? undefined,
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed },
        selectable: false,
      })),
    [view.edges],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      elementsSelectable
      minZoom={0.2}
      proOptions={{ hideAttribution: false }}
      onNodeClick={(_, node) => onSelect(node.id)}
      onPaneClick={() => onSelect(null)}
    >
      <Background />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
