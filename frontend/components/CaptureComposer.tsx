"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";

export default function CaptureComposer({ onSent }: { onSent: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function sendText() {
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.createText(content);
      setText("");
      onSent();
    } catch (e) {
      setError(e instanceof Error ? e.message : "send failed");
    } finally {
      setBusy(false);
    }
  }

  async function onFile(file: File | undefined) {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.createFile(file);
      onSent();
    } catch (e) {
      setError(e instanceof Error ? e.message : "upload failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="composer">
      <input
        ref={fileRef}
        type="file"
        hidden
        onChange={(e) => onFile(e.target.files?.[0])}
      />
      {error && <div className="composer-error">{error}</div>}
      <div className="composer-row">
        <textarea
          placeholder="Dump a note…"
          value={text}
          rows={2}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendText();
            }
          }}
        />
        <button className="attach" title="Upload document" disabled={busy} onClick={() => fileRef.current?.click()}>
          +
        </button>
        <button className="send" disabled={busy || !text.trim()} onClick={sendText}>
          Send
        </button>
      </div>
    </div>
  );
}