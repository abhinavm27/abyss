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
  MessageCircle,
  Mic,
  Network,
  Phone,
  Send,
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
import { useVoiceSession } from "@/hooks/useVoiceSession";
import { captureCard } from "@/lib/cardScan";
import { NeuralPath } from "@/vela/NeuralPath";
import { AppointmentsTab, DocumentsTab, PathsTab, PreferencesTab, type VelaAppointment, type VelaDocument } from "@/vela/VelaTabs";

type AppTab = "home" | "paths" | "appointments" | "documents" | "preferences";

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

function useDemoMicrophone() {
  const [active, setActive] = useState(false);
  const [level, setLevel] = useState(0);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const frameRef = useRef(0);
  const stop = () => {
    window.cancelAnimationFrame(frameRef.current);
    streamRef.current?.getTracks().forEach((track) => track.stop());
    void contextRef.current?.close().catch(() => {});
    streamRef.current = null; contextRef.current = null; setActive(false); setLevel(0);
  };
  const start = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const context = new AudioContext(); const analyser = context.createAnalyser(); analyser.fftSize = 256;
    context.createMediaStreamSource(stream).connect(analyser); streamRef.current = stream; contextRef.current = context; setActive(true);
    const values = new Uint8Array(analyser.frequencyBinCount);
    const read = () => { analyser.getByteFrequencyData(values); const average = values.reduce((sum, value) => sum + value, 0) / values.length / 128; setLevel(Math.min(1, average * 1.9)); frameRef.current = window.requestAnimationFrame(read); };
    read();
  };
  useEffect(() => stop, []);
  return { active, level, start, stop };
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

function Sidebar({ scene, tab, onTab, onReset }: { scene: Scene; tab: AppTab; onTab: (tab: AppTab) => void; onReset: () => void }) {
  return (
    <aside className="vela-sidebar">
      <Logo />
      <nav aria-label="Primary">
        <button className={tab === "home" ? "is-current" : ""} onClick={() => { onReset(); onTab("home"); }}><Home />Home</button>
        <button className={`${tab === "paths" ? "is-current" : ""} ${scene === "recommendation" ? "has-update" : ""}`} onClick={() => onTab("paths")}><Network />Paths</button>
        <button className={`${tab === "appointments" ? "is-current" : ""} ${scene === "complete" ? "has-update" : ""}`} onClick={() => onTab("appointments")}><CalendarDays />Appointments</button>
        <button className={tab === "documents" ? "is-current" : ""} onClick={() => onTab("documents")}><FileText />Documents</button>
        <button className={tab === "preferences" ? "is-current" : ""} onClick={() => onTab("preferences")}><Settings />Preferences</button>
      </nav>
      <div className="vela-private"><ShieldCheck /><span>Your data is<br />private and secure</span><i /></div>
    </aside>
  );
}

function MobileHeader({ onReset }: { onReset: () => void }) {
  return <header className="vela-mobile-header"><Logo /><button aria-label="Menu" onClick={onReset}><Menu /></button></header>;
}

