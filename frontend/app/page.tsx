"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Capture } from "@/lib/api";
import CaptureComposer from "@/components/CaptureComposer";
import CaptureList from "@/components/CaptureList";
import ChatPane from "@/components/ChatPane";

export default function Home() {
  const [captures, setCaptures] = useState<Capture[]>([]);

  const refresh = useCallback(async () => {
    try {
      setCaptures(await api.listCaptures());
    } catch {
      // backend not reachable yet; poll later
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <main className="app">
      <section className="pane capture-pane">
        <header className="pane-header">Capture</header>
        <div className="pane-body">
          <CaptureList captures={captures} onChanged={refresh} />
        </div>
        <CaptureComposer onSent={refresh} />
      </section>
      <section className="pane chat-pane">
        <header className="pane-header">Ask</header>
        <div className="pane-body">
          <ChatPane />
        </div>
      </section>
    </main>
  );
}