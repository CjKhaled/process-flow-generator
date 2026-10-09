import type { ProcessOption, SessionState, SessionSummary } from "./types";

// Empty means same origin, which is how the built page is served. Set VITE_API_BASE to point
// a development build at a service running somewhere else.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

/** A refusal from the service, carrying the sentence it gave. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((data: { detail?: unknown }) => (typeof data.detail === "string" ? data.detail : null))
      .catch(() => null);
    throw new ApiError(detail ?? `The service answered ${response.status}.`, response.status);
  }
  return (await response.json()) as T;
}

export const listProcesses = () => request<ProcessOption[]>("/processes");

export const listSessions = () => request<SessionSummary[]>("/sessions");

export const startSession = (processId: string, description: string) =>
  request<{ session_id: string }>("/sessions", { process_id: processId, description });

export const getSession = (id: string) => request<SessionState>(`/sessions/${id}`);

export interface Answer {
  text?: string;
  quick_reply?: string | null;
  question_id?: string | null;
  item_key?: string | null;
}

export const sendMessage = (id: string, answer: Answer) => request<unknown>(`/sessions/${id}/messages`, answer);

export const setFocus = (id: string, focus: string) => request<unknown>(`/sessions/${id}/focus`, { focus });

export const closeSession = (id: string) => request<unknown>(`/sessions/${id}/close`, {});

export const acceptSession = (id: string) => request<unknown>(`/sessions/${id}/accept`, {});

/** A finished flow's page, to be shown in a frame; the download URL serves the same file to be saved. */
export const flowPageUrl = (id: string, flow: string) => `${BASE}/sessions/${id}/flows/${flow}/page`;

export const downloadUrl = (id: string, flow: string, file: string) => `${BASE}/sessions/${id}/outputs/${flow}/${file}`;
