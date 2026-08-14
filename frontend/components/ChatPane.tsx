"use client";

import { useEffect, useRef, useState } from "react";
import { api, ChatResponse } from "@/lib/api";

interface Message {
  role: "user" | "assistant" | "error";
  text: string;
  found?: boolean;
  sources?: ChatResponse["sources"];
  structured?: ChatResponse["structured"];
  sensitive?: boolean;
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
  const [pinPrompt, setPinPrompt] = useState<string | null>(null);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingQueryRef = useRef<string | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function ask(q?: string, retryToken?: string | null) {
    const text = q ?? query;
    const clean = text.trim();
    if (!clean || busy) return;
    if (!q) {
      setBusy(true);
      setMessages((m) => [...m, { role: "user", text: clean }]);
      setQuery("");
    }
    const token = retryToken !== undefined ? retryToken : sessionStorage.getItem("nm-pin-token");
    try {
      const res = await api.chat(clean, false, token);
      if (res.needs_pin) {
        pendingQueryRef.current = clean;
        setPinPrompt(clean);
        setMessages((m) => [...m, { role: "assistant", text: res.answer }]);
        return;
      }
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: res.answer,
          found: res.found,
          sources: res.sources,
          structured: res.structured ?? undefined,
          sensitive: res.sources.some((s) => s.sensitivity_tier !== "none"),
        },
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

  async function submitPin() {
    setPinError(null);
    try {
      const { token } = await api.pinVerify(pinInput);
      sessionStorage.setItem("nm-pin-token", token);
      const q = pendingQueryRef.current;
      setPinPrompt(null);
      setPinInput("");
      pendingQueryRef.current = null;
      if (q) await ask(q, token);
    } catch (e) {
      setPinError(e instanceof Error ? e.message : "invalid pin");
    }
  }

  async function setupPin() {
    if (pinInput.length < 4) {
      setPinError("pin must be at least 4 characters");
      return;
    }
    setPinError(null);
    try {
      await api.pinSet(pinInput);
      sessionStorage.setItem("nm-pin-token", (await api.pinVerify(pinInput)).token);
      const q = pendingQueryRef.current;
      setPinPrompt(null);
      setPinInput("");
      pendingQueryRef.current = null;
      if (q) await ask(q, sessionStorage.getItem("nm-pin-token"));
    } catch (e) {
      setPinError(e instanceof Error ? e.message : "could not set pin");
    }
  }

  function openPinSetup() {
    setPinError(null);
    setPinPrompt("__setup__");
  }

  return (
    <div className="chat">
      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="msg-text">{m.text}</div>
            {m.structured?.kind === "fields" && m.structured.fields.length > 0 && (
              <table className="msg-card">
                <tbody>
                  {m.structured.fields.map((f, i) => (
                    <tr key={i}>
                      <td>{f.key}</td>
                      <td>{f.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {m.role === "assistant" && m.found === false && !m.sensitive && (
              <div className="msg-note">No grounded answer — check your captures.</div>
            )}
            {m.sensitive && (
              <div className="msg-note sensitive-note">
                Includes sensitive material — handled per your sensitivity settings.
              </div>
            )}
            {m.sources && m.sources.length > 0 && (
              <ul className="msg-sources">
                {m.sources.map((s) => (
                  <li
                    key={s.capture_id}
                    className={s.sensitivity_tier !== "none" ? `tier-${s.sensitivity_tier}` : ""}
                    title={s.snippet.replace(/<[^>]+>/g, "")}
                  >
                    capture #{s.capture_id}
                    {s.sensitivity_tier === "high" && " 🔒"}
                    {s.sensitivity_tier === "moderate" && " ⚠"}
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
        <button disabled={busy || !query.trim()} onClick={() => ask()}>
          Ask
        </button>
      </div>
      {pinPrompt !== null && (
        <div className="pin-overlay">
          <div className="pin-modal">
            <h3>{pinPrompt === "__setup__" ? "Set a PIN for sensitive documents" : "PIN required"}</h3>
            {pinPrompt !== "__setup__" && (
              <p className="pin-note">
                Your question touches sensitive documents. Enter your PIN to unlock.
                {!sessionStorage.getItem("nm-pin-token") && (
                  <button className="pin-link" onClick={openPinSetup}>
                    No PIN yet? Set one.
                  </button>
                )}
              </p>
            )}
            {pinPrompt === "__setup__" && (
              <p className="pin-note">
                A PIN gates ID/financial documents (Aadhaar, PAN, bank statements) at retrieval.
              </p>
            )}
            <input
              type="password"
              autoFocus
              value={pinInput}
              placeholder="PIN"
              onChange={(e) => setPinInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  if (pinPrompt === "__setup__") setupPin();
                  else submitPin();
                }
              }}
            />
            {pinError && <div className="composer-error">{pinError}</div>}
            <div className="pin-actions">
              {pinPrompt === "__setup__" ? (
                <button onClick={setupPin}>Set PIN</button>
              ) : (
                <button onClick={submitPin}>Unlock</button>
              )}
              <button onClick={() => setPinPrompt(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}