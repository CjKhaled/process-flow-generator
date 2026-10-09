import { downloadUrl } from "../api";
import type { OpenItem, SessionState } from "../types";

interface Props {
  state: SessionState;
  busy: boolean;
  onAnswer: (item: OpenItem) => void;
  onAccept: () => void;
}

/** What is still open, grouped by flow; and once the session is finished, the files to download. */
export function CloseOut({ state, busy, onAnswer, onAccept }: Props) {
  if (state.phase === "complete") {
    return (
      <div className="closeout">
        <h3>Finished</h3>
        {state.outputs.map((output) => (
          <div key={output.flow} className="download-row">
            <span>{output.label}</span>
            {output.files.map((file) => (
              <a key={file} href={downloadUrl(state.id, output.flow, file)} download>
                {file}
              </a>
            ))}
          </div>
        ))}
      </div>
    );
  }

  const flows = [...new Set(state.open_items.map((item) => item.scope))];

  return (
    <div className="closeout">
      <h3>Still open</h3>
      <button className="primary" disabled={busy} onClick={onAccept}>
        Accept and finish
      </button>
      {state.open_items.length === 0 && <p className="muted">Nothing is open.</p>}
      {flows.map((scope) => {
        const items = state.open_items.filter((item) => item.scope === scope);
        return (
          <div key={scope}>
            <h4>{items[0].scope_label}</h4>
            <ul>
              {items.map((item) => (
                <li key={item.key}>
                  <span>{item.text}</span>
                  <button className="link" disabled={busy} onClick={() => onAnswer(item)}>
                    Answer
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
