import { useState } from "react";
import { api, type CareJourneySnapshot } from "@/lib/api";

const actions = {
  enroll: "enroll_plan",
  transition: "transition_coverage",
  verify: "share_with_provider",
  book: "book_appointment",
} as const;

export function Journey({ onBack }: { onBack: () => void }) {
  const [snapshot, setSnapshot] = useState<CareJourneySnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [matchingReason, setMatchingReason] = useState<string | null>(null);

  async function run(work: () => Promise<CareJourneySnapshot>) {
    setBusy(true); setError(null);
    try { setSnapshot(await work()); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function start() {
    const started = await api.startJourney();
    const consented = await api.journeyConsent(started.journey_id, { action: "process_documents", scope: "synthetic request and documents", approved: true });
    setSnapshot(consented);
  }

  async function submitAnswer() {
    if (!snapshot || !answer.trim()) return;
    await run(() => api.journeyOnboard(snapshot.journey_id, answer));
    setAnswer("");
  }

  async function compare() {
    if (!snapshot) return;
    await run(() => api.journeyCompare(snapshot.journey_id));
  }

  async function explainMatch() {
    if (!snapshot) return;
    await run(async () => {
      const result = await api.journeyMatchingReason(snapshot.journey_id);
      setMatchingReason(result.reason);
      return result.journey;
    });
  }

  async function advance() {
    if (!snapshot) return;
    await run(() => api.journeyAdvance(snapshot.journey_id));
  }

  async function act(kind: keyof typeof actions) {
    if (!snapshot) return;
    const action = actions[kind];
    const scope = kind === "enroll" ? "wa-plan-b" : kind === "transition" ? "current coverage to wa-plan-b" : kind === "verify" ? "Dr. Lee / Seattle General" : "Dr. Lee / September 4, 2026 at 10:30";
    await run(() => api.journeyConsent(snapshot.journey_id, { action, scope, approved: true }).then((s) =>
      api.journeyAction(s.journey_id, { action, scope, idempotency_key: `${kind}-${s.journey_id}`, ...(kind === "transition" ? { new_effective_date: "2026-09-01", first_premium_confirmed: true } : {}) })));
  }

  return (
    <main className="mx-auto min-h-dvh w-full max-w-md bg-background px-5 pb-24 pt-8">
      <button onClick={onBack} className="text-sm text-muted-foreground">← Back</button>
      <p className="mt-8 text-xs font-medium uppercase tracking-[0.18em] text-primary">Care journey</p>
      <h1 className="mt-2 font-display text-3xl font-semibold text-foreground">Coverage + knee MRI</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">A seeded Washington scenario. Every result is sandbox-only and every action requires separate approval.</p>
      {!snapshot ? (
        <button disabled={busy} onClick={() => void run(start)} className="mt-8 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">Start seeded request</button>
      ) : (
        <>
          <div className="mt-6 rounded-xl border border-border bg-card p-4 text-sm"><span className="text-muted-foreground">Stage: </span><b>{snapshot.stage}</b></div>
          {snapshot.onboarding_questions.length > 0 && <section className="mt-5 rounded-xl border border-primary/30 bg-primary/5 p-4"><h2 className="font-medium text-foreground">A little more detail</h2>{snapshot.onboarding_questions.map((question) => <p key={question} className="mt-2 text-sm text-muted-foreground">{question}</p>)}<input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Type your answer" className="mt-3 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm" /><button disabled={busy || !answer.trim()} onClick={() => void submitAnswer()} className="mt-3 w-full rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground">Send answer</button></section>}
          {snapshot.evaluations.length === 0 && snapshot.stage === "compare" && <button disabled={busy} onClick={() => void compare()} className="mt-4 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">Compare three plans</button>}
          {snapshot.evaluations.length > 0 && <section className="mt-5 space-y-3"><h2 className="font-medium text-foreground">Ranked care paths</h2>{snapshot.evaluations.map((item) => <div key={item.plan_id} className={`rounded-xl border p-4 ${item.feasible ? "border-primary/40 bg-card" : "border-border bg-secondary/40"}`}><div className="flex justify-between gap-3"><b>{item.plan_name}</b><b>{item.feasible ? `$${item.annual_total.toLocaleString()}` : "Rejected"}</b></div>{item.hard_failures.length > 0 && <p className="mt-2 text-xs text-muted-foreground">{item.hard_failures.join(" · ")}</p>}</div>)}<button disabled={busy} onClick={() => void explainMatch()} className="w-full rounded-xl border border-border px-4 py-3 text-sm text-foreground">Ask Nemotron to explain these constraints</button>{matchingReason && <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 text-sm leading-relaxed text-foreground"><span className="mb-1 block text-xs font-medium uppercase tracking-wider text-primary">Matching Agent reasoning</span>{matchingReason}</div>}</section>}
          {snapshot.stage === "recommend" && <button disabled={busy} onClick={() => void advance()} className="mt-5 w-full rounded-xl border border-primary px-4 py-3 text-sm font-medium text-primary">Review enrollment approval</button>}
          {snapshot.stage === "enroll" && <button disabled={busy} onClick={() => void act("enroll")} className="mt-5 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">Approve sandbox enrollment in Plan B</button>}
          {snapshot.stage === "transition" && <button disabled={busy} onClick={() => void act("transition")} className="mt-5 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">Approve coverage transition</button>}
          {snapshot.stage === "verify" && <button disabled={busy} onClick={() => void act("verify")} className="mt-5 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">Approve provider verification</button>}
          {snapshot.stage === "book" && <button disabled={busy} onClick={() => void act("book")} className="mt-5 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">Approve sandbox appointment</button>}
          {snapshot.receipts.length > 0 && <section className="mt-7"><h2 className="font-medium text-foreground">Sandbox receipts</h2>{snapshot.receipts.map((r) => <p key={r.idempotency_key} className="mt-2 rounded-lg bg-secondary p-3 text-xs">{r.action}: {r.status} · {r.scope}</p>)}</section>}
          {snapshot.stage === "complete" && <p className="mt-6 rounded-xl border border-primary/40 bg-primary/5 p-4 text-sm text-foreground">Journey complete. The results above are recorded in the audit history.</p>}
        </>
      )}
      {error && <p className="mt-4 text-sm text-destructive">{error}</p>}
    </main>
  );
}
