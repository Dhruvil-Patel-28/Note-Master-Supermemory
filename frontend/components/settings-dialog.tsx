"use client";

import { useEffect, useState } from "react";
import { Shield, ScrollText, Info } from "lucide-react";
import { api, AuditEntry } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

function SensitivitySection() {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="font-medium">Sensitivity tiers</p>
        <p className="text-xs text-muted-foreground">
          Every capture is classified at ingest as none, moderate, or high (ID/financial
          documents). Tiers are labels only — nothing is blocked. Sources are badged in chat,
          and every retrieval that surfaces sensitive content is logged in Activity.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge variant="destructive">high — Aadhaar, PAN, bank</Badge>
        <Badge variant="outline" className="text-yellow-600 dark:text-yellow-400">
          moderate — meeting, doctor, address
        </Badge>
        <Badge variant="outline">none — everything else</Badge>
      </div>
      <Separator />
      <p className="text-xs text-muted-foreground">
        All data stays on this machine: OCR, ASR, embeddings, and chat run locally via Ollama.
        No hosted APIs, no API keys, no telemetry.
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
          <DialogDescription>Sensitivity, activity, and app info.</DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="sensitivity">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="sensitivity">
              <Shield className="mr-1 size-3.5" /> Sensitivity
            </TabsTrigger>
            <TabsTrigger value="activity">
              <ScrollText className="mr-1 size-3.5" /> Activity
            </TabsTrigger>
            <TabsTrigger value="about">
              <Info className="mr-1 size-3.5" /> About
            </TabsTrigger>
          </TabsList>
          <TabsContent value="sensitivity" className="pt-3">
            <SensitivitySection />
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