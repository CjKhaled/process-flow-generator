// The shape of GET /sessions/{id}, as api/sessions.py builds it. Everything the reader can
// read arrives worded: this page lays it out, and decides none of what it says.

export interface Question {
  id: string;
  turn: number;
  kind: string;
  topic_ids: string[];
  node_ids: string[];
  scope: string;
  text: string;
  subject: string | null;
}

export interface Message {
  role: "user" | "assistant";
  text: string;
  turn: number;
  questions: Question[];
}

export interface ViewNode {
  id: string;
  kind: "start" | "task" | "gateway" | "terminal" | "subprocess";
  label: string;
  lane: string | null;
  status: "stated" | "needs_clarification";
  origin: "source" | "rule" | "slice";
  open_question: boolean;
  from_answer: boolean;
  subprocess_id: string | null;
}

export interface ViewEdge {
  id: string;
  source: string;
  target: string;
  label: string | null;
}

export interface EvidenceLine {
  statement_id: string;
  quote: string;
  statement_text: string;
  restatement: string | null;
  turn: number;
  origin: "initial_description" | "answer";
}

export interface Rationale {
  label: string;
  kind: string;
  lane: string | null;
  status: string;
  origin: string;
  detail: string | null;
  open_question: string | null;
  evidence: EvidenceLine[];
  alternatives: string[];
  notes: string[];
  topics: string[];
  entry: string | null;
  step_count: number | null;
  open_count: number | null;
}

export interface FlowView {
  id: string;
  label: string;
  nodes: ViewNode[];
  edges: ViewEdge[];
  rationale: Record<string, Rationale>;
}

export interface OpenTopic {
  id: string;
  title: string;
  status: string;
  priority: string;
  note: string | null;
}

export interface ScopeCoverage {
  scope: string;
  label: string;
  counts: Record<string, number>;
  total: number;
  open_topics: OpenTopic[];
  complete: boolean;
}

export interface OpenItem {
  key: string;
  scope: string;
  scope_label: string;
  kind: "topic" | "step";
  text: string;
}

export interface Lane {
  name: string;
  persona: string | null;
  description: string;
  status: string;
  default: boolean;
}

export interface FlowOutput {
  flow: string;
  label: string;
  files: string[];
}

export interface SessionState {
  id: string;
  process_id: string;
  process_name: string;
  phase: "describing" | "probing" | "closing" | "complete" | "abandoned";
  focus: string;
  focus_label: string;
  requested_focus: string | null;
  turn: number;
  turn_status: string;
  status_label: string;
  running: boolean;
  flow_updated: boolean;
  notice: string | null;
  transcript: Message[];
  pending: Question[];
  quick_replies: { id: string; label: string }[];
  lanes: Lane[];
  coverage: ScopeCoverage[];
  views: FlowView[];
  open_items: OpenItem[];
  outputs: FlowOutput[];
  outputs_stale: boolean;
  outputs_notice: string | null;
  reopen_notice: string | null;
}

/** One row of GET /sessions: enough to recognise a session without opening it. */
export interface SessionSummary {
  id: string;
  process_name: string;
  title: string;
  turn: number;
  phase: string;
  phase_label: string;
  updated_at: string;
  flows: number;
}

export interface ProcessOption {
  id: string;
  display_name: string;
}
