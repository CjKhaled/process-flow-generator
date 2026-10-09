import { useEffect, useState } from "react";

import { listProcesses, startSession } from "../api";
import type { ProcessOption } from "../types";

interface Props {
  onStarted: (sessionId: string) => void;
}

export function StartScreen({ onStarted }: Props) {
  const [processes, setProcesses] = useState<ProcessOption[]>([]);
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
      <h1>Process Flow Generator</h1>
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
      <button className="primary" disabled={busy || !processId || !description.trim()} onClick={() => void start()}>
        {busy ? "Starting…" : "Start"}
      </button>
    </main>
  );
}
