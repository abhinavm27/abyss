import { Activity, ArrowRight, CheckCircle2, CircleAlert, Clock3, Database, Gauge, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type CareJourneySnapshot } from "@/lib/api";

const label: Record<string, string> = {
  onboarding_completed: "Onboarding Agent → Fact Ledger",
  matching_requested: "Care Journey Engine → Matching Agent",
  evaluation_completed: "Matching Agent → Deterministic Evaluator",
  consent_recorded: "User → Consent Gate",
  stage_advanced: "Journey State Transition",
  fact_recorded: "Fact Ledger ← Agent / User",
  sandbox_receipt: "Sandbox Adapter → Receipt Ledger",
};

const tone: Record<string, string> = {
  onboarding_completed: "admin-node--cyan",
  matching_requested: "admin-node--amber",
  evaluation_completed: "admin-node--lime",
  consent_recorded: "admin-node--violet",
  sandbox_receipt: "admin-node--green",
};

export function AdminDashboard({ onBack }: { onBack: () => void }) {
  const [journeys, setJourneys] = useState<CareJourneySnapshot[]>([]);
  const [selected, setSelected] = useState<CareJourneySnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const result = await api.adminJourneys();
      setJourneys(result.journeys);
      setSelected((current) => result.journeys.find((item) => item.journey_id === current?.journey_id) ?? result.journeys[0] ?? null);
      setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 5000); return () => window.clearInterval(timer); }, []);

  const events = useMemo(() => selected?.events ?? [], [selected]);
  const agentEvents = events.filter((event) => event.type.includes("onboarding") || event.type.includes("matching") || event.type.includes("evaluation") || event.type.includes("receipt"));
  const stageIndex = ["intake", "compare", "recommend", "enroll", "transition", "verify", "book", "complete"];

  return (
    <main className="admin-console">
      <header className="admin-console__header">
        <div><button onClick={onBack} className="admin-console__back">← ABYSS</button><p className="admin-kicker">Operations / synthetic environment</p><h1>Journey control room</h1><p className="admin-subtitle">Watch facts become decisions, approvals become actions, and every handoff leave a trace.</p></div>
        <button onClick={() => void refresh()} className="admin-refresh"><Activity size={16} /> Live · 5s</button>
      </header>
      <section className="admin-metrics"><div><span><Gauge size={15} /> Active journeys</span><b>{journeys.filter((item) => item.stage !== "complete").length}</b></div><div><span><CheckCircle2 size={15} /> Completed</span><b>{journeys.filter((item) => item.stage === "complete").length}</b></div><div><span><ShieldCheck size={15} /> Sandbox receipts</span><b>{journeys.reduce((sum, item) => sum + item.receipts.length, 0)}</b></div><div><span><Database size={15} /> Audit events</span><b>{journeys.reduce((sum, item) => sum + item.events.length, 0)}</b></div></section>
      <div className="admin-layout">
        <aside className="admin-journeys"><div className="admin-section-title"><span>Care journeys</span><small>{journeys.length} total</small></div>{journeys.map((journey) => <button key={journey.journey_id} onClick={() => setSelected(journey)} className={`admin-journey ${selected?.journey_id === journey.journey_id ? "admin-journey--selected" : ""}`}><span className="admin-status-dot" /><span><b>{journey.journey_id}</b><small>{journey.stage} · {journey.receipts.length} receipts</small></span><ArrowRight size={15} /></button>)}{journeys.length === 0 && <p className="admin-empty">No synthetic journeys yet. Start one from the member app.</p>}</aside>
        <section className="admin-detail">{selected ? <><div className="admin-detail__top"><div><p className="admin-kicker">Selected journey</p><h2>{selected.journey_id}</h2></div><span className="admin-stage">{selected.stage}</span></div><div className="admin-stagebar">{stageIndex.map((stage, index) => <div key={stage} className={index <= stageIndex.indexOf(selected.stage) ? "is-done" : ""}><i />{stage}</div>)}</div><div className="admin-agent-grid"><div className="admin-panel"><div className="admin-panel__title"><span>Agent handoffs</span><small>ordered by event time</small></div>{agentEvents.length ? agentEvents.map((event) => <div className={`admin-node ${tone[event.type] ?? ""}`} key={`${event.sequence}-${event.type}`}><span className="admin-node__icon">{event.type.includes("receipt") ? "↗" : "◆"}</span><div><b>{label[event.type] ?? event.type}</b><small>{event.actor} · {new Date(event.recorded_at).toLocaleTimeString()}</small></div></div>) : <p className="admin-empty">Agent activity appears as the journey progresses.</p>}</div><div className="admin-panel"><div className="admin-panel__title"><span>Evaluation signal</span><small>deterministic</small></div>{selected.evaluations.map((evaluation) => <div className="admin-eval" key={evaluation.plan_id}><div><b>{evaluation.plan_name}</b><small>{evaluation.feasible ? "feasible path" : evaluation.hard_failures.join(" · ")}</small></div><strong>{evaluation.feasible ? `$${evaluation.annual_total.toLocaleString()}` : "—"}</strong></div>)}</div></div><div className="admin-panel admin-audit"><div className="admin-panel__title"><span>Audit stream</span><small>{events.length} events</small></div>{events.slice().reverse().map((event) => <div className="admin-event" key={`${event.sequence}-${event.type}`}><span>{String(event.sequence).padStart(2, "0")}</span><b>{label[event.type] ?? event.type}</b><small>{event.actor} · {new Date(event.recorded_at).toLocaleString()}</small></div>)}</div></> : <div className="admin-empty admin-empty--large"><CircleAlert size={24} />Select a journey to inspect its flow.</div>}</section>
      </div>
      {error && <p className="admin-error">{error}</p>}
    </main>
  );
}
