import { useEffect, useState } from "react";

import { downloadUrl, flowPageUrl } from "../api";
import type { SessionState } from "../types";

interface Props {
  state: SessionState;
  onBack: () => void;
  onNewSession: () => void;
}

/**
 * The finished diagrams, one flow at a time.
 *
 * Each flow is shown in a frame holding stage 3's own page, whole and unchanged. That is
 * deliberate: its Edit mode, its open-questions panel and its zoom all live inside that page,
 * so they work here exactly as they do in the downloaded file, and nothing about them is
 * reimplemented or can drift.
 */
export function DiagramsView({ state, onBack, onNewSession }: Props) {
  const [flow, setFlow] = useState(state.outputs[0]?.flow ?? "main");
  const current = state.outputs.find((output) => output.flow === flow) ?? state.outputs[0];

  // A flow can disappear when the session is finished again without it.
  useEffect(() => {
    if (current && current.flow !== flow) {
      setFlow(current.flow);
    }
  }, [current, flow]);

  if (!current) {
    return null;
  }

  return (
    <div className="diagrams">
      <header className="topbar">
        <strong>{state.process_name}</strong>
        <nav className="flow-tabs">
          {state.outputs.map((output) => (
            <button
              key={output.flow}
              className={output.flow === current.flow ? "active" : ""}
              onClick={() => setFlow(output.flow)}
            >
              {output.label}
            </button>
          ))}
        </nav>
        <span className="downloads">
          {current.files.map((file) => (
            <a key={file} href={downloadUrl(state.id, current.flow, file)} download>
              {file}
            </a>
          ))}
        </span>
        <button onClick={onBack}>Back to requirements</button>
        <button className="link" onClick={onNewSession}>
          New session
        </button>
      </header>
      {state.outputs_notice && <p className="notice">{state.outputs_notice}</p>}
      {/* Keyed by flow, so switching tabs loads a fresh page instead of navigating one frame's history. */}
      <iframe key={current.flow} title={current.label} src={flowPageUrl(state.id, current.flow)} />
    </div>
  );
}
