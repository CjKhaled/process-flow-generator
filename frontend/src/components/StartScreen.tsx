import { useEffect, useState } from "react";

import { listProcesses, listSessions, startSession } from "../api";
import type { ProcessOption, SessionSummary } from "../types";

interface Props {
  onStarted: (sessionId: string) => void;
  onViewKnowledge: (processId: string) => void;
}

export function StartScreen({ onStarted, onViewKnowledge }: Props) {
  const [processes, setProcesses] = useState<ProcessOption[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [processId, setProcessId] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listProcesses()
      .then((found) => {
        setProcesses(found);
        setProcessId((current) => current || found[0]?.id || "");
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "The service could not be reached."),
      );
  }, []);

  // Separate from the process list on purpose: with no earlier sessions, or none readable,
  // the form above is still everything a first visit needs.
  useEffect(() => {
    listSessions()
      .then(setSessions)
      .catch(() => setSessions([]));
  }, []);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const { session_id } = await startSession(processId, description);
      onStarted(session_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The session could not be started.");
      setBusy(false);
    }
  };

  return (
    <main className="start-screen">
      <p className="eyebrow">Process Flow Generator</p>
      <h1>Describe the process</h1>
      <p className="muted">
        Describe how the process runs today. You will be asked a few questions at a time, and the flow is drawn as
        you answer.
      </p>

      <label htmlFor="process">Process</label>
      <select id="process" value={processId} onChange={(event) => setProcessId(event.target.value)}>
        {processes.map((process) => (
          <option key={process.id} value={process.id}>
            {process.display_name}
          </option>
        ))}
      </select>

      <label htmlFor="description">Description</label>
      <textarea
        id="description"
        rows={14}
        value={description}
        placeholder="Paste or write a description of the process, in your own words."
        onChange={(event) => setDescription(event.target.value)}
      />

      {error && <p className="error">{error}</p>}
      <div className="start-actions">
        <button className="accent" disabled={busy || !processId || !description.trim()} onClick={() => void start()}>
          {busy ? "Starting…" : "Start"}
        </button>
        <button disabled={!processId} onClick={() => onViewKnowledge(processId)}>
          View knowledge
        </button>
      </div>

      {sessions.length > 0 && (
        <section className="previous">
          <h2>Previous sessions</h2>
          <ul>
            {sessions.map((session) => (
              <li key={session.id}>
                <button onClick={() => onStarted(session.id)}>
                  <span className="title">{session.title}</span>
                  <span className="meta">
                    <span className={`pill ${session.phase}`}>{session.phase_label}</span>
                    {session.process_name} · turn {session.turn}
                    {session.flows > 0 ? ` · ${session.flows} diagram${session.flows === 1 ? "" : "s"}` : ""} ·{" "}
                    {new Date(session.updated_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
