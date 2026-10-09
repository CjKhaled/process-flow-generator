import { useEffect, useState } from "react";

import type { EvidenceLine, FlowView, SessionState } from "../types";

interface Props {
  state: SessionState;
  view: FlowView | null;
  selected: string | null;
}

// The words for a status are the checklist's own, with the underscores taken out.
const words = (status: string) => status.replace(/_/g, " ");

const said = (line: EvidenceLine) =>
  line.origin === "initial_description" ? "From your description" : `From your answer in turn ${line.turn}`;

export function SidePanel({ state, view, selected }: Props) {
  const [tab, setTab] = useState<"rationale" | "coverage">("coverage");
  const rationale = selected && view ? view.rationale[selected] : undefined;

  // Selecting a step is asking why it is there.
  useEffect(() => {
    if (selected) {
      setTab("rationale");
    }
  }, [selected]);

  return (
    <aside className="side">
      <div className="tabs">
        <button className={tab === "rationale" ? "active" : ""} onClick={() => setTab("rationale")}>
          Step
        </button>
        <button className={tab === "coverage" ? "active" : ""} onClick={() => setTab("coverage")}>
          Coverage
        </button>
      </div>

      {tab === "rationale" && !rationale && <p className="muted pad">Select a step in the flow to see where it came from.</p>}

      {tab === "rationale" && rationale && (
        <div className="pad">
          <p className="eyebrow">
            {words(rationale.kind)}
            {rationale.lane ? ` · ${rationale.lane}` : ""}
          </p>
          <h3>{rationale.label}</h3>

          {rationale.entry && (
            <>
              <h4>Entered when</h4>
              <p>{rationale.entry}</p>
              <p className="muted">
                {rationale.step_count} step{rationale.step_count === 1 ? "" : "s"}, {rationale.open_count} open
              </p>
            </>
          )}

          {rationale.open_question && (
            <>
              <h4>Open question</h4>
              <p className="open">{rationale.open_question}</p>
            </>
          )}

          {rationale.origin === "rule" && (
            <p className="muted">Added to close an outcome that was not stated. Nothing you said supports it yet.</p>
          )}
          {rationale.origin === "slice" && (
            <p className="muted">Added to show where this flow begins or where it hands back.</p>
          )}

          {rationale.evidence.length > 0 && (
            <>
              <h4>In your words</h4>
              {rationale.evidence.map((line, index) => (
                <blockquote key={index}>
                  <q>{line.quote}</q>
                  <span className="tag">{said(line)}</span>
                  {line.statement_text !== line.quote && <span className="context">{line.statement_text}</span>}
                </blockquote>
              ))}
            </>
          )}

          {rationale.detail && !rationale.open_question && (
            <>
              <h4>Detail</h4>
              <p>{rationale.detail}</p>
            </>
          )}

          {rationale.alternatives.length > 0 && (
            <>
              <h4>Alternatives, with no rule given</h4>
              <ul>
                {rationale.alternatives.map((alternative) => (
                  <li key={alternative}>{alternative}</li>
                ))}
              </ul>
            </>
          )}

          {rationale.notes.length > 0 && (
            <>
              <h4>Notes</h4>
              <ul>
                {rationale.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </>
          )}

          {rationale.topics.length > 0 && (
            <>
              <h4>Related topics</h4>
              <ul>
                {rationale.topics.map((topic) => (
                  <li key={topic}>{topic}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {tab === "coverage" && (
        <div className="pad">
          {state.coverage.map((scope) => {
            const settled = scope.total - scope.open_topics.filter((topic) => topic.status !== "deferred").length;
            return (
              <details key={scope.scope} open={scope.scope === state.focus}>
                <summary>
                  <span>{scope.label}</span>
                  <span className="muted">
                    {settled}/{scope.total}
                  </span>
                </summary>
                <div className="progress">
                  <div style={{ width: `${scope.total ? (settled / scope.total) * 100 : 0}%` }} />
                </div>
                <p className="counts">
                  {Object.entries(scope.counts)
                    .map(([status, count]) => `${count} ${words(status)}`)
                    .join(" · ")}
                </p>
                <ul className="topics">
                  {scope.open_topics.map((topic) => (
                    <li key={topic.id} className={topic.priority}>
                      {topic.title}
                      <span className="muted"> {words(topic.status)}</span>
                    </li>
                  ))}
                </ul>
              </details>
            );
          })}

          <h4>Lanes</h4>
          <ul className="topics">
            {state.lanes.map((lane) => (
              <li key={lane.name}>
                {lane.name}
                <span className="muted">
                  {" "}
                  {lane.persona ?? "role not known"}
                  {lane.default ? " · default" : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}
