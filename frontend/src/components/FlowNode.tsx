import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import type { ViewNode } from "../types";

export interface FlowNodeData extends Record<string, unknown> {
  node: ViewNode;
  onOpen: (subprocessId: string) => void;
}

export type FlowNodeType = Node<FlowNodeData, "flow">;

/** One shape of the live view. The kind decides the shape; everything else is the same for all of them. */
export function FlowNode({ data, selected }: NodeProps<FlowNodeType>) {
  const { node, onOpen } = data;
  const classes = ["node", node.kind, node.open_question ? "open" : "", selected ? "selected" : ""].join(" ");
  const below = node.kind === "start" || node.kind === "terminal" || node.kind === "gateway";

  return (
    <div className={classes}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="shape">
        {node.from_answer && <span className="marker" title="Includes something from one of your answers" />}
        {!below && <span className="label">{node.label}</span>}
        {node.kind === "gateway" && <span className="glyph">?</span>}
        {node.kind === "subprocess" && node.subprocess_id && (
          <button
            className="open-flow nodrag"
            onClick={(event) => {
              event.stopPropagation();
              onOpen(node.subprocess_id!);
            }}
          >
            Open
          </button>
        )}
      </div>
      {below && <span className="label under">{node.label}</span>}
      {node.lane && <span className="lane">{node.lane}</span>}
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}
