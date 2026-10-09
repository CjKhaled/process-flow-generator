import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, getSession, setFocus } from "./api";
import { Chat } from "./components/Chat";
import { FlowCanvas } from "./components/FlowCanvas";
import { SidePanel } from "./components/SidePanel";
import { StartScreen } from "./components/StartScreen";
import type { SessionState } from "./types";

const POLL_MS = 1500;

/** The session id lives in the URL fragment, so a reload returns to the same conversation. */
function sessionFromUrl(): string | null {
  return window.location.hash.replace(/^#/, "") || null;
}

export function App() {
  const [sessionId, setSessionId] = useState<string | null>(sessionFromUrl);
  const [state, setState] = useState<SessionState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("main");
  const [selected, setSelected] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async (id: string) => {
    try {
      const next = await getSession(id);
      setState(next);
      setError(null);
      return next;
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) {
        // A session that no longer exists: back to the start, not a page that polls for ever.
        window.location.hash = "";
        setSessionId(null);
        setState(null);
        return null;
      }
      setError(caught instanceof Error ? caught.message : "The service could not be reached.");
      return null;
    }
  }, []);

  // Poll only while a turn is running. Each poll schedules the next one, so a slow response
  // never overlaps the one after it, and the loop simply ends when the turn does.
  const watch = useCallback(
    (id: string) => {
      window.clearTimeout(timer.current);
      const tick = async () => {
        const next = await refresh(id);
        if (next === null || next.running) {
          timer.current = window.setTimeout(tick, POLL_MS);
        }
      };
      void tick();
    },
    [refresh],
  );

  useEffect(() => {
    if (sessionId) {
      watch(sessionId);
    }
    return () => window.clearTimeout(timer.current);
  }, [sessionId, watch]);

  // A tab can disappear between payloads (a correction removed a subprocess's only steps).
  useEffect(() => {
    if (state && !state.views.some((view) => view.id === tab)) {
      setTab("main");
    }
  }, [state, tab]);

  if (!sessionId) {
    return (
      <StartScreen
        onStarted={(id) => {
          window.location.hash = id;
          setSessionId(id);
        }}
      />
    );
  }

  if (!state) {
    return <div className="loading">{error ?? "Loading the session…"}</div>;
  }

  const view = state.views.find((candidate) => candidate.id === tab) ?? state.views[0] ?? null;

  const openFlow = (flowId: string) => {
    setTab(flowId);
    setSelected(null);
    // Tell the conversation where the user went, so the next questions follow them.
    if (state.phase !== "complete" && !state.running) {
      void setFocus(state.id, flowId)
        .then(() => refresh(state.id))
        .catch(() => undefined);
    }
  };

  return (
    <div className="workspace">
      <header className="topbar">
        <strong>{state.process_name}</strong>
        <span className="muted">Turn {state.turn}</span>
        {error && <span className="error-inline">{error}</span>}
        <button
          className="link"
          onClick={() => {
            window.location.hash = "";
            setSessionId(null);
            setState(null);
          }}
        >
          New session
        </button>
      </header>
      <Chat state={state} onChanged={() => watch(state.id)} />
      <FlowCanvas
        views={state.views}
        view={view}
        tab={view?.id ?? "main"}
        selected={selected}
        onTab={openFlow}
        onSelect={setSelected}
      />
      <SidePanel state={state} view={view} selected={selected} />
    </div>
  );
}
