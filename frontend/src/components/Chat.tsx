import { useEffect, useRef, useState } from "react";

import { acceptSession, closeSession, sendMessage, type Answer } from "../api";
import type { OpenItem, SessionState } from "../types";
import { CloseOut } from "./CloseOut";

interface Props {
  state: SessionState;
  /** Called after anything that starts work on the server, so the page begins polling. */
  onChanged: () => void;
  onViewDiagrams: () => void;
}

export function Chat({ state, onChanged, onViewDiagrams }: Props) {
  const [draft, setDraft] = useState("");
  const [questionId, setQuestionId] = useState<string | null>(null);
  const [answering, setAnswering] = useState<OpenItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const finished = state.phase === "complete";
  const busy = state.running;
  const failed = state.turn_status === "failed";

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [state.transcript.length, state.running]);

  // A chosen question that is no longer pending belongs to a turn that has passed.
  useEffect(() => {
    if (questionId && !state.pending.some((question) => question.id === questionId)) {
      setQuestionId(null);
    }
  }, [state.pending, questionId]);

  const act = async (work: () => Promise<unknown>) => {
    setError(null);
    try {
      await work();
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That could not be sent.");
    }
  };

  const send = (answer: Answer) =>
    act(async () => {
      await sendMessage(state.id, { question_id: questionId, item_key: answering?.key ?? null, ...answer });
      setDraft("");
      setQuestionId(null);
      setAnswering(null);
    });

  const lastAssistant = [...state.transcript].reverse().find((message) => message.role === "assistant");

  return (
    <section className="chat">
      <div className="transcript">
        {state.transcript.map((message, index) => (
          <div key={index} className={`bubble ${message.role}`}>
            {message.text}
            {message === lastAssistant && state.pending.length > 0 && (
              <ol className="questions">
                {state.pending.map((question) => (
                  <li
                    key={question.id}
                    className={question.id === questionId ? "chosen" : undefined}
                    title="Click to answer this question in particular"
                    onClick={() => {
                      setQuestionId(question.id === questionId ? null : question.id);
                      input.current?.focus();
                    }}
                  >
                    {question.text}
                  </li>
                ))}
              </ol>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>

      {(state.phase === "closing" || finished) && (
        <CloseOut
          state={state}
          busy={busy}
          onAnswer={(item) => {
            setAnswering(item);
            input.current?.focus();
          }}
          onAccept={() => void act(() => acceptSession(state.id))}
          onViewDiagrams={onViewDiagrams}
        />
      )}

      {state.notice && !busy && <p className="notice">{state.notice}</p>}
      {(busy || failed) && state.status_label && (
        <p className={failed ? "error" : "status"}>{state.status_label}</p>
      )}
      {error && <p className="error">{error}</p>}

      {state.reopen_notice && !busy && <p className="notice">{state.reopen_notice}</p>}

      <div className="composer">
        <div className="focus-line">
          Now discussing: <strong>{state.focus_label}</strong>
          {state.requested_focus && state.requested_focus !== state.focus && (
            <span className="muted"> (moving to the flow you opened on your next answer)</span>
          )}
        </div>
        {answering && (
          <div className="answering">
            Answering: {answering.text}
            <button className="link" onClick={() => setAnswering(null)}>
              cancel
            </button>
          </div>
        )}
        <textarea
          ref={input}
          rows={3}
          value={draft}
          disabled={busy}
          placeholder={busy ? "" : "Type your answer. Enter sends; Shift+Enter starts a new line."}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && draft.trim() && !busy) {
              event.preventDefault();
              void send({ text: draft });
            }
          }}
        />
        <div className="actions">
          <button className="primary" disabled={busy || !draft.trim()} onClick={() => void send({ text: draft })}>
            Send
          </button>
          {state.quick_replies.map((reply) => (
            <button key={reply.id} disabled={busy || state.turn === 0} onClick={() => void send({ quick_reply: reply.id })}>
              {reply.label}
            </button>
          ))}
          {state.phase !== "closing" && !finished && (
            <button
              className="finish"
              disabled={busy || state.turn === 0}
              onClick={() => void act(() => closeSession(state.id))}
            >
              Finish
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
