"use client";

import { useEffect, useRef, useState } from "react";
import { api, ChatResponse } from "@/lib/api";

interface Message {
  role: "user" | "assistant" | "error";
  text: string;
  found?: boolean;
  sources?: ChatResponse["sources"];
}

export default function ChatPane() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      text: "Ask anything about what you've captured. I only answer from your notes.",
    },
  ]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function ask() {
    const q = query.trim();
    if (!q || busy) return;
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text: q }]);
    setQuery("");
    try {
      const res = await api.chat(q);
      setMessages((m) => [
        ...m,
        { role: "assistant", text: res.answer, found: res.found, sources: res.sources },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "error", text: e instanceof Error ? e.message : "chat failed" },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="msg-text">{m.text}</div>
            {m.role === "assistant" && m.found === false && (
              <div className="msg-note">No grounded answer — check your captures.</div>
            )}
            {m.sources && m.sources.length > 0 && (
              <ul className="msg-sources">
                {m.sources.map((s) => (
                  <li key={s.capture_id} title={s.snippet.replace(/<[^>]+>/g, "")}>
                    capture #{s.capture_id}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
        {busy && <div className="msg assistant thinking">thinking…</div>}
      </div>
      <div className="chat-input">
        <input
          placeholder="Ask your notes…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              ask();
            }
          }}
        />
        <button disabled={busy || !query.trim()} onClick={ask}>
          Ask
        </button>
      </div>
    </div>
  );
}