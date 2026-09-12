import React, { useEffect, useRef, useState } from "react";
import { resetSession, sendChat } from "../api.js";
import { Card, Chip, ErrorBox } from "./Shared.jsx";

/** WhatsApp markdown: *bold* and newlines. Split rather than inject HTML. */
function renderBody(text) {
  return text.split(/(\*[^*\n]+\*)/g).map((part, i) =>
    part.startsWith("*") && part.endsWith("*") && part.length > 2 ? (
      <strong key={i}>{part.slice(1, -1)}</strong>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    )
  );
}

/* The first inbound message always returns the language menu whatever it
   contains, so every script opens with "hi". Starting with "1" shifts every
   subsequent answer by one. */
const SCRIPTS = [
  {
    label: "Hindi homeowner → routed",
    turns: ["hi", "2", "1", "1", "302015", "650", "5", "1850 2100 1950", "skip", "1"],
  },
  {
    label: "Rented roof → dropped",
    turns: ["hi", "1", "1", "2"],
  },
  {
    label: "Unviable → dropped with reason",
    turns: ["hi", "1", "1", "1", "110001", "400", "2", "320 290 310", "skip"],
  },
  {
    label: "SME → CAPEX vs OPEX",
    turns: [
      "hi", "1", "2", "1", "302015", "9000", "150",
      "180000 175000 190000", "1", "8", "skip",
    ],
  },
];

const newPhone = () =>
  `9199${Math.floor(Math.random() * 1e8).toString().padStart(8, "0")}`;

export default function ChatReplay({ onLeadCreated, onOpenLead }) {
  const [phone, setPhone] = useState(newPhone);
  const [thread, setThread] = useState([]);
  const [input, setInput] = useState("");
  const [state, setState] = useState(null);
  const [leadId, setLeadId] = useState(null);
  const [terminal, setTerminal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const scroller = useRef(null);

  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = scroller.current.scrollHeight;
    }
  }, [thread]);

  async function turn(text, currentPhone = phone) {
    const reply = await sendChat(currentPhone, text);
    setThread((t) => [
      ...t,
      ...reply.messages.map((m) => ({ dir: "out", text: m })),
    ]);
    setState(reply.state);
    setTerminal(reply.terminal);
    if (reply.lead_id) {
      setLeadId(reply.lead_id);
      onLeadCreated?.();
    }
    return reply;
  }

  async function send(text) {
    if (!text.trim() || busy || terminal) return;
    setBusy(true);
    setError(null);
    setThread((t) => [...t, { dir: "in", text }]);
    setInput("");
    try {
      await turn(text);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function runScript(script) {
    setBusy(true);
    setError(null);
    const fresh = newPhone();
    setPhone(fresh);
    setThread([]);
    setLeadId(null);
    setTerminal(false);
    try {
      for (const text of script.turns) {
        setThread((t) => [...t, { dir: "in", text }]);
        const reply = await turn(text, fresh);
        if (reply.terminal) break;
        await new Promise((r) => setTimeout(r, 240));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await resetSession(phone).catch(() => {});
    } finally {
      setPhone(newPhone());
      setThread([]);
      setState(null);
      setLeadId(null);
      setTerminal(false);
      setError(null);
      setBusy(false);
    }
  }

  return (
    <Card
      title="WhatsApp qualification"
      subtitle="The same state machine the live webhook drives. No Meta account needed."
      actions={
        <button className="btn small" onClick={reset} disabled={busy}>
          New conversation
        </button>
      }
    >
      <div className="script-buttons">
        {SCRIPTS.map((s) => (
          <button
            key={s.label}
            className="btn small"
            onClick={() => runScript(s)}
            disabled={busy}
          >
            {s.label}
          </button>
        ))}
      </div>

      <ErrorBox error={error} />

      <div className="chat" ref={scroller}>
        {thread.length === 0 && (
          <p className="caption">
            Pick a scripted demo above, or type below. The first message always
            returns the language menu — start with “hi”.
          </p>
        )}
        {thread.map((m, i) => (
          <div key={i} className={`bubble ${m.dir}`}>
            {m.dir === "out" ? renderBody(m.text) : m.text}
          </div>
        ))}
        {busy && (
          <p className="caption">
            <span className="spinner" /> typing…
          </p>
        )}
      </div>

      <div className="chat-input">
        <input
          value={input}
          placeholder={terminal ? "Conversation ended" : "Type a reply…"}
          disabled={busy || terminal}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send(input)}
        />
        <button
          className="btn primary"
          onClick={() => send(input)}
          disabled={busy || terminal || !input.trim()}
        >
          Send
        </button>
      </div>

      <div className="row" style={{ marginTop: 12 }}>
        <span className="caption">{phone}</span>
        {state && <Chip>{state.replace(/_/g, " ")}</Chip>}
        {terminal && <Chip tone="warn">ended</Chip>}
        {leadId && (
          <button className="btn small" onClick={() => onOpenLead?.(leadId)}>
            Open lead {leadId}
          </button>
        )}
      </div>
    </Card>
  );
}
