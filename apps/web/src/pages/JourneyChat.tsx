import { ArrowUp, Bot, Check, Loader2, ShieldCheck, UserRound } from "lucide-react";
import { useState } from "react";
import { api, type CareJourneySnapshot } from "@/lib/api";

type Message = { role: "user" | "assistant"; text: string };

export function JourneyChat({ onBack }: { onBack: () => void }) {
  const [snapshot, setSnapshot] = useState<CareJourneySnapshot | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function call<T>(fn: () => Promise<T>, userText?: string) {
    setBusy(true); setError(null);
    if (userText) setMessages((items) => [...items, { role: "user", text: userText }]);
    try { return await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); return null; } finally { setBusy(false); }
  }
  async function send() {
    const value = text.trim(); if (!value) return;
    setText("");
    if (!snapshot) {
      const started = await call(() => api.startJourney(), value);
      if (started) {
        const onboarded = await call(() => api.journeyOnboard(started.journey_id, value));
        if (onboarded) {
          setSnapshot(onboarded);
          setMessages((items) => [...items, { role: "assistant", text: onboarded.onboarding_questions.length ? onboarded.onboarding_questions.join(" ") : "The Onboarding and Knowledge agents recorded the intake facts." }]);
        }
      }
      return;
    }
    const result = await call(() => api.journeyOnboard(snapshot.journey_id, value), value);
    if (result) { setSnapshot(result); setMessages((items) => [...items, { role: "assistant", text: result.onboarding_questions.length ? result.onboarding_questions.join(" ") : "I recorded that intake information. The journey is ready for the next deterministic step." }]); }
  }
  async function consent(action: string, scope: string): Promise<CareJourneySnapshot | null> {
    if (!snapshot) return null;
    const result = await call(() => api.journeyConsent(snapshot.journey_id, { action, scope, approved: true }));
    if (result) { setSnapshot(result); setMessages((items) => [...items, { role: "assistant", text: `Consent recorded for ${scope}.` }]); }
    return result;
  }
  async function nextAction() {
    if (!snapshot) return;
    let result: CareJourneySnapshot | null = null;
    if (snapshot.stage === "compare") result = await call(() => api.journeyCompare(snapshot.journey_id));
    else if (snapshot.stage === "recommend") result = await call(() => api.journeyAdvance(snapshot.journey_id));
    else if (snapshot.stage === "enroll") { const c = await consent("enroll_plan", "wa-plan-b"); if (!c) return; result = await call(() => api.journeyAction(snapshot.journey_id, { action: "enroll_plan", scope: "wa-plan-b", idempotency_key: `chat-enroll-${snapshot.journey_id}` })); }
    else if (snapshot.stage === "transition") { const c = await consent("transition_coverage", "current coverage to wa-plan-b"); if (!c) return; result = await call(() => api.journeyAction(snapshot.journey_id, { action: "transition_coverage", scope: "current coverage to wa-plan-b", idempotency_key: `chat-transition-${snapshot.journey_id}`, new_effective_date: "2026-09-01", first_premium_confirmed: true })); }
    else if (snapshot.stage === "verify") { const c = await consent("share_with_provider", "Dr. Lee / Seattle General"); if (!c) return; result = await call(() => api.journeyAction(snapshot.journey_id, { action: "share_with_provider", scope: "Dr. Lee / Seattle General", idempotency_key: `chat-verify-${snapshot.journey_id}` })); }
    else if (snapshot.stage === "book") { const c = await consent("book_appointment", "Dr. Lee / September 4, 2026 at 10:30"); if (!c) return; result = await call(() => api.journeyAction(snapshot.journey_id, { action: "book_appointment", scope: "Dr. Lee / September 4, 2026 at 10:30", idempotency_key: `chat-book-${snapshot.journey_id}` })); }
    if (result) { setSnapshot(result); setMessages((items) => [...items, { role: "assistant", text: `Backend advanced the journey to ${result.stage}.` }]); }
  }
  async function explain() {
    if (!snapshot?.evaluations.length) return;
    const result = await call(() => api.journeyMatchingReason(snapshot.journey_id));
    if (result) { setSnapshot(result.journey); setMessages((items) => [...items, { role: "assistant", text: result.reason }]); }
  }

  const canAdvance = snapshot && ["compare", "recommend", "enroll", "transition", "verify", "book"].includes(snapshot.stage);
  return <main className="mx-auto flex min-h-dvh w-full max-w-5xl flex-col bg-background px-5 pb-8 pt-6 md:px-10"><header className="flex items-center justify-between border-b border-border pb-4"><div><button onClick={onBack} className="text-xs text-muted-foreground">← Back</button><p className="mt-3 text-xs font-medium uppercase tracking-[.18em] text-primary">Backend test lab</p><h1 className="font-display text-2xl font-semibold text-foreground">Care Journey Chat</h1></div>{snapshot && <span className="rounded-full border border-primary/30 px-3 py-1 text-xs text-primary">{snapshot.stage}</span>}</header><div className="grid flex-1 gap-5 pt-5 md:grid-cols-[1fr_330px]"><section className="flex min-h-[560px] flex-col rounded-2xl border border-border bg-card p-4"><div className="flex-1 space-y-4 overflow-auto">{messages.length === 0 && <div className="rounded-xl bg-secondary/60 p-4 text-sm leading-relaxed text-muted-foreground">Try: <button onClick={() => setText("I want an MRI scan for my knee")} className="text-primary underline">“I want an MRI scan for my knee.”</button><br />Every response below is produced by the live GN100-backed API.</div>}{messages.map((message, index) => <div key={`${message.role}-${index}`} className={`flex gap-2 ${message.role === "user" ? "justify-end" : ""}`}><span className="mt-1 text-muted-foreground">{message.role === "user" ? <UserRound size={15} /> : <Bot size={15} />}</span><p className={`max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed ${message.role === "user" ? "bg-primary text-primary-foreground" : "bg-secondary text-foreground"}`}>{message.text}</p></div>)}</div><div className="mt-4 flex gap-2 border-t border-border pt-4"><input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void send(); }} placeholder="Send a request or answer…" className="min-w-0 flex-1 rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none" /><button onClick={() => void send()} disabled={busy || !text.trim()} className="rounded-xl bg-primary px-3 text-primary-foreground"><ArrowUp size={17} /></button></div></section><aside className="space-y-4"><div className="rounded-2xl border border-border bg-card p-4"><div className="flex items-center gap-2"><ShieldCheck size={16} className="text-primary" /><h2 className="text-sm font-medium">Live controls</h2></div>{!snapshot ? <p className="mt-3 text-xs leading-relaxed text-muted-foreground">Send your first message to create a real journey on the backend.</p> : <div className="mt-3 space-y-2">{snapshot.onboarding_questions.length > 0 && <p className="rounded-lg bg-warning/10 p-3 text-xs text-foreground">Needs input: {snapshot.onboarding_questions.join(" ")}</p>}{snapshot.stage === "intake" && <button onClick={() => void consent("process_documents", "synthetic request and documents")} className="w-full rounded-lg border border-primary/30 px-3 py-2 text-xs text-primary">Approve document processing</button>}{canAdvance && <button onClick={() => void nextAction()} disabled={busy} className="w-full rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground">{busy ? <Loader2 size={14} className="mx-auto animate-spin" /> : snapshot.stage === "compare" ? "Run deterministic comparison" : snapshot.stage === "recommend" ? "Continue to enrollment" : snapshot.stage === "enroll" ? "Approve enrollment" : `Run ${snapshot.stage} action`}</button>}{snapshot.evaluations.length > 0 && <button onClick={() => void explain()} disabled={busy} className="w-full rounded-lg border border-border px-3 py-2 text-xs text-foreground">Ask Nemotron for reasoning</button>}</div>}</div>{snapshot && <div className="rounded-2xl border border-border bg-card p-4"><h2 className="text-sm font-medium">Trace</h2><div className="mt-3 space-y-2">{snapshot.events.slice(-8).reverse().map((event) => <div key={`${event.sequence}-${event.type}`} className="flex gap-2 text-xs"><Check size={13} className="mt-0.5 shrink-0 text-primary" /><span><b className="font-medium text-foreground">{event.type}</b><span className="ml-1 text-muted-foreground">· {event.actor}</span></span></div>)}</div><p className="mt-4 text-xs text-muted-foreground">{snapshot.receipts.length} sandbox receipt(s)</p></div>}{error && <p className="rounded-xl bg-destructive/10 p-3 text-xs text-destructive">{error}</p>}</aside></div></main>;
}