function MobileNav({ scene, tab, onTab, onReset }: { scene: Scene; tab: AppTab; onTab: (tab: AppTab) => void; onReset: () => void }) {
  return (
    <nav className="vela-mobile-nav" aria-label="Primary">
      <button className={tab === "home" ? "is-current" : ""} onClick={() => { onReset(); onTab("home"); }}><Home /><span>Home</span></button>
      <button className={`${tab === "paths" ? "is-current" : ""} ${scene === "recommendation" ? "has-update" : ""}`} onClick={() => onTab("paths")}><Network /><span>Paths</span></button>
      <button className={`${tab === "appointments" ? "is-current" : ""} ${scene === "complete" ? "has-update" : ""}`} onClick={() => onTab("appointments")}><CalendarDays /><span>Appointments</span></button>
      <button className={tab === "documents" ? "is-current" : ""} onClick={() => onTab("documents")}><FileText /><span>Documents</span></button>
      <button className={tab === "preferences" ? "is-current" : ""} onClick={() => onTab("preferences")}><CircleEllipsis /><span>More</span></button>
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

type ChatTurn = { role: "user" | "assistant"; text: string };

function ChatPanel({ turns, value, busy, onValue, onSend }: { turns: ChatTurn[]; value: string; busy: boolean; onValue: (value: string) => void; onSend: () => void }) {
  return <section className="vela-chat-panel" aria-label="Chat with VELA"><div className="vela-chat-turns">{turns.slice(-2).map((turn, index) => <div className={`vela-chat-turn is-${turn.role}`} key={`${turn.role}-${index}`}><span>{turn.role === "assistant" ? "VELA" : "You"}</span><p>{turn.text}</p></div>)}{busy && <div className="vela-chat-turn is-assistant is-typing"><span>VELA is reasoning</span><p><i /><i /><i /></p></div>}</div><form onSubmit={(event) => { event.preventDefault(); onSend(); }}><MessageCircle aria-hidden /><input autoFocus type="text" enterKeyHint="send" value={value} onChange={(event) => onValue(event.currentTarget.value)} placeholder="Describe the care you need…" aria-label="Message VELA" /><button type="submit" disabled={!value.trim() || busy} aria-label="Send message"><Send /></button></form><div className="vela-chat-suggestions"><button type="button" onClick={() => onValue("I need a knee MRI and want to understand what it will cost.")}>I need an MRI</button><button type="button" onClick={() => onValue("Help me compare my insurance options.")}>Compare coverage</button></div></section>;
}

function ChatDocumentDock({ busy, onCamera, onUpload }: DocumentPromptProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  return <aside className="vela-chat-document-dock" aria-label="Add coverage documents"><span>Coverage</span><button type="button" onClick={onCamera} disabled={busy} aria-label="Scan insurance card"><Camera /><small>Scan card</small></button><button type="button" onClick={() => inputRef.current?.click()} disabled={busy} aria-label="Upload insurance PDF"><Upload /><small>Upload PDF</small></button><input ref={inputRef} type="file" accept="image/*,.pdf,application/pdf" hidden onChange={(event) => onUpload(event.target.files)} /></aside>;
}

export function VelaExperience() {
  const mobile = useIsMobile();
  const [tab, setTab] = useState<AppTab>("home");
  const [inputMode, setInputMode] = useState<"voice" | "chat">("voice");
  const [scene, setScene] = useState<Scene>(() => {
    const requested = new URLSearchParams(window.location.search).get("scene") as Scene | null;
    return requested && sceneOrder.includes(requested) ? requested : "listening";
  });
  const [busy, setBusy] = useState(false);
  const [journey, setJourney] = useState<CareJourneySnapshot | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [chatValue, setChatValue] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatStarted, setChatStarted] = useState(false);
  const [chatVisualProgress, setChatVisualProgress] = useState(0);
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([{ role: "assistant", text: "Where do you need to go from here? Tell me what care you need and I’ll ask only what changes the recommendation." }]);
  const [documents, setDocuments] = useState<VelaDocument[]>([
    { id: "demo-sbc", name: "Current Plan SBC.pdf", kind: "Summary of Benefits", status: "Verified", added: "Aug 15" },
    { id: "demo-referral", name: "Knee MRI referral.pdf", kind: "Referral", status: "Verified", added: "Aug 15" },
  ]);
  const [appointments, setAppointments] = useState<VelaAppointment[]>([
    { id: "demo-appointment", title: "Knee MRI without contrast", provider: "Northwest Imaging", date: "Tuesday, September 3", time: "10:30 AM", location: "Seattle, WA", cost: 420, status: "Confirmed" },
  ]);
  const [cameraOpen, setCameraOpen] = useState(false);
  const liveMode = import.meta.env.VITE_LIVE_MODE === "true" && Boolean(getToken());
  const voice = useVoiceSession({ onError: (message) => setNotice(message) });
  const demoMic = useDemoMicrophone();
  const index = sceneOrder.indexOf(scene);
  const progress = Math.max(0, index / (sceneOrder.length - 1));
  const copy = sceneCopy[scene];
  const resolved = ["recommendation", "consent", "booking", "complete"].includes(scene);
  const voiceLevel = inputMode === "chat" && chatBusy ? .72 : liveMode ? voice.micLevel : demoMic.level;
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
    voice.disconnect(); demoMic.stop();
    setScene("listening");
    setJourney(null);
    setNotice(null);
    setChatStarted(false);
    setChatVisualProgress(0);
  };

  const begin = async () => {
    if (inputMode === "chat") return;
    try {
      if (liveMode) await voice.connect();
      else await demoMic.start();
      setScene("documents");
    } catch (error) {
      setNotice(error instanceof Error && error.name === "NotAllowedError" ? "Microphone access was denied. You can continue by chat instead." : "Microphone unavailable. You can continue by chat instead.");
      setInputMode("chat");
    }
  };

  const sendChat = async () => {
    const text = chatValue.trim(); if (!text) return;
    setChatStarted(true); setChatVisualProgress((current) => Math.min(.62, current + .08));
    setChatTurns((turns) => [...turns, { role: "user", text }]); setChatValue(""); setChatBusy(true);
    try {
      await new Promise((resolve) => window.setTimeout(resolve, 260)); setChatVisualProgress((current) => Math.min(.68, current + .06));
      await new Promise((resolve) => window.setTimeout(resolve, 340)); setChatVisualProgress((current) => Math.min(.74, current + .07));
      if (liveMode && voice.isActive) voice.sendText(text);
      else if (liveMode) {
        const response = await api.agentChat(text, journey ?? { journey_stage: scene });
        setChatTurns((turns) => [...turns, { role: "assistant", text: response.reply }]);
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 420));
        setChatTurns((turns) => [...turns, { role: "assistant", text: "I can help with that. First, show me your coverage so I can compare the complete cost instead of guessing from the procedure price alone." }]);
      }
      setScene("documents");
      setChatVisualProgress((current) => Math.min(.78, current + .05));
    } catch (error) { setNotice(error instanceof Error ? error.message : "VELA could not send that message."); }
    finally { setChatBusy(false); }
  };

  const handleFiles = async (files: FileList | File[] | null) => {
    const file = files?.[0];
    if (!file) return;
    setBusy(true);
    setNotice(null);
    try {
      const newDocument: VelaDocument = { id: crypto.randomUUID(), name: file.name, kind: file.type.includes("pdf") ? "Summary of Benefits" : "Insurance card", status: "Processing", added: "Just now", preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined };
      setDocuments((items) => [newDocument, ...items]);
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
      setDocuments((items) => items.map((item) => item.id === newDocument.id ? { ...item, status: "Verified" } : item));
      setScene("understanding");
    } catch (error) {
      setDocuments((items) => items.map((item) => item.status === "Processing" ? { ...item, status: "Review needed" } : item));
      setNotice(error instanceof Error ? error.message : "VELA could not read that document.");
    } finally {
      setBusy(false);
    }
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
      {!mobile && <Sidebar scene={scene} tab={tab} onTab={setTab} onReset={reset} />}
      {mobile && <MobileHeader onReset={reset} />}
      {tab === "home" ? <main className={`vela-stage scene-${scene} ${inputMode === "chat" ? "is-chat-mode" : ""}`}>
          <NeuralPath className={inputMode === "chat" && !chatStarted ? "is-hidden" : ""} progress={inputMode === "chat" ? Math.max(chatVisualProgress, chatStarted ? progress : 0, voiceLevel * .55) : Math.max(progress, voiceLevel * .55)} energy={voiceLevel} resolved={resolved} />
          <div className="vela-stage-content">
            <div className="vela-mode-switch"><button type="button" className={inputMode === "voice" ? "is-active" : ""} onClick={() => setInputMode("voice")}><Phone />Call</button><button type="button" className={inputMode === "chat" ? "is-active" : ""} onClick={() => setInputMode("chat")}><MessageCircle />Chat</button></div>
            <p className="vela-eyebrow">{inputMode === "chat" && chatStarted ? "VELA care network" : copy.eyebrow}</p>
            <h1>{(inputMode === "chat" && chatStarted ? "Finding your clearest path." : copy.title).split("\n").map((line, lineIndex, lines) => <span key={line}>{line}{lineIndex < lines.length - 1 && <br />}</span>)}</h1>
            {inputMode === "voice" && <><div className="vela-listener" style={{ "--energy": voiceLevel } as React.CSSProperties}><Waveform /><VoiceOrb active={scene !== "complete"} /><Waveform /></div><p className="vela-status">{voiceLevel > .08 ? "I can hear you…" : copy.status}</p></>}
            {inputMode === "chat" && <ChatPanel turns={chatTurns} value={chatValue} busy={chatBusy} onValue={setChatValue} onSend={sendChat} />}

            {scene === "listening" && inputMode === "voice" && <div className="vela-start"><p>Tell VELA what care you need, or begin with the guided demo.</p><button onClick={() => void begin()}>{(liveMode ? voice.isActive : demoMic.active) ? <><Mic />Listening now</> : <><Mic />Start a care request</>}</button></div>}
            {scene === "documents" && inputMode === "voice" && <><p className="vela-prompt">Scan your insurance card or upload a plan document so I can understand your benefits.</p><DocumentPrompt onCamera={() => { setTab("documents"); setCameraOpen(true); }} onUpload={handleFiles} busy={busy} /></>}
            {["understanding", "context", "working", "verifying"].includes(scene) && <AgentPanel activeCount={agentCount} />}
            {scene === "decision" && <DecisionCard onAnswer={handleDecision} />}
            {scene === "recommendation" && <RecommendationCard onContinue={() => setScene("consent")} onExplain={() => setNotice("VELA compared annual cost, network status, medication coverage, physician preference, and appointment availability. Deterministic rules selected the feasible path; Nemotron explained the evidence.")} />}
            {scene === "consent" && <ConsentCard onApprove={approve} onBack={() => setScene("recommendation")} />}
            {scene === "booking" && <AgentPanel activeCount={4} />}
            {scene === "complete" && <CompleteCard onReset={reset} />}
          </div>
          {inputMode === "chat" && chatStarted && scene === "documents" && <ChatDocumentDock busy={busy} onCamera={() => void captureCard().then((file) => file && handleFiles([file]))} onUpload={handleFiles} />}
          {notice && <div className="vela-notice"><span>{notice}</span><button onClick={() => setNotice(null)} aria-label="Close"><X /></button></div>}
        </main> : <main className="vela-stage vela-tab-stage">
          {tab === "paths" && <PathsTab />}
          {tab === "appointments" && <AppointmentsTab items={appointments} onItems={setAppointments} liveMode={liveMode} />}
          {tab === "documents" && <DocumentsTab documents={documents} onDocuments={setDocuments} liveMode={liveMode} openCamera={cameraOpen} onOpenCamera={setCameraOpen} />}
          {tab === "preferences" && <PreferencesTab />}
        </main>}
      {mobile && <MobileNav scene={scene} tab={tab} onTab={setTab} onReset={reset} />}
    </div>
  );
}
