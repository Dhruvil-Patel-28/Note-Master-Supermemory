"use client";

import { useCallback, useEffect, useState } from "react";
import { MessagesSquare, NotebookPen, Settings, FileText } from "lucide-react";
import { api, Capture } from "@/lib/api";
import CaptureComposer from "@/components/CaptureComposer";
import CaptureList from "@/components/CaptureList";
import ChatPane from "@/components/ChatPane";
import HealthIndicator from "@/components/health-indicator";
import SettingsDialog from "@/components/settings-dialog";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Tab = "captures" | "ask";

export default function Home() {
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [tab, setTab] = useState<Tab>("captures");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [focusId, setFocusId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const caps = await api.listCaptures();
      setCaptures(Array.from(new Map(caps.map((c) => [c.id, c])).values()));
    } catch {
      // backend unreachable; HealthIndicator surfaces this
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onSourceClick = useCallback((id: number) => {
    setFocusId(id);
    setTab("captures");
  }, []);

  const onOpenFile = useCallback((id: number) => {
    const cap = captures.find((c) => c.id === id);
    if (cap?.type === "doc" && cap.raw_content_ref) {
      window.open(api.fileUrl(id), "_blank");
    }
  }, [captures]);

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b px-3 sm:px-4">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <NotebookPen className="size-4" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold">Note Master</div>
            <div className="hidden text-xs text-muted-foreground sm:block">
              Dump messy, retrieve clean.
            </div>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <HealthIndicator />
          <ThemeToggle />
          <Button
            variant="ghost"
            size="icon"
            aria-label="Settings"
            onClick={() => setSettingsOpen(true)}
          >
            <Settings />
          </Button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(320px,2fr)_minmax(0,3fr)]">
        <section
          className={cn(
            "min-h-0 flex-col border-r",
            tab === "captures" ? "flex" : "hidden md:flex"
          )}
        >
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <h2 className="text-sm font-semibold">Captures</h2>
            <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {captures.length}
            </span>
          </div>
          <CaptureList
            captures={captures}
            onChanged={refresh}
            focusId={focusId}
          />
          <CaptureComposer onSent={refresh} />
        </section>
        <section
          className={cn(
            "min-h-0 flex-col",
            tab === "ask" ? "flex" : "hidden md:flex"
          )}
        >
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <h2 className="text-sm font-semibold">Ask</h2>
            <p className="ml-auto hidden text-xs text-muted-foreground sm:block">
              Answers only from your notes
            </p>
          </div>
          <ChatPane captures={captures} onSourceClick={onSourceClick} onOpenFile={onOpenFile} />
        </section>
      </div>

      <nav className="grid h-14 shrink-0 grid-cols-2 border-t md:hidden">
        <Button
          variant="ghost"
          className={cn("rounded-none", tab === "captures" && "bg-muted")}
          onClick={() => setTab("captures")}
        >
          <FileText />
          Captures
        </Button>
        <Button
          variant="ghost"
          className={cn("rounded-none", tab === "ask" && "bg-muted")}
          onClick={() => setTab("ask")}
        >
          <MessagesSquare />
          Ask
        </Button>
      </nav>

      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}