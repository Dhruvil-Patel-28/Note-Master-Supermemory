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
}

export interface ChatResponse {
  answer: string;
  found: boolean;
  sources: ChatSource[];
}

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  listCaptures: () => http<Capture[]>("/captures"),
  createText: (content: string) =>
    http<Capture>("/captures/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  createFile: (file: File, documentGroupId?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    const qs = documentGroupId !== undefined ? `?document_group_id=${documentGroupId}` : "";
    return http<Capture>(`/captures/file${qs}`, { method: "POST", body: fd });
  },
  update: (id: number, content: string) =>
    http<Capture>(`/captures/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  remove: (id: number) => http<void>(`/captures/${id}`, { method: "DELETE" }),
  history: (groupId: number) => http<Capture[]>(`/captures/history/${groupId}`),
  chat: (query: string, includeHistory = false) =>
    http<ChatResponse>("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, include_history: includeHistory }),
    }),
};