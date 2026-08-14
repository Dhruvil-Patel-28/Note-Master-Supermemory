"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";

export default function CaptureComposer({ onSent }: { onSent: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

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

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError("microphone not available in this browser");
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        setRecording(false);
        setBusy(true);
        try {
          await api.createAudio(
            new File([blob], `voice-${Date.now()}.webm`, { type: blob.type })
          );
          onSent();
        } catch (e) {
          setError(e instanceof Error ? e.message : "upload failed");
        } finally {
          setBusy(false);
        }
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "microphone unavailable");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
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
        <button
          className={`mic ${recording ? "recording" : ""}`}
          title={recording ? "Stop recording" : "Record voice note"}
          disabled={busy}
          onClick={recording ? stopRecording : startRecording}
        >
          {recording ? "■" : "🎤"}
        </button>
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