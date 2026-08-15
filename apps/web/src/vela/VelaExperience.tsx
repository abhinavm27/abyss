import {
  Building2,
  CalendarDays,
  Camera,
  Check,
  ChevronRight,
  CircleEllipsis,
  FileText,
  Home,
  LockKeyhole,
  Menu,
  Mic,
  Network,
  Settings,
  ShieldCheck,
  Sparkles,
  Tag,
  Upload,
  WalletCards,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, getToken, type CareJourneySnapshot } from "@/lib/api";
import { captureCard } from "@/lib/cardScan";
import { NeuralPath } from "@/vela/NeuralPath";

type Scene =
  | "listening"
  | "documents"
  | "understanding"
  | "context"
  | "working"
  | "decision"
  | "verifying"
  | "recommendation"
  | "consent"
  | "booking"
  | "complete";

const sceneOrder: Scene[] = [
  "listening",
  "documents",
  "understanding",
  "context",
  "working",
  "decision",
  "verifying",
  "recommendation",
  "consent",
  "booking",
  "complete",
];

const sceneCopy: Record<Scene, { title: string; eyebrow: string; status: string }> = {
  listening: { title: "Where do you need\nto go from here?", eyebrow: "", status: "I’m listening." },
  documents: { title: "Show me your coverage.", eyebrow: "A clearer answer starts with your plan", status: "I’m listening." },
  understanding: { title: "I understand what\nyou need.", eyebrow: "Knee MRI without contrast", status: "Building your care request" },
  context: { title: "I’m connecting the\ndetails.", eyebrow: "Coverage, timing, doctors, and prescriptions", status: "Adding your context" },
  working: { title: "I’m finding every\nviable path.", eyebrow: "Four bounded agents are working", status: "Comparing your options" },
  decision: { title: "One detail changes\nthe recommendation.", eyebrow: "Your approval is always required", status: "Waiting for your answer" },
  verifying: { title: "I’m verifying the\nbest options.", eyebrow: "Checking networks, total cost, and availability", status: "Verifying source facts" },
  recommendation: { title: "Your best path", eyebrow: "Verified against your priorities", status: "I found a better path" },
  consent: { title: "Your approval is\nrequired to continue.", eyebrow: "Nothing consequential happens without you", status: "Review the exact action" },
  booking: { title: "I’m securing your\nappointment.", eyebrow: "Your approved path is in motion", status: "Booking in the sandbox" },
  complete: { title: "Your appointment\nis booked.", eyebrow: "Every step is recorded", status: "You’re all set" },
};

const agentSteps = [
  { name: "Onboarding", detail: "Care request understood" },
  { name: "Knowledge", detail: "Coverage facts sourced" },
  { name: "Matching", detail: "Three paths evaluated" },
  { name: "Scheduler", detail: "Appointment verified" },
];

function useIsMobile() {
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 760px)").matches);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 760px)");
    const update = () => setMobile(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return mobile;
}

function Logo() {
  return <span className="vela-logo" aria-label="VELA">VELA</span>;
}

function VoiceOrb({ active = true }: { active?: boolean }) {
  return (
    <div className={`vela-orb ${active ? "is-active" : ""}`} aria-hidden>
      <i /><i /><i />
      <span />
    </div>
  );
}

function Waveform() {
  return <div className="vela-wave" aria-hidden>{Array.from({ length: 56 }, (_, index) => <i key={index} style={{ "--h": `${3 + ((index * 7) % 18)}px` } as React.CSSProperties} />)}</div>;
}

function Sidebar({ scene, onReset }: { scene: Scene; onReset: () => void }) {
  return (
    <aside className="vela-sidebar">
      <Logo />
      <nav aria-label="Primary">
        <button className="is-current" onClick={onReset}><Home />Home</button>
        <button className={scene === "recommendation" ? "has-update" : ""}><Network />Paths</button>
        <button className={scene === "complete" ? "has-update" : ""}><CalendarDays />Appointments</button>
        <button><FileText />Documents</button>
        <button><Settings />Preferences</button>
      </nav>
      <div className="vela-private"><ShieldCheck /><span>Your data is<br />private and secure</span><i /></div>
    </aside>
  );
}

function MobileHeader({ onReset }: { onReset: () => void }) {
  return <header className="vela-mobile-header"><Logo /><button aria-label="Menu" onClick={onReset}><Menu /></button></header>;
}

function MobileNav({ scene, onReset }: { scene: Scene; onReset: () => void }) {
  return (
    <nav className="vela-mobile-nav" aria-label="Primary">
      <button className="is-current" onClick={onReset}><Home /><span>Home</span></button>
      <button className={scene === "recommendation" ? "has-update" : ""}><Network /><span>Paths</span></button>
      <button className={scene === "complete" ? "has-update" : ""}><CalendarDays /><span>Appointments</span></button>
      <button><FileText /><span>Documents</span></button>
      <button><CircleEllipsis /><span>More</span></button>
    </nav>
  );
}

