import { useEffect, useRef, useState } from "react";

import { getKnowledge } from "../api";
import type { Knowledge } from "../types";

interface Props {
  processId: string;
  onBack: () => void;
}

/**
 * Everything the tool knows about a process, to read.
 *
 * A list of pages on the left and one page on the right. The pages arrive as finished HTML
 * from the service, which is where the knowledge files are turned into prose, so this
 * component lays them out and decides nothing about what they say.
 */
export function KnowledgeView({ processId, onBack }: Props) {
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const page = useRef<HTMLElement>(null);

  useEffect(() => {
    getKnowledge(processId)
      .then((loaded) => {
        setKnowledge(loaded);
        setCurrent(loaded.sections[0]?.id ?? null);
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "The knowledge could not be loaded."));
  }, [processId]);

  // A new page starts at its top, not wherever the last one was left.
  useEffect(() => {
    page.current?.scrollTo({ top: 0 });
  }, [current]);

  const section = knowledge?.sections.find((candidate) => candidate.id === current);
  const groups = [...new Set(knowledge?.sections.map((candidate) => candidate.group) ?? [])];

  return (
    <div className="knowledge">
      <header className="topbar">
        <strong>{knowledge?.process_name ?? "Knowledge"}</strong>
        <span className="muted">What the tool knows</span>
        <span className="spacer" />
        <button onClick={onBack}>Back</button>
      </header>
      <nav className="knowledge-nav">
        {groups.map((group) => (
          <div key={group}>
            <p className="eyebrow">{group}</p>
            {knowledge?.sections
              .filter((candidate) => candidate.group === group)
              .map((candidate) => (
                <button
                  key={candidate.id}
                  className={candidate.id === current ? "active" : ""}
                  onClick={() => setCurrent(candidate.id)}
                >
                  {candidate.title}
                </button>
              ))}
          </div>
        ))}
      </nav>
      <main className="knowledge-page" ref={page}>
        {error && <p className="error">{error}</p>}
        {!knowledge && !error && <p className="muted">Loading…</p>}
        {section && <article className="prose" dangerouslySetInnerHTML={{ __html: section.html }} />}
      </main>
    </div>
  );
}
