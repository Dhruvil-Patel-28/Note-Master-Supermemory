"use client";

import { useEffect, useState } from "react";
import { Lock, LockOpen, ScrollText, Info } from "lucide-react";
import { toast } from "sonner";
import { api, AuditEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function PinSection() {
  const [set, setSet] = useState<boolean | null>(null);
  const [newPin, setNewPin] = useState("");
  const [oldPin, setOldPin] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setSet((await api.pinStatus()).set);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function setPin() {
    if (newPin.length < 4) return toast.error("PIN must be at least 4 characters");
    setBusy(true);
    try {
      await api.pinSet(newPin);
      toast.success("PIN set — sensitive documents are now gated");
      setNewPin("");
      await refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not set PIN");
    } finally {
      setBusy(false);
    }
  }

  async function changePin() {
    if (newPin.length < 4) return toast.error("PIN must be at least 4 characters");
    setBusy(true);
    try {
      await api.pinChange(oldPin, newPin);
      toast.success("PIN changed");
      setOldPin("");
      setNewPin("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not change PIN");
    } finally {
      setBusy(false);
    }
  }

  async function deletePin() {
    setBusy(true);
    try {
      await api.pinDelete(oldPin);
      toast.success("PIN removed — sensitive documents are no longer gated");
      setOldPin("");
      await refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not remove PIN");
    } finally {
      setBusy(false);
    }
  }

  if (set === null) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {set ? (
          <Badge variant="secondary">
            <Lock className="mr-1 size-3" /> PIN enabled
          </Badge>
        ) : (
          <Badge variant="outline">
            <LockOpen className="mr-1 size-3" /> No PIN set
          </Badge>
        )}
      </div>
      {!set ? (
        <div className="space-y-2">
          <Label htmlFor="pin-new">New PIN</Label>
          <Input
            id="pin-new"
            type="password"
            value={newPin}
            onChange={(e) => setNewPin(e.target.value)}
            placeholder="At least 4 characters"
          />
          <Button onClick={setPin} disabled={busy}>
            Set PIN
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="pin-old">Current PIN</Label>
            <Input
              id="pin-old"
              type="password"
              value={oldPin}
              onChange={(e) => setOldPin(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pin-new">New PIN</Label>
            <Input
              id="pin-new"
              type="password"
              value={newPin}
              onChange={(e) => setNewPin(e.target.value)}
              placeholder="At least 4 characters"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={changePin} disabled={busy}>
              Change PIN
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" disabled={busy}>
                  Remove PIN
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Remove the PIN?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Sensitive documents (Aadhaar, PAN, bank statements) will no longer be gated
                    at retrieval. This is a local recovery option.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={deletePin}>Remove PIN</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        The PIN is a light, local guardrail against casual snooping — it is not account
        authentication.
      </p>
    </div>
  );
}

function AuditSection() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .audit(50)
      .then(setEntries)
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load"));
  }, []);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (entries === null) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Every retrieval that surfaces sensitive content is logged here.
      </p>
      <ScrollArea className="h-72 rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">Time</TableHead>
              <TableHead>Query</TableHead>
              <TableHead className="w-20 text-right">Type</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.length === 0 && (
              <TableRow>
                <TableCell colSpan={3} className="text-center text-muted-foreground">
                  No retrievals yet
                </TableCell>
              </TableRow>
            )}
            {entries.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="whitespace-nowrap font-mono text-xs">
                  {e.created_at.slice(0, 16)}
                </TableCell>
                <TableCell className="max-w-[220px] truncate text-sm">{e.query}</TableCell>
                <TableCell className="text-right">
                  {e.sensitive_access ? (
                    <Badge variant="destructive">sensitive</Badge>
                  ) : (
                    <Badge variant="outline">regular</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </ScrollArea>
    </div>
  );
}

function AboutSection() {
  return (
    <div className="space-y-3 text-sm">
      <div className="space-y-1">
        <p className="font-medium">Note Master</p>
        <p className="text-muted-foreground">Dump messy, retrieve clean.</p>
        <p className="text-xs text-muted-foreground">v0.1 · local-first, single-user</p>
      </div>
      <Separator />
      <div className="space-y-1 text-muted-foreground">
        <p>
          All models run locally via Ollama. Documents and audio never leave this machine.
        </p>
        <p>No hosted APIs, no API keys, no telemetry.</p>
      </div>
      <Separator />
      <div className="space-y-1 text-xs text-muted-foreground">
        <p>Models: llama3.2:3b (chat) · nomic-embed-text (embeddings)</p>
        <p>OCR: qwen2.5vl:3b (opt-in) · ASR: faster-whisper base (CPU)</p>
      </div>
    </div>
  );
}

export default function SettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>Security, activity, and app info.</DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="security">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="security">
              <Lock className="mr-1 size-3.5" /> Security
            </TabsTrigger>
            <TabsTrigger value="activity">
              <ScrollText className="mr-1 size-3.5" /> Activity
            </TabsTrigger>
            <TabsTrigger value="about">
              <Info className="mr-1 size-3.5" /> About
            </TabsTrigger>
          </TabsList>
          <TabsContent value="security" className="pt-3">
            <PinSection />
          </TabsContent>
          <TabsContent value="activity" className="pt-3">
            <AuditSection />
          </TabsContent>
          <TabsContent value="about" className="pt-3">
            <AboutSection />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}