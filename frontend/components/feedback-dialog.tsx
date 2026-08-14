"use client";

import { useState } from "react";
import { toast } from "sonner";
import { api, FeedbackKind } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const KINDS: { value: FeedbackKind; label: string }[] = [
  { value: "wrong", label: "Wrong answer" },
  { value: "missing", label: "Missing information" },
  { value: "off_topic", label: "Off-topic" },
  { value: "other", label: "Other" },
];

export default function FeedbackDialog({
  open,
  onOpenChange,
  query,
  captureIds,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  query: string;
  captureIds: number[];
}) {
  const [kind, setKind] = useState<FeedbackKind>("wrong");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (busy) return;
    setBusy(true);
    try {
      await api.submitFeedback({ query, capture_ids: captureIds, kind, note });
      toast.success("Feedback recorded", {
        description: "The source capture is being re-indexed to fix future answers.",
      });
      setNote("");
      onOpenChange(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not submit feedback");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Flag this answer</DialogTitle>
          <DialogDescription>
            Tell us what went wrong — it feeds back into re-indexing so future answers improve.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>What was wrong?</Label>
            <Select value={kind} onValueChange={(v) => setKind(v as FeedbackKind)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KINDS.map((k) => (
                  <SelectItem key={k.value} value={k.value}>
                    {k.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fb-note">Details (optional)</Label>
            <Textarea
              id="fb-note"
              placeholder="e.g. it said the balance was 1000 but it should be 2500"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy}>
            Submit feedback
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}