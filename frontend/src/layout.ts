import ELK from "elkjs/lib/elk.bundled.js";

import type { FlowView, ViewNode } from "./types";

// Layered, left to right: the same reading direction as the final BPMN, so the live view
// and the finished diagram tell the story in the same order.
const elk = new ELK();

const OPTIONS = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.layered.spacing.nodeNodeBetweenLayers": "70",
  "elk.spacing.nodeNode": "36",
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  // Keep the order nodes arrive in where the algorithm has a free choice. The service sends
  // them in narrative order, so this is what keeps a re-layout from shuffling the flow.
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
};

/** The box each kind of node occupies. The shape is drawn inside it; the label may sit under it. */
export const SIZES: Record<ViewNode["kind"], { width: number; height: number }> = {
  start: { width: 150, height: 96 },
  terminal: { width: 150, height: 96 },
  task: { width: 190, height: 72 },
  gateway: { width: 170, height: 124 },
  subprocess: { width: 200, height: 84 },
};

export type Positions = Record<string, { x: number; y: number }>;

/** Compute a position for every node of a view. */
export async function layout(view: FlowView): Promise<Positions> {
  const result = await elk.layout({
    id: "root",
    layoutOptions: OPTIONS,
    children: view.nodes.map((node) => ({ id: node.id, ...SIZES[node.kind] })),
    edges: view.edges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  });
  const positions: Positions = {};
  for (const child of result.children ?? []) {
    positions[child.id] = { x: child.x ?? 0, y: child.y ?? 0 };
  }
  return positions;
}
