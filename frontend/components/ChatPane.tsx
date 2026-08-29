"use client";

import { useEffect, useRef, useState } from "react";
import {
  Copy,
  Check,
  ExternalLink,
  FileText,
  Flag,
  RotateCw,
  Send,
  ShieldAlert,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { api, Artifact, Capture, ChatResponse, ChatSource, ShowDocument } from "@/lib/api";
import Markdown from "@/components/markdown";
import ArtifactPanel from "@/components/ArtifactPanel";
import FeedbackDialog from "@/components/feedback-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant" | "error";
  text: string;
  query?: string;
  found?: boolean;
  sources?: ChatResponse["sources"];
  structured?: ChatResponse["structured"];
  sensitive?: boolean;
  artifact?: Artifact;
}

function newMessageId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `m-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// Retrieval returns per-chunk sources (up to 3 chunks per capture) — citations
// should show each capture once.
function dedupeSources(sources: ChatResponse["sources"]): ChatResponse["sources"] {
  const seen = new Set<number>();
  return sources.filter((s) => {
    if (seen.has(s.capture_id)) return false;
    seen.add(s.capture_id);
    return true;
  });
}

function SourceChip({
  s,
  hasFile,
  onClick,
  onOpenFile,
}: {
  s: ChatSource;
  hasFile?: boolean;
  onClick: () => void;
  onOpenFile?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={s.snippet.replace(/<[^>]+>/g, "")}
      className={cn(
        "group inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors hover:bg-muted",
        s.sensitivity_tier === "high" &&
          "border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/20",
        s.sensitivity_tier === "moderate" &&
          "border-yellow-500/40 bg-yellow-500/10 text-yellow-600 hover:bg-yellow-500/20 dark:text-yellow-400",
        s.sensitivity_tier === "none" &&
          "border-primary/30 bg-primary/10 text-primary hover:bg-primary/20"
      )}
    >
      {s.sensitivity_tier === "high" && <ShieldAlert className="size-3" />}
      {s.sensitivity_tier === "moderate" && <TriangleAlert className="size-3" />}
      capture #{s.capture_id}
      {hasFile && (
        <span
          role="button"
          title="Open original document"
          onClick={(e) => {
            e.stopPropagation();
            onOpenFile?.();
          }}
          className="ml-0.5 rounded-full p-0.5 opacity-60 transition-opacity hover:bg-foreground/10 hover:opacity-100"
        >
          <ExternalLink className="size-3" />
        </span>
      )}
    </button>
  );
}

function FieldCard({ fields }: { fields: { key: string; value: string }[] }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    const text = fields.map((f) => `${f.key}: ${f.value}`).join("\n");
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <div className="mt-2 overflow-hidden rounded-lg border">
      <Table>
        <TableBody>
          {fields.map((f, i) => (
            <TableRow key={i}>
              <TableCell className="w-1/3 whitespace-nowrap align-top font-medium text-muted-foreground">
                {f.key}
              </TableCell>
              <TableCell className="break-words">{f.value}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="flex justify-end border-t bg-muted/40 p-1.5">
        <Button variant="ghost" size="xs" onClick={copy}>
          {copied ? <Check className="mr-1 size-3" /> : <Copy className="mr-1 size-3" />}
          {copied ? "Copied" : "Copy fields"}
        </Button>
      </div>
    </div>
  );
}

function AssistantMessage({
  m,
  captures,
  onSourceClick,
  onOpenFile,
  onFlag,
}: {
  m: Message;
  captures: Capture[];
  onSourceClick: (id: number) => void;
  onOpenFile: (id: number) => void;
  onFlag: (m: Message) => void;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(m.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <div className="flex max-w-[85%] flex-col gap-1 self-start">
      <div className="flex items-center gap-1 text-muted-foreground">
        <Sparkles className="size-3.5" />
        <span className="text-xs font-medium">Note Master</span>
      </div>
      <div className="rounded-2xl rounded-tl-sm border bg-card px-3 py-2">
        {m.structured?.kind === "fields" && m.structured.fields.length > 0 ? (
          <FieldCard fields={m.structured.fields} />
        ) : (
          <Markdown>{m.text}</Markdown>
        )}
        {m.found === false && !m.sensitive && (
          <p className="mt-1.5 text-xs text-muted-foreground">
            No grounded answer — check your captures.
          </p>
        )}
        {m.sensitive && (
          <p className="mt-1.5 flex items-center gap-1 text-xs text-yellow-600 dark:text-yellow-400">
            <TriangleAlert className="size-3" /> Includes sensitive material — handled per your
            sensitivity settings.
          </p>
        )}
        {m.sources && m.sources.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {dedupeSources(m.sources).map((s) => {
              const cap = captures.find((c) => c.id === s.capture_id);
              return (
                <SourceChip
                  key={s.capture_id}
                  s={s}
                  hasFile={cap?.type === "doc" && !!cap.raw_content_ref}
                  onClick={() => onSourceClick(s.capture_id)}
                  onOpenFile={() => onOpenFile(s.capture_id)}
                />
              );
            })}
          </div>
        )}
      </div>
      <div className="flex items-center gap-1 pl-1">
        <Button variant="ghost" size="icon-xs" title="Copy answer" onClick={copy}>
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
        </Button>
        <Button variant="ghost" size="icon-xs" title="Flag wrong answer" onClick={() => onFlag(m)}>
          <Flag className="size-3" />
        </Button>
      </div>
    </div>
  );
}

function DocumentPreview({
  doc,
  onOpenChange,
}: {
  doc: ShowDocument;
  onOpenChange: (open: boolean) => void;
}) {
  const ext = (doc.filename ?? "").split(".").pop()?.toLowerCase() ?? "";
  const iframeable = ["pdf", "png", "jpg", "jpeg", "webp", "tiff", "bmp"].includes(ext);
  useEffect(() => {
    if (!iframeable) {
      window.open(api.fileUrl(doc.capture_id), "_blank");
      onOpenChange(false);
    }
  }, [iframeable, doc.capture_id, onOpenChange]);
  if (!iframeable) return null;
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[80vh] w-[min(90vw,900px)] flex-col sm:max-w-none">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="size-4" />
            {doc.filename ?? `capture #${doc.capture_id}`}
          </DialogTitle>
          <DialogDescription>
            Original document — capture #{doc.capture_id}
          </DialogDescription>
        </DialogHeader>
        <iframe
          src={api.fileUrl(doc.capture_id)}
          className="min-h-0 flex-1 rounded-lg border bg-background"
          title={doc.filename ?? "document"}
        />
      </DialogContent>
    </Dialog>
  );
}

