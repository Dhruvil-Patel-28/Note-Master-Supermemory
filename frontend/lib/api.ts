export type CaptureType = "text" | "voice" | "doc";
export type CaptureStatus = "queued" | "processing" | "indexed" | "failed";

export interface Capture {
  id: number;
  type: CaptureType;
  content: string;
  raw_content_ref: string | null;
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

export interface ChatResponse {
  answer: string;
  found: boolean;
  sources: ChatSource[];
  structured?: StructuredAnswer | null;
  needs_pin?: boolean;
}

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
  createFile: (file: File, documentGroupId?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    const qs = documentGroupId !== undefined ? `?document_group_id=${documentGroupId}` : "";
    return http<Capture>(`/api/captures/file${qs}`, { method: "POST", body: fd });
  },
  createAudio: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return http<Capture>("/api/captures/audio", { method: "POST", body: fd });
  },
  audioUrl: (id: number) => `${BASE}/api/captures/${id}/audio`,
  update: (id: number, content: string) =>
    http<Capture>(`/api/captures/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  remove: (id: number) => http<void>(`/api/captures/${id}`, { method: "DELETE" }),
  history: (groupId: number) => http<Capture[]>(`/api/captures/history/${groupId}`),
  chat: (query: string, includeHistory = false, pinToken?: string | null) =>
    http<ChatResponse>("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(pinToken ? { "X-Pin-Token": pinToken } : {}),
      },
      body: JSON.stringify({ query, include_history: includeHistory }),
    }),
  pinStatus: () => http<{ set: boolean }>("/api/pin/status"),
  pinSet: (pin: string) =>
    http<{ ok: boolean }>("/api/pin/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    }),
  pinVerify: (pin: string) =>
    http<{ token: string }>("/api/pin/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    }),
};