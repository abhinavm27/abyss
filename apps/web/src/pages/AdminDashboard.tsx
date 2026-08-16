import { Activity, ArrowRight, CircleAlert, Database, Gauge, MessageCircle, Mic, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type AgentSession, type CareJourneySnapshot } from "@/lib/api";

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
  const [view, setView] = useState<"sessions" | "journeys">("sessions");
  const [journeys, setJourneys] = useState<CareJourneySnapshot[]>([]);
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [selected, setSelected] = useState<CareJourneySnapshot | null>(null);
  const [selectedSession, setSelectedSession] = useState<AgentSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  async function refresh() {
    try {
      const [journeyResult, sessionResult] = await Promise.all([
        api.adminJourneys(), api.adminAgentSessions(),
      ]);
      setJourneys(journeyResult.journeys);
      setSessions(sessionResult.sessions);
      setSelected((current) => journeyResult.journeys.find((item) => item.journey_id === current?.journey_id) ?? journeyResult.journeys[0] ?? null);
      setSelectedSession((current) => sessionResult.sessions.find((item) => item.correlation_id === current?.correlation_id) ?? sessionResult.sessions[0] ?? null);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function clearSyntheticData() {
    if (!window.confirm("Clear this synthetic user's journeys, appointments, and agent traces?")) return;
    setClearing(true);
    try { await api.clearDemoData(); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setClearing(false); }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, []);

  const events = useMemo(() => selected?.events ?? [], [selected]);
  const agentEvents = events.filter((event) => event.type.includes("onboarding") || event.type.includes("matching") || event.type.includes("evaluation") || event.type.includes("receipt"));
  const stageIndex = ["intake", "compare", "recommend", "enroll", "transition", "verify", "book", "complete"];
  const failedTurns = sessions.reduce((sum, session) => sum + session.turns.filter((turn) => turn.status === "failed").length, 0);

  return (
    <main className="admin-console">
      <header className="admin-console__header">
        <div><button onClick={onBack} className="admin-console__back">← VELA</button><p className="admin-kicker">Operations / synthetic environment</p><h1>Agent session room</h1><p className="admin-subtitle">Follow each utterance from voice capture through routing, knowledge, matching, consent, and deterministic execution.</p></div>
        <div className="admin-header-actions"><button onClick={() => void refresh()} className="admin-refresh"><Activity size={16} /> Live · 3s</button><button disabled={clearing} onClick={() => void clearSyntheticData()} className="admin-clear"><Trash2 size={15} />{clearing ? "Clearing…" : "Clear synthetic data"}</button></div>
      </header>
      <nav className="admin-view-switch" aria-label="Admin data view"><button className={view === "sessions" ? "is-active" : ""} onClick={() => setView("sessions")}><Mic size={15} /> Agent sessions</button><button className={view === "journeys" ? "is-active" : ""} onClick={() => setView("journeys")}><Database size={15} /> Care journeys</button></nav>
      <section className="admin-metrics"><div><span><Mic size={15} /> Voice sessions</span><b>{sessions.filter((item) => item.channel === "voice").length}</b></div><div><span><CircleAlert size={15} /> Failed turns</span><b>{failedTurns}</b></div><div><span><Gauge size={15} /> Active journeys</span><b>{journeys.filter((item) => item.stage !== "complete").length}</b></div><div><span><ShieldCheck size={15} /> Sandbox receipts</span><b>{journeys.reduce((sum, item) => sum + item.receipts.length, 0)}</b></div></section>

      {view === "sessions" ? <div className="admin-layout">
        <aside className="admin-journeys"><div className="admin-section-title"><span>Agent sessions</span><small>{sessions.length} total</small></div>{sessions.map((session) => <button key={session.correlation_id} onClick={() => setSelectedSession(session)} className={`admin-journey ${selectedSession?.correlation_id === session.correlation_id ? "admin-journey--selected" : ""}`}><span className={`admin-status-dot status-${session.status}`} /><span><b>{session.channel === "voice" ? "Voice" : "Chat"} · {session.turns.length} turn{session.turns.length === 1 ? "" : "s"}</b><small>{session.status} · {new Date(session.updated_at).toLocaleTimeString()}</small></span><ArrowRight size={15} /></button>)}{sessions.length === 0 && <p className="admin-empty">No agent sessions yet. Start a voice or chat request from VELA.</p>}</aside>
        <section className="admin-detail">{selectedSession ? <><div className="admin-detail__top"><div><p className="admin-kicker">Correlation</p><h2>{selectedSession.correlation_id}</h2></div><span className={`admin-stage status-${selectedSession.status}`}>{selectedSession.status}</span></div><div className="admin-session-meta"><span>{selectedSession.channel === "voice" ? <Mic /> : <MessageCircle />} {selectedSession.channel}</span><span>{selectedSession.turns.length} utterances</span><span>{new Date(selectedSession.started_at).toLocaleString()}</span></div><div className="admin-turns">{selectedSession.turns.map((turn, index) => { const plan = "steps" in turn.plan ? turn.plan : null; return <article className={`admin-turn status-${turn.status}`} key={turn.utterance_id}><div className="admin-turn__rail"><i>{String(index + 1).padStart(2, "0")}</i><span /></div><div><header><b>{turn.intent.replace(/_/g, " ")}</b><small>{turn.status} · {new Date(turn.created_at).toLocaleTimeString()}</small></header><blockquote>“{turn.message}”</blockquote>{plan && <div className="admin-plan-flow"><span>Care Journey Agent</span>{plan.steps.map((step) => <span key={step}>{step.replace(/_/g, " ")}</span>)}</div>}{turn.journey_id && <p>Journey: {turn.journey_id}</p>}{turn.error && <div className="admin-turn-error"><CircleAlert />{turn.error}</div>}</div></article>; })}</div></> : <div className="admin-empty admin-empty--large"><CircleAlert size={24} />Select a session to inspect every agent turn.</div>}</section>
      </div> : <div className="admin-layout">
        <aside className="admin-journeys"><div className="admin-section-title"><span>Care journeys</span><small>{journeys.length} total</small></div>{journeys.map((journey) => <button key={journey.journey_id} onClick={() => setSelected(journey)} className={`admin-journey ${selected?.journey_id === journey.journey_id ? "admin-journey--selected" : ""}`}><span className="admin-status-dot" /><span><b>{journey.journey_id}</b><small>{journey.stage} · {journey.receipts.length} receipts</small></span><ArrowRight size={15} /></button>)}{journeys.length === 0 && <p className="admin-empty">No synthetic journeys yet. Start one from the member app.</p>}</aside>
        <section className="admin-detail">{selected ? <><div className="admin-detail__top"><div><p className="admin-kicker">Selected journey</p><h2>{selected.journey_id}</h2></div><span className="admin-stage">{selected.stage}</span></div><div className="admin-stagebar">{stageIndex.map((stage, index) => <div key={stage} className={index <= stageIndex.indexOf(selected.stage) ? "is-done" : ""}><i />{stage}</div>)}</div><div className="admin-agent-grid"><div className="admin-panel"><div className="admin-panel__title"><span>Agent handoffs</span><small>ordered by event time</small></div>{agentEvents.length ? agentEvents.map((event) => <div className={`admin-node ${tone[event.type] ?? ""}`} key={`${event.sequence}-${event.type}`}><span className="admin-node__icon">{event.type.includes("receipt") ? "↗" : "◆"}</span><div><b>{label[event.type] ?? event.type}</b><small>{event.actor} · {new Date(event.recorded_at).toLocaleTimeString()}</small></div></div>) : <p className="admin-empty">Agent activity appears as the journey progresses.</p>}</div><div className="admin-panel"><div className="admin-panel__title"><span>Evaluation signal</span><small>deterministic</small></div>{selected.evaluations.map((evaluation) => <div className="admin-eval" key={evaluation.plan_id}><div><b>{evaluation.plan_name}</b><small>{evaluation.feasible ? "feasible path" : evaluation.hard_failures.join(" · ")}</small></div><strong>{evaluation.feasible ? `$${evaluation.annual_total.toLocaleString()}` : "—"}</strong></div>)}</div></div><div className="admin-panel admin-audit"><div className="admin-panel__title"><span>Audit stream</span><small>{events.length} events</small></div>{events.slice().reverse().map((event) => <div className="admin-event" key={`${event.sequence}-${event.type}`}><span>{String(event.sequence).padStart(2, "0")}</span><b>{label[event.type] ?? event.type}</b><small>{event.actor} · {new Date(event.recorded_at).toLocaleString()}</small></div>)}</div></> : <div className="admin-empty admin-empty--large"><CircleAlert size={24} />Select a journey to inspect its flow.</div>}</section>
      </div>}
      {error && <p className="admin-error">{error}</p>}
    </main>
  );
}