export default function ChatPane({
  captures,
  onSourceClick,
  onOpenFile,
}: {
  captures: Capture[];
  onSourceClick?: (captureId: number) => void;
  onOpenFile?: (captureId: number) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: newMessageId(),
      role: "assistant",
      text: "Ask anything about what you've captured. I only answer from your notes — every answer is grounded and cited.",
    },
  ]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<Message | null>(null);
  const [preview, setPreview] = useState<ShowDocument | null>(null);
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, busy]);

  async function ask(q?: string) {
    const text = (q ?? query).trim();
    if (!text || busy) return;
    if (!q) {
      setBusy(true);
      setMessages((m) => [...m, { id: newMessageId(), role: "user", text }]);
      setQuery("");
    }
    try {
      const res = await api.chat(text, false);
      setMessages((m) => [
        ...m,
        {
          id: newMessageId(),
          role: "assistant",
          text: res.answer,
          query: text,
          found: res.found,
          sources: res.sources,
          structured: res.structured ?? undefined,
          sensitive: res.sources.some((s) => s.sensitivity_tier !== "none"),
          artifact: res.artifact ?? undefined,
        },
      ]);
      if (res.show_document) {
        setPreview(res.show_document);
      }
      if (res.artifact) {
        setActiveArtifact(res.artifact);
      }
    } catch (e) {
      setMessages((m) => [
        ...m,
        { id: newMessageId(), role: "error", text: e instanceof Error ? e.message : "Chat failed" },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1">
      {/* Main chat column */}
      <div className={cn("flex min-h-0 flex-1 flex-col", activeArtifact && "border-r md:w-[45%]")}>
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex flex-col space-y-4 p-4">
            {messages.map((m) =>
              m.role === "user" ? (
                <div
                  key={m.id}
                  className="max-w-[85%] self-end rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground"
                >
                  {m.text}
                </div>
              ) : m.role === "error" ? (
                <div
                  key={m.id}
                  className="max-w-[85%] self-start rounded-2xl rounded-tl-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  {m.text}
                </div>
              ) : (
                <AssistantMessage
                  key={m.id}
                  m={m}
                  captures={captures}
                  onSourceClick={(id) => onSourceClick?.(id)}
                  onOpenFile={(id) => onOpenFile?.(id)}
                  onFlag={(msg) => setFeedbackMsg(msg)}
                />
              )
            )}
            {busy && (
              <div className="flex items-center gap-2 self-start text-sm text-muted-foreground">
                <RotateCw className="size-3.5 animate-spin" /> Thinking…
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 border-t p-3">
          <Input
            placeholder="Ask your notes…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                ask();
              }
            }}
            className="flex-1"
          />
          <Button size="icon" disabled={busy || !query.trim()} onClick={() => ask()} aria-label="Ask">
            <Send />
          </Button>
        </div>
        <FeedbackDialog
          open={feedbackMsg !== null}
          onOpenChange={(open) => {
            if (!open) setFeedbackMsg(null);
          }}
          query={feedbackMsg?.query ?? ""}
          captureIds={dedupeSources(feedbackMsg?.sources ?? []).map((s) => s.capture_id)}
        />
        {preview && <DocumentPreview doc={preview} onOpenChange={(o) => { if (!o) setPreview(null); }} />}
      </div>
      
      {/* Artifact preview panel — slides in when active */}
      {activeArtifact && (
        <div className="hidden min-h-0 flex-1 md:flex">
          <ArtifactPanel
            artifact={activeArtifact}
            onClose={() => setActiveArtifact(null)}
          />
        </div>
      )}
    </div>
  );
}