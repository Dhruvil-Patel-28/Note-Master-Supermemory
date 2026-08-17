"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Eye,
  FileText,
  History,
  Loader2,
  Lock,
  Mic,
  Pencil,
  RotateCcw,
  Search,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api, Capture } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<Capture["status"], string> = {
  queued: "queued",
  processing: "processing",
  indexed: "indexed",
  failed: "failed",
};

function TypeBadge({ type }: { type: Capture["type"] }) {
  if (type === "doc")
    return (
      <Badge variant="secondary">
        <FileText className="mr-1 size-3" /> doc
      </Badge>
    );
  if (type === "voice")
    return (
      <Badge variant="secondary">
        <Mic className="mr-1 size-3" /> voice
      </Badge>
    );
  return <Badge variant="outline">text</Badge>;
}

function StatusBadge({ status }: { status: Capture["status"] }) {
  if (status === "queued" || status === "processing")
    return (
      <Badge variant="outline">
        <Loader2 className="mr-1 size-3 animate-spin" /> {STATUS_LABEL[status]}
      </Badge>
    );
  if (status === "failed")
    return <Badge variant="destructive">{STATUS_LABEL[status]}</Badge>;
  return <Badge variant="outline">{STATUS_LABEL[status]}</Badge>;
}

function TierBadge({ tier }: { tier: Capture["sensitivity_tier"] }) {
  if (tier === "high")
    return (
      <Badge variant="destructive">
        <Lock className="mr-1 size-3" /> sensitive
      </Badge>
    );
  if (tier === "moderate")
    return (
      <Badge variant="outline" className="text-yellow-600 dark:text-yellow-400">
        <TriangleAlert className="mr-1 size-3" /> moderate
      </Badge>
    );
  return null;
}

