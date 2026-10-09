import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import type { ViewNode } from "../types";

export interface FlowNodeData extends Record<string, unknown> {
  node: ViewNode;
  onOpen: (subprocessId: string) => void;
}

export type FlowNodeType = Node<FlowNodeData, "flow">;

type Status = "needs-input" | "inferred" | "from-you";

/**
 * Where a step stands, which decides its border and its pill.
 *
 * Three states that differ in border style and lightness as well as hue, so they can be told
 * apart in grayscale: waiting on the user (solid orange, and the only one that tints the
 * card), put there by the tool to complete a flow (dashed grey), or backed by the user's own
 * words (solid green).
 */
function statusOf(node: ViewNode): Status {
  if (node.open_question) {
    return "needs-input";
  }
  return node.origin === "source" ? "from-you" : "inferred";
}

const STATUS_WORDS: Record<Status, string> = {
  "needs-input": "Needs your input",
  inferred: "Inferred",
  "from-you": "From you",
};

const KIND_WORDS: Record<ViewNode["kind"], string> = {
  start: "Start",
  task: "Step",
  gateway: "Decision",
  terminal: "End",
  subprocess: "Subprocess",
};

/** One shape of the live view. The kind decides the shape; the status decides how it is outlined. */
export function FlowNode({ data, selected }: NodeProps<FlowNodeType>) {
  const { node, onOpen } = data;
  const status = statusOf(node);
  const card = node.kind === "task" || node.kind === "subprocess";
  const classes = ["node", node.kind, status, selected ? "selected" : ""].join(" ");

  return (
    <div className={classes} title={`${KIND_WORDS[node.kind]} · ${STATUS_WORDS[status]}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="shape">
        {node.from_answer && <span className="marker" title="Includes something from one of your answers" />}
        {card && (
          <>
            <div className="card-head">
              <span className="kind">{KIND_WORDS[node.kind]}</span>
              <span className="pill">{STATUS_WORDS[status]}</span>
            </div>
            <span className="label">{node.label}</span>
          </>
        )}
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
      {!card && <span className="label under">{node.label}</span>}
      {node.lane && <span className="lane">{node.lane}</span>}
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}