type DocumentPromptProps = {
  onCamera: () => void;
  onUpload: (files: FileList | null) => void;
  busy: boolean;
};

function DocumentPrompt({ onCamera, onUpload, busy }: DocumentPromptProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <section className="vela-document-card" aria-label="Add coverage documents">
      <button onClick={onCamera} disabled={busy}><Camera /><span>Scan with camera</span><ChevronRight /></button>
      <button onClick={() => inputRef.current?.click()} disabled={busy}><Upload /><span>Upload documents</span><ChevronRight /></button>
      <input ref={inputRef} type="file" accept="image/*,.pdf,application/pdf" multiple hidden onChange={(event) => onUpload(event.target.files)} />
      <small>{busy ? "Reading your coverage…" : "Insurance cards, SBCs, and PDFs are supported."}</small>
    </section>
  );
}

function AgentPanel({ activeCount }: { activeCount: number }) {
  return (
    <section className="vela-agent-panel">
      <div className="vela-agent-heading"><Sparkles /><span>VELA’s agents</span><b>{activeCount < 4 ? "working" : "complete"}</b></div>
      {agentSteps.map((agent, index) => (
        <div className={`vela-agent-row ${index < activeCount ? "is-done" : index === activeCount ? "is-active" : ""}`} key={agent.name}>
          <span>{index < activeCount ? <Check /> : <i />}</span>
          <div><b>{agent.name}</b><small>{agent.detail}</small></div>
        </div>
      ))}
    </section>
  );
}

function DecisionCard({ onAnswer }: { onAnswer: () => void }) {
  return (
    <section className="vela-decision-card">
      <span className="vela-card-kicker">One question</span>
      <h2>Is keeping Dr. Lee essential?</h2>
      <p>One lower cost path uses a different physician. Your answer changes which option VELA can recommend.</p>
      <div><button onClick={onAnswer}>Yes, keep Dr. Lee</button><button onClick={onAnswer}>Show me both options</button></div>
    </section>
  );
}

function RecommendationCard({ onContinue, onExplain }: { onContinue: () => void; onExplain: () => void }) {
  return (
    <section className="vela-recommendation-card">
      <div className="vela-verified"><Check /></div>
      <h2>Keep your current insurance</h2>
      <p><Building2 />Northwest Imaging</p>
      <p><CalendarDays />Tuesday at 10:30 AM</p>
      <hr />
      <p><WalletCards />Estimated responsibility: $420</p>
      <p className="is-savings"><Tag />Potential savings: $1,060</p>
      <hr />
      <p><ShieldCheck />Prior authorization required</p>
      <p><Network />Confidence: <em>High</em></p>
      <button className="vela-primary" onClick={onContinue}>Review and continue</button>
      <button className="vela-secondary" onClick={onExplain}>See how VELA decided</button>
    </section>
  );
}

function ConsentCard({ onApprove, onBack }: { onApprove: () => void; onBack: () => void }) {
  return (
    <section className="vela-consent-card">
      <div className="vela-consent-icon"><LockKeyhole /></div>
      <h2>Your approval is required to continue.</h2>
      <p>VELA is ready to schedule with the recommended provider on your behalf.</p>
      <div className="vela-consent-list">
        <b>What VELA will do</b>
        <span><Check />Share relevant information with the provider</span>
        <span><Check />Request the next available appointment</span>
        <span><Check />Receive and manage appointment details</span>
      </div>
      <button className="vela-approve" onClick={onApprove}>Approve and continue</button>
      <button className="vela-review" onClick={onBack}>Review details</button>
    </section>
  );
}

function CompleteCard({ onReset }: { onReset: () => void }) {
  return (
    <section className="vela-complete-card">
      <div className="vela-verified"><Check /></div>
      <h2>Your appointment is booked.</h2>
      <p>Northwest Imaging<br />Tuesday at 10:30 AM</p>
      <small>Sandbox confirmation VELA 1042<br />Receipt saved to your audit history</small>
      <button className="vela-primary" onClick={onReset}>Return home</button>
    </section>
  );
}