function EditDialog({
  cap,
  open,
  onOpenChange,
  onSaved,
}: {
  cap: Capture | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && cap) {
      setDraft(cap.content);
      setNote(cap.note ?? "");
    }
  }, [open, cap]);

  async function save() {
    if (!cap || busy) return;
    const contentChanged = cap.type !== "doc" && draft.trim() && draft !== cap.content;
    const noteChanged = note.trim() !== (cap.note ?? "").trim();
    if (!contentChanged && !noteChanged) {
      onOpenChange(false);
      return;
    }
    setBusy(true);
    try {
      if (contentChanged) {
        await api.update(cap.id, draft, note);
        toast.success("Capture updated — re-indexing…");
      } else {
        await api.updateNote(cap.id, note);
        toast.success("Note updated");
      }
      onOpenChange(false);
      onSaved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit capture #{cap?.id}</DialogTitle>
          <DialogDescription>
            {cap?.type === "doc"
              ? "Add a note describing this document (e.g. “my resume”)."
              : "Editing re-indexes this capture."}
          </DialogDescription>
        </DialogHeader>
        {cap?.type === "doc" ? null : (
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={6}
            autoFocus
          />
        )}
        <Label className="text-xs text-muted-foreground">Note (what is this?)</Label>
        <Input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. my resume, my Aadhaar card"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DeleteDialog({
  cap,
  onDeleted,
}: {
  cap: Capture;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="icon-sm" title="Delete capture">
          <Trash2 />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete capture #{cap.id}?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently removes the capture, its index entries, and any associated file.
            {cap.version_number > 1 && " Other versions in this document group are kept."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground"
            disabled={busy}
            onClick={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                await api.remove(cap.id);
                toast.success("Capture deleted");
                onDeleted();
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Delete failed");
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Deleting…" : "Delete"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function VersionHistory({
  cap,
  onChanged,
}: {
  cap: Capture;
  onChanged: () => void;
}) {
  const [history, setHistory] = useState<Capture[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (history) {
      setHistory(null);
      return;
    }
    if (cap.document_group_id === null) return;
    setHistory(await api.history(cap.document_group_id));
  }

  async function restore(id: number) {
    if (busy) return;
    setBusy(true);
    try {
      await api.restore(id);
      toast.success(`Restored version — capture #${id} is now the latest`);
      setHistory(null);
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Restore failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {cap.version_number > 1 && (
        <Button variant="ghost" size="icon-sm" title="Version history" onClick={toggle}>
          <History />
        </Button>
      )}
      {history && (
        <div className="rounded-lg border bg-muted/40 p-2">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            All versions of this document group
          </p>
          <ul className="space-y-1">
            {history.map((h) => (
              <li key={h.id} className="flex items-center gap-2 text-xs">
                <Badge variant={h.is_latest ? "default" : "outline"}>v{h.version_number}</Badge>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  {h.type === "doc" ? h.original_filename ?? `#${h.id}` : h.content.slice(0, 60)}
                </span>
                {h.is_latest ? (
                  <span className="text-xs text-muted-foreground">current</span>
                ) : (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => restore(h.id)}
                    disabled={busy}
                  >
                    <RotateCcw className="mr-1 size-3" /> Restore
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

function CaptureItem({
  cap,
  focused,
  onChanged,
  onEdit,
}: {
  cap: Capture;
  focused: boolean;
  onChanged: () => void;
  onEdit: () => void;
}) {
  return (
    <Card
      data-capture-id={cap.id}
      className={cn(
        "transition-colors",
        focused && "ring-2 ring-primary ring-offset-2 ring-offset-background"
      )}
    >
      <CardContent className="space-y-2 p-3">
        <div className="flex items-center gap-1.5">
          <TypeBadge type={cap.type} />
          <StatusBadge status={cap.status} />
          <TierBadge tier={cap.sensitivity_tier} />
          {!cap.is_latest && <Badge variant="outline">old</Badge>}
          <div className="ml-auto flex items-center gap-0.5">
            {cap.version_number > 1 && (
              <VersionHistory cap={cap} onChanged={onChanged} />
            )}
            <Button variant="ghost" size="icon-sm" title="Edit" onClick={onEdit}>
              <Pencil />
            </Button>
            {cap.type === "doc" && cap.raw_content_ref && cap.status === "indexed" && (
              <Button
                variant="ghost"
                size="icon-sm"
                title="Open original file"
                onClick={() => window.open(api.fileUrl(cap.id), "_blank")}
              >
                <Eye />
              </Button>
            )}
            <DeleteDialog cap={cap} onDeleted={onChanged} />
          </div>
        </div>
        <div className="text-sm leading-relaxed break-words whitespace-pre-wrap">
          {cap.type === "doc" ? (
            <div className="flex items-start gap-1.5">
              <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0">
                <p className="font-medium">
                  {cap.original_filename ?? `Document #${cap.id}`}
                </p>
                {cap.note && (
                  <p className="text-xs text-primary">“{cap.note}”</p>
                )}
                {cap.status === "indexed" && (
                  <p className="text-xs text-muted-foreground">
                    {cap.content.length} chars indexed — open the file to view it
                  </p>
                )}
              </div>
            </div>
          ) : (
            cap.content
          )}
        </div>
        {cap.type === "voice" && cap.raw_content_ref && cap.status === "indexed" && (
          <audio controls src={api.audioUrl(cap.id)} className="h-8 w-full" />
        )}
        {cap.status === "failed" && cap.error && (
          <p className="text-xs text-destructive">{cap.error}</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function CaptureList({
  captures,
  onChanged,
  focusId,
}: {
  captures: Capture[];
  onChanged: () => void;
  focusId?: number | null;
}) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [editing, setEditing] = useState<Capture | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [highlight, setHighlight] = useState<number | null>(null);

  useEffect(() => {
    if (!captures.some((c) => c.status === "queued" || c.status === "processing")) return;
    const t = setInterval(onChanged, 1500);
    return () => clearInterval(t);
  }, [captures, onChanged]);

  useEffect(() => {
    if (!focusId) return;
    setHighlight(focusId);
    const el = listRef.current?.querySelector(`[data-capture-id="${focusId}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    const t = setTimeout(() => setHighlight(null), 2500);
    return () => clearTimeout(t);
  }, [focusId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return captures.filter((c) => {
      if (typeFilter !== "all" && c.type !== typeFilter) return false;
      if (statusFilter !== "all" && c.status !== statusFilter) return false;
      if (q && !c.content.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [captures, query, typeFilter, statusFilter]);

  const hasFilters = query.trim() !== "" || typeFilter !== "all" || statusFilter !== "all";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2 border-b p-3">
        <div className="relative">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="Search captures…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="h-8 flex-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              <SelectItem value="text">Text</SelectItem>
              <SelectItem value="voice">Voice</SelectItem>
              <SelectItem value="doc">Documents</SelectItem>
            </SelectContent>
          </Select>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 flex-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="queued">Queued</SelectItem>
              <SelectItem value="processing">Processing</SelectItem>
              <SelectItem value="indexed">Indexed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
          {hasFilters && (
            <Button
              variant="ghost"
              size="icon-sm"
              title="Clear filters"
              onClick={() => {
                setQuery("");
                setTypeFilter("all");
                setStatusFilter("all");
              }}
            >
              <X />
            </Button>
          )}
        </div>
      </div>
      <div ref={listRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {captures.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
            <div className="flex size-12 items-center justify-center rounded-full bg-muted">
              <FileText className="size-5 text-muted-foreground" />
            </div>
            <p className="text-sm text-muted-foreground">
              Nothing captured yet. Dump a note, record a voice memo, or drop a file below.
            </p>
          </div>
        ) : filtered.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No captures match your filters.
          </p>
        ) : (
          filtered.map((c) => (
            <CaptureItem
              key={c.id}
              cap={c}
              focused={highlight === c.id}
              onChanged={onChanged}
              onEdit={() => setEditing(c)}
            />
          ))
        )}
      </div>
      <EditDialog
        cap={editing}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        onSaved={onChanged}
      />
    </div>
  );
}