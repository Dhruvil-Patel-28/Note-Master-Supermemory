"use client";

import { useRef, useState } from "react";
import { Paperclip, Send, Square, Mic } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export default function CaptureComposer({ onSent }: { onSent: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function sendText() {
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    try {
      await api.createText(content);
      setText("");
      toast.success("Note captured");
      onSent();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  async function sendFile(file: File) {
    if (busy) return;
    setBusy(true);
    const isAudio = file.type.startsWith("audio/");
    try {
      if (isAudio) {
        await api.createAudio(file);
        toast.success("Voice note uploaded — transcribing…");
      } else {
        await api.createFile(file);
        toast.success(`Uploading ${file.name}…`);
      }
      onSent();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      toast.error("Microphone not available in this browser");
      return;
    }
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
          toast.success("Voice note uploaded — transcribing…");
          onSent();
        } catch (e) {
          toast.error(e instanceof Error ? e.message : "Upload failed");
        } finally {
          setBusy(false);
        }
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
      toast.info("Recording… tap stop when done");
    } catch {
      toast.error("Microphone unavailable");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
  }

  return (
    <div
      className={cn(
        "space-y-2 border-t bg-background p-3 transition-colors",
        dragOver && "border-t-2 border-primary"
      )}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const file = e.dataTransfer.files?.[0];
        if (file) sendFile(file);
      }}
    >
      <input
        ref={fileRef}
        type="file"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) sendFile(f);
          if (fileRef.current) fileRef.current.value = "";
        }}
      />
      {dragOver && (
        <p className="rounded-md border border-dashed border-primary px-3 py-2 text-center text-xs text-primary">
          Drop to upload
        </p>
      )}
      <Textarea
        placeholder="Dump a note… (drag & drop a file, or record)"
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
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          title="Upload document"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          <Paperclip />
          <span className="sr-only">Upload document</span>
        </Button>
        <Button
          variant={recording ? "destructive" : "ghost"}
          size="icon"
          title={recording ? "Stop recording" : "Record voice note"}
          disabled={busy}
          onClick={recording ? stopRecording : startRecording}
          className={cn(recording && "animate-pulse")}
        >
          {recording ? <Square /> : <Mic />}
          <span className="sr-only">{recording ? "Stop recording" : "Record voice note"}</span>
        </Button>
        <Button
          className="ml-auto"
          size="sm"
          disabled={busy || !text.trim()}
          onClick={sendText}
        >
          <Send />
          Send
        </Button>
      </div>
    </div>
  );
}