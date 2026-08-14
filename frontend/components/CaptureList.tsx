"use client";

import { useEffect, useState } from "react";
import { api, Capture } from "@/lib/api";

const STATUS_LABEL: Record<Capture["status"], string> = {
  queued: "queued",
  processing: "processing…",
  indexed: "indexed",
  failed: "failed",
};

function CaptureItem({
  cap,
  onChanged,
}: {
  cap: Capture;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(cap.content);
  const [history, setHistory] = useState<Capture[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!draft.trim() || busy) return;
    setBusy(true);
    try {
      await api.update(cap.id, draft);
      setEditing(false);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (busy || !confirm(`Delete capture ${cap.id}?`)) return;
    setBusy(true);
    try {
      await api.remove(cap.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function toggleHistory() {
    if (history) {
      setHistory(null);
      return;
    }
    if (cap.document_group_id === null) return;
    setHistory(await api.history(cap.document_group_id));
  }

  return (
    <li className={`capture-item status-${cap.status}`}>
      <div className="capture-meta">
        <span className={`badge type-${cap.type}`}>{cap.type}</span>
        {cap.version_number > 1 && (
          <button className="badge version" title="Versions" onClick={toggleHistory}>
            v{cap.version_number}
          </button>
        )}
        <span className={`badge status`}>{STATUS_LABEL[cap.status]}</span>
        {!cap.is_latest && <span className="badge old">old</span>}
      </div>
      {editing ? (
        <textarea value={draft} rows={3} onChange={(e) => setDraft(e.target.value)} />
      ) : (
        <p className="capture-content">
          {cap.type === "doc" ? `📄 ${cap.content.slice(0, 200)}` : cap.content}
        </p>
      )}
      {cap.status === "failed" && cap.error && (
        <p className="capture-error">{cap.error}</p>
      )}
      {history && (
        <ul className="capture-history">
          {history.map((h) => (
            <li key={h.id}>
              v{h.version_number} · {h.content.slice(0, 80)}
            </li>
          ))}
        </ul>
      )}
      <div className="capture-actions">
        {editing ? (
          <>
            <button onClick={save} disabled={busy}>Save</button>
            <button onClick={() => setEditing(false)}>Cancel</button>
          </>
        ) : (
          <>
            <button onClick={() => setEditing(true)}>Edit</button>
            <button className="danger" onClick={remove} disabled={busy}>Delete</button>
          </>
        )}
      </div>
    </li>
  );
}

export default function CaptureList({
  captures,
  onChanged,
}: {
  captures: Capture[];
  onChanged: () => void;
}) {
  useEffect(() => {
    if (!captures.some((c) => c.status === "queued" || c.status === "processing")) return;
    const t = setInterval(onChanged, 1500);
    return () => clearInterval(t);
  }, [captures, onChanged]);

  if (captures.length === 0) {
    return <p className="empty">Nothing captured yet. Dump a note on the left.</p>;
  }
  return (
    <ul className="capture-list">
      {captures.map((c) => (
        <CaptureItem key={c.id} cap={c} onChanged={onChanged} />
      ))}
    </ul>
  );
}