export type CaptureType = "text" | "voice" | "doc";
export type CaptureStatus = "queued" | "processing" | "indexed" | "failed";

export interface Capture {
  id: number;
  type: CaptureType;
  content: string;
  raw_content_ref: string | null;
  original_filename: string | null;
  note: string | null;
  status: CaptureStatus;
  error: string | null;
  sensitivity_tier: "none" | "moderate" | "high";
  document_group_id: number | null;
  version_number: number;
  is_latest: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChatSource {
  capture_id: number;
  snippet: string;
  sensitivity_tier: "none" | "moderate" | "high";
}

export interface StructuredField {
  key: string;
  value: string;
}

export interface StructuredAnswer {
  kind: "fields" | "prose";
  fields: StructuredField[];
}

export interface ShowDocument {
  capture_id: number;
  filename: string | null;
}

export interface ChatResponse {
  answer: string;
  found: boolean;
  sources: ChatSource[];
  structured?: StructuredAnswer | null;
  show_document?: ShowDocument | null;
}

export interface AuditEntry {
  id: number;
  query: string | null;
  retrieved_source_ids: string | null;
  sensitive_access: boolean;
  created_at: string;
}

export interface HealthStatus {
  status: "ok" | "degraded";
  database: boolean;
  ollama: boolean;
}

export type FeedbackKind = "wrong" | "missing" | "off_topic" | "other";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? ""; // empty → same-origin /api via Next rewrite

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // keep statusText
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  listCaptures: () => http<Capture[]>("/api/captures"),
  createText: (content: string) =>
    http<Capture>("/api/captures/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  createFile: (file: File, note?: string, documentGroupId?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    if (note) fd.append("note", note);
    const qs = documentGroupId !== undefined ? `?document_group_id=${documentGroupId}` : "";
    return http<Capture>(`/api/captures/file${qs}`, { method: "POST", body: fd });
  },
  createAudio: (file: File, note?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (note) fd.append("note", note);
    return http<Capture>("/api/captures/audio", { method: "POST", body: fd });
  },
  audioUrl: (id: number) => `${BASE}/api/captures/${id}/audio`,
  fileUrl: (id: number) => `${BASE}/api/captures/${id}/file`,
  update: (id: number, content: string, note?: string) =>
    http<Capture>(`/api/captures/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, ...(note !== undefined ? { note } : {}) }),
    }),
  updateNote: (id: number, note: string) =>
    http<Capture>(`/api/captures/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    }),
  remove: (id: number) => http<void>(`/api/captures/${id}`, { method: "DELETE" }),
  history: (groupId: number) => http<Capture[]>(`/api/captures/history/${groupId}`),
  chat: (query: string, includeHistory = false) =>
    http<ChatResponse>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, include_history: includeHistory }),
    }),
  health: () => http<HealthStatus>("/api/health"),
  audit: (limit = 100) => http<AuditEntry[]>(`/api/audit?limit=${limit}`),
  restore: (id: number) =>
    http<Capture>(`/api/captures/${id}/restore`, { method: "POST" }),
  submitFeedback: (payload: {
    query: string;
    capture_ids: number[];
    kind: FeedbackKind;
    note: string;
  }) =>
    http<{ ok: boolean }>("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
};