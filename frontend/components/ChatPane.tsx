"use client";

import { useEffect, useRef, useState } from "react";
import {
  Copy,
  Check,
  Flag,
  Lock,
  RotateCw,
  Send,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { toast } from "sonner";
import { api, ChatResponse, ChatSource } from "@/lib/api";
import Markdown from "@/components/markdown";
import FeedbackDialog from "@/components/feedback-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
  id: number;
  role: "user" | "assistant" | "error";
  text: string;
  query?: string;
  found?: boolean;
  sources?: ChatResponse["sources"];
  structured?: ChatResponse["structured"];
  sensitive?: boolean;
  needsPin?: boolean;
}

let nextId = 1;

function SourceChip({
  s,
  onClick,
}: {
  s: ChatSource;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={s.snippet.replace(/<[^>]+>/g, "")}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors hover:bg-muted",
        s.sensitivity_tier === "high" &&
          "border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/20",
        s.sensitivity_tier === "moderate" &&
          "border-yellow-500/40 bg-yellow-500/10 text-yellow-600 hover:bg-yellow-500/20 dark:text-yellow-400",
        s.sensitivity_tier === "none" &&
          "border-primary/30 bg-primary/10 text-primary hover:bg-primary/20"
      )}
    >
      {s.sensitivity_tier === "high" && <Lock className="size-3" />}
      {s.sensitivity_tier === "moderate" && <TriangleAlert className="size-3" />}
      capture #{s.capture_id}
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
  onSourceClick,
  onFlag,
}: {
  m: Message;
  onSourceClick: (id: number) => void;
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
        {m.found === false && !m.sensitive && !m.needsPin && (
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
            {m.sources.map((s) => (
              <SourceChip
                key={s.capture_id}
                s={s}
                onClick={() => onSourceClick(s.capture_id)}
              />
            ))}
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

function PinDialog({
  open,
  onOpenChange,
  setup,
  onVerified,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  setup: boolean;
  onVerified: (token: string) => void;
}) {
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (pinInput.length < 4) {
      setPinError("PIN must be at least 4 characters");
      return;
    }
    setBusy(true);
    setPinError(null);
    try {
      let token: string;
      if (setup) {
        await api.pinSet(pinInput);
        token = (await api.pinVerify(pinInput)).token;
      } else {
        token = (await api.pinVerify(pinInput)).token;
      }
      sessionStorage.setItem("nm-pin-token", token);
      toast.success(setup ? "PIN set — unlocked" : "Unlocked");
      setPinInput("");
      onOpenChange(false);
      onVerified(token);
    } catch (e) {
      setPinError(e instanceof Error ? e.message : "Invalid PIN");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{setup ? "Set a PIN for sensitive documents" : "PIN required"}</DialogTitle>
          <DialogDescription>
            {setup
              ? "A PIN gates ID/financial documents (Aadhaar, PAN, bank statements) at retrieval."
              : "Your question touches sensitive documents. Enter your PIN to unlock."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="pin-input">PIN</Label>
          <Input
            id="pin-input"
            type="password"
            autoFocus
            value={pinInput}
            onChange={(e) => setPinInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="PIN"
          />
          {pinError && <p className="text-xs text-destructive">{pinError}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy}>
            {setup ? "Set PIN" : "Unlock"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function ChatPane({
  onSourceClick,
}: {
  onSourceClick?: (captureId: number) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: nextId++,
      role: "assistant",
      text: "Ask anything about what you've captured. I only answer from your notes — every answer is grounded and cited.",
    },
  ]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);
  const [pinSetup, setPinSetup] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<Message | null>(null);
  const pendingQueryRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, busy]);

  async function ask(q?: string, retryToken?: string | null) {
    const text = (q ?? query).trim();
    if (!text || busy) return;
    if (!q) {
      setBusy(true);
      setMessages((m) => [...m, { id: nextId++, role: "user", text }]);
      setQuery("");
    }
    const token = retryToken !== undefined ? retryToken : sessionStorage.getItem("nm-pin-token");
    try {
      const res = await api.chat(text, false, token);
      if (res.needs_pin) {
        pendingQueryRef.current = text;
        setPinSetup(false);
        setPinOpen(true);
        setMessages((m) => [
          ...m,
          {
            id: nextId++,
            role: "assistant",
            text: res.answer,
            query: text,
            needsPin: true,
            sources: res.sources,
          },
        ]);
        return;
      }
      setMessages((m) => [
        ...m,
        {
          id: nextId++,
          role: "assistant",
          text: res.answer,
          query: text,
          found: res.found,
          sources: res.sources,
          structured: res.structured ?? undefined,
          sensitive: res.sources.some((s) => s.sensitivity_tier !== "none"),
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { id: nextId++, role: "error", text: e instanceof Error ? e.message : "Chat failed" },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function onPinVerified(token: string) {
    const q = pendingQueryRef.current;
    pendingQueryRef.current = null;
    if (q) await ask(q, token);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
                onSourceClick={(id) => onSourceClick?.(id)}
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
      <PinDialog
        open={pinOpen}
        onOpenChange={setPinOpen}
        setup={pinSetup}
        onVerified={onPinVerified}
      />
      <FeedbackDialog
        open={feedbackMsg !== null}
        onOpenChange={(open) => {
          if (!open) setFeedbackMsg(null);
        }}
        query={feedbackMsg?.query ?? ""}
        captureIds={feedbackMsg?.sources?.map((s) => s.capture_id) ?? []}
      />
    </div>
  );
}