export function VelaExperience() {
  const mobile = useIsMobile();
  const [scene, setScene] = useState<Scene>(() => {
    const requested = new URLSearchParams(window.location.search).get("scene") as Scene | null;
    return requested && sceneOrder.includes(requested) ? requested : "listening";
  });
  const [busy, setBusy] = useState(false);
  const [journey, setJourney] = useState<CareJourneySnapshot | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const liveMode = import.meta.env.VITE_LIVE_MODE === "true" && Boolean(getToken());
  const index = sceneOrder.indexOf(scene);
  const progress = Math.max(0, index / (sceneOrder.length - 1));
  const copy = sceneCopy[scene];
  const resolved = ["recommendation", "consent", "booking", "complete"].includes(scene);
  const agentCount = useMemo(() => {
    if (scene === "working") return 2;
    if (["decision", "verifying"].includes(scene)) return 3;
    if (index >= sceneOrder.indexOf("recommendation")) return 4;
    return Math.max(0, index - 1);
  }, [index, scene]);

  useEffect(() => {
    if (scene !== "understanding" && scene !== "context" && scene !== "working" && scene !== "verifying" && scene !== "booking") return;
    const next: Partial<Record<Scene, Scene>> = {
      understanding: "context",
      context: "working",
      working: "decision",
      verifying: "recommendation",
      booking: "complete",
    };
    const timer = window.setTimeout(() => setScene(next[scene] ?? scene), scene === "working" ? 2400 : 1650);
    return () => window.clearTimeout(timer);
  }, [scene]);

  const reset = () => {
    setScene("listening");
    setJourney(null);
    setNotice(null);
  };

  const begin = () => setScene("documents");

  const handleFiles = async (files: FileList | File[] | null) => {
    const file = files?.[0];
    if (!file) return;
    setBusy(true);
    setNotice(null);
    try {
      if (liveMode) {
        const started = journey ?? await api.startJourney();
        setJourney(started);
        if (file.type.startsWith("image/")) await api.scanCard(file);
        else await api.parseSbc(file);
        const consented = await api.journeyConsent(started.journey_id, {
          action: "process_documents",
          scope: `coverage document ${file.name}`,
          approved: true,
        });
        setJourney(consented);
      }
      setScene("understanding");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "VELA could not read that document.");
    } finally {
      setBusy(false);
    }
  };

  const handleCamera = async () => {
    const file = await captureCard();
    if (file) await handleFiles([file]);
  };

  const handleDecision = async () => {
    setBusy(true);
    try {
      if (liveMode && journey) {
        const onboarded = await api.journeyOnboard(journey.journey_id, "Keep Dr. Lee. MRI knee without contrast on September 4, 2026. Coverage ends August 31, 2026.");
        const compared = await api.journeyCompare(onboarded.journey_id);
        setJourney(compared);
      }
      setScene("verifying");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "VELA could not compare the paths.");
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    setBusy(true);
    try {
      if (liveMode && journey) {
        let current = journey;
        if (current.stage === "recommend") current = await api.journeyAdvance(current.journey_id);
        const consented = await api.journeyConsent(current.journey_id, {
          action: "enroll_plan",
          scope: "recommended care path",
          approved: true,
        });
        const actioned = await api.journeyAction(consented.journey_id, {
          action: "enroll_plan",
          scope: "recommended care path",
          idempotency_key: `vela-enroll-${consented.journey_id}`,
        });
        setJourney(actioned);
      }
      setScene("booking");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The approved action could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`vela-shell ${mobile ? "is-mobile" : "is-desktop"}`}>
      {!mobile && <Sidebar scene={scene} onReset={reset} />}
      {mobile && <MobileHeader onReset={reset} />}
      <main className={`vela-stage scene-${scene}`}>
        <NeuralPath progress={progress} resolved={resolved} />
        <div className="vela-stage-content">
          <p className="vela-eyebrow">{copy.eyebrow}</p>
          <h1>{copy.title.split("\n").map((line, lineIndex) => <span key={line}>{line}{lineIndex < copy.title.split("\n").length - 1 && <br />}</span>)}</h1>
          <div className="vela-listener"><Waveform /><VoiceOrb active={scene !== "complete"} /><Waveform /></div>
          <p className="vela-status">{copy.status}</p>

          {scene === "listening" && (
            <div className="vela-start">
              <p>Tell VELA what care you need, or begin with the guided demo.</p>
              <button onClick={begin}><Mic />Start a care request</button>
            </div>
          )}
          {scene === "documents" && (
            <>
              <p className="vela-prompt">Scan your insurance card or upload a plan document so I can understand your benefits.</p>
              <DocumentPrompt onCamera={handleCamera} onUpload={handleFiles} busy={busy} />
            </>
          )}
          {["understanding", "context", "working", "verifying"].includes(scene) && <AgentPanel activeCount={agentCount} />}
          {scene === "decision" && <DecisionCard onAnswer={handleDecision} />}
          {scene === "recommendation" && <RecommendationCard onContinue={() => setScene("consent")} onExplain={() => setNotice("VELA compared annual cost, network status, medication coverage, physician preference, and appointment availability. Deterministic rules selected the feasible path; Nemotron explained the evidence.")} />}
          {scene === "consent" && <ConsentCard onApprove={approve} onBack={() => setScene("recommendation")} />}
          {scene === "booking" && <AgentPanel activeCount={4} />}
          {scene === "complete" && <CompleteCard onReset={reset} />}
        </div>
        {notice && <div className="vela-notice"><span>{notice}</span><button onClick={() => setNotice(null)} aria-label="Close"><X /></button></div>}
      </main>
      {mobile && <MobileNav scene={scene} onReset={reset} />}
    </div>
  );
}
