import { Building2, CalendarDays, Camera, Check, CircleEllipsis, FileText, Home, LockKeyhole, Menu, MessageCircle, Mic, Network, Phone, Send, Settings, ShieldCheck, Sparkles, Upload, WalletCards, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, getToken, type CareAgentResponse, type CareContext, type CareJourneySnapshot } from "@/lib/api";
import { VOICE_LABEL, useVoiceSession } from "@/hooks/useVoiceSession";
import { captureCard } from "@/lib/cardScan";
import { NeuralPath } from "@/vela/NeuralPath";
import { AppointmentsTab, DocumentsTab, PathsTab, PreferencesTab, type VelaAppointment, type VelaDocument } from "@/vela/VelaTabs";

type AppTab = "home" | "paths" | "appointments" | "documents" | "preferences";

type Scene = "listening" | "documents" | "understanding" | "context" | "working" | "decision" | "verifying" | "recommendation" | "consent" | "booking" | "complete";

const sceneOrder: Scene[] = ["listening", "documents", "understanding", "context", "working", "decision", "verifying", "recommendation", "consent", "booking", "complete"];

function sceneForJourney(journey: CareJourneySnapshot | null): Scene {
  if (!journey) return "listening";
  if (journey.stage === "intake") return "understanding";
  if (journey.stage === "compare") return "working";
  if (journey.stage === "recommend") return "recommendation";
  if (journey.stage === "verify") return "consent";
  if (journey.stage === "book") return "booking";
  if (journey.stage === "complete") return "complete";
  return "context";
}

const sceneCopy: Record<Scene, { title: string; eyebrow: string; status: string }> = {
  listening: {
    title: "Where do you need\nto go from here?",
    eyebrow: "",
    status: "I’m listening.",
  },
  documents: {
    title: "Show me your coverage.",
    eyebrow: "A clearer answer starts with your plan",
    status: "I’m listening.",
  },
  understanding: {
    title: "I understand what\nyou need.",
    eyebrow: "Knee MRI without contrast",
    status: "Building your care request",
  },
  context: {
    title: "I’m connecting the\ndetails.",
    eyebrow: "Coverage, timing, doctors, and prescriptions",
    status: "Adding your context",
  },
  working: {
    title: "I’m finding every\nviable path.",
    eyebrow: "Four bounded agents are working",
    status: "Comparing your options",
  },
  decision: {
    title: "One detail changes\nthe recommendation.",
    eyebrow: "Your approval is always required",
    status: "Waiting for your answer",
  },
  verifying: {
    title: "I’m verifying the\nbest options.",
    eyebrow: "Checking networks, total cost, and availability",
    status: "Verifying source facts",
  },
  recommendation: {
    title: "Your best path",
    eyebrow: "Verified against your priorities",
    status: "I found a better path",
  },
  consent: {
    title: "Your approval is\nrequired to continue.",
    eyebrow: "Nothing consequential happens without you",
    status: "Review the exact action",
  },
  booking: {
    title: "I’m securing your\nappointment.",
    eyebrow: "Your approved path is in motion",
    status: "Booking in the sandbox",
  },
  complete: {
    title: "Your appointment\nis booked.",
    eyebrow: "Every step is recorded",
    status: "You’re all set",
  },
};

const agentSteps = [
  { name: "Onboarding", detail: "Extract request facts" },
  { name: "Knowledge", detail: "Resolve catalog evidence" },
  { name: "Matching", detail: "Rank current-plan hospitals" },
  { name: "Scheduler", detail: "Prepare booking handoff" },
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
    streamRef.current = null;
    contextRef.current = null;
    setActive(false);
    setLevel(0);
  };
  const start = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    context.createMediaStreamSource(stream).connect(analyser);
    streamRef.current = stream;
    contextRef.current = context;
    setActive(true);
    const values = new Uint8Array(analyser.frequencyBinCount);
    const read = () => {
      analyser.getByteFrequencyData(values);
      const average = values.reduce((sum, value) => sum + value, 0) / values.length / 128;
      setLevel(Math.min(1, average * 1.9));
      frameRef.current = window.requestAnimationFrame(read);
    };
    read();
  };
  useEffect(() => stop, []);
  return { active, level, start, stop };
}

function Logo() {
  return (
    <span className="vela-logo" aria-label="VELA">
      VELA
    </span>
  );
}

function VoiceOrb({ active = true }: { active?: boolean }) {
  return (
    <div className={`vela-orb ${active ? "is-active" : ""}`} aria-hidden>
      <i />
      <i />
      <i />
      <span />
    </div>
  );
}

function Waveform() {
  return (
    <div className="vela-wave" aria-hidden>
      {Array.from({ length: 56 }, (_, index) => (
        <i key={index} style={{ "--h": `${3 + ((index * 7) % 18)}px` } as React.CSSProperties} />
      ))}
    </div>
  );
}

function Sidebar({ scene, tab, onTab, onReset }: { scene: Scene; tab: AppTab; onTab: (tab: AppTab) => void; onReset: () => void }) {
  return (
    <aside className="vela-sidebar">
      <Logo />
      <nav aria-label="Primary">
        <button
          className={tab === "home" ? "is-current" : ""}
          onClick={() => {
            onReset();
            onTab("home");
          }}
        >
          <Home />
          Home
        </button>
        <button className={`${tab === "paths" ? "is-current" : ""} ${scene === "recommendation" ? "has-update" : ""}`} onClick={() => onTab("paths")}>
          <Network />
          Paths
        </button>
        <button className={`${tab === "appointments" ? "is-current" : ""} ${scene === "complete" ? "has-update" : ""}`} onClick={() => onTab("appointments")}>
          <CalendarDays />
          Appointments
        </button>
        <button className={tab === "documents" ? "is-current" : ""} onClick={() => onTab("documents")}>
          <FileText />
          Documents
        </button>
        <button className={tab === "preferences" ? "is-current" : ""} onClick={() => onTab("preferences")}>
          <Settings />
          Preferences
        </button>
      </nav>
      <div className="vela-private">
        <ShieldCheck />
        <span>
          Your data is
          <br />
          private and secure
        </span>
        <i />
      </div>
    </aside>
  );
}

function MobileHeader({ onReset }: { onReset: () => void }) {
  return (
    <header className="vela-mobile-header">
      <Logo />
      <button aria-label="Menu" onClick={onReset}>
        <Menu />
      </button>
    </header>
  );
}

function MobileNav({ scene, tab, onTab, onReset }: { scene: Scene; tab: AppTab; onTab: (tab: AppTab) => void; onReset: () => void }) {
  return (
    <nav className="vela-mobile-nav" aria-label="Primary">
      <button
        className={tab === "home" ? "is-current" : ""}
        onClick={() => {
          onReset();
          onTab("home");
        }}
      >
        <Home />
        <span>Home</span>
      </button>
      <button className={`${tab === "paths" ? "is-current" : ""} ${scene === "recommendation" ? "has-update" : ""}`} onClick={() => onTab("paths")}>
        <Network />
        <span>Paths</span>
      </button>
      <button className={`${tab === "appointments" ? "is-current" : ""} ${scene === "complete" ? "has-update" : ""}`} onClick={() => onTab("appointments")}>
        <CalendarDays />
        <span>Appointments</span>
      </button>
      <button className={tab === "documents" ? "is-current" : ""} onClick={() => onTab("documents")}>
        <FileText />
        <span>Documents</span>
      </button>
      <button className={tab === "preferences" ? "is-current" : ""} onClick={() => onTab("preferences")}>
        <CircleEllipsis />
        <span>More</span>
      </button>
    </nav>
  );
}

type DocumentPromptProps = {
  onCamera: () => void;
  onUpload: (files: FileList | null) => void;
  busy: boolean;
};

function AgentPanel({ activeCount }: { activeCount: number }) {
  return (
    <section className="vela-agent-panel">
      <div className="vela-agent-heading">
        <Sparkles />
        <span>VELA’s agents</span>
        <b>{activeCount < 4 ? "working" : "complete"}</b>
      </div>
      {agentSteps.map((agent, index) => (
        <div className={`vela-agent-row ${index < activeCount ? "is-done" : index === activeCount ? "is-active" : ""}`} key={agent.name}>
          <span>{index < activeCount ? <Check /> : <i />}</span>
          <div>
            <b>{agent.name}</b>
            <small>{agent.detail}</small>
          </div>
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
      <div>
        <button onClick={onAnswer}>Yes, keep Dr. Lee</button>
        <button onClick={onAnswer}>Show me both options</button>
      </div>
    </section>
  );
}

function RecommendationCard({ journey, onContinue, onExplain }: { journey: CareJourneySnapshot; onContinue: () => void; onExplain: () => void }) {
  const option = journey.current_plan_options[0];
  return (
    <section className="vela-recommendation-card">
      <div className="vela-verified">
        <Check />
      </div>
      <h2>Keep {journey.current_plan_name}</h2>
      <p>
        <Building2 />
        {option?.hospital ?? "Hospital options ready"}
      </p>
      <p>
        <CalendarDays />
        {journey.current_plan_options.length} current-plan option
        {journey.current_plan_options.length === 1 ? "" : "s"}
      </p>
      <hr />
      <p>
        <WalletCards />
        Lowest member-cost scenario: {option ? `$${option.estimated_member_cost.toLocaleString()}` : "pending"}
      </p>
      <hr />
      <p>
        <ShieldCheck />
        Network verification follows selection
      </p>
      <p>
        <Network />
        Insurance change: <em>None</em>
      </p>
      <button className="vela-primary" onClick={onContinue}>
        Compare hospitals
      </button>
      <button className="vela-secondary" onClick={onExplain}>
        See how VELA decided
      </button>
    </section>
  );
}

type ConsentCopy = {
  title: string;
  description: string;
  items: string[];
  button: string;
};

function ConsentCard({ copy, onApprove, onBack }: { copy: ConsentCopy; onApprove: () => void; onBack: () => void }) {
  return (
    <section className="vela-consent-card">
      <div className="vela-consent-icon">
        <LockKeyhole />
      </div>
      <h2>{copy.title}</h2>
      <p>{copy.description}</p>
      <div className="vela-consent-list">
        <b>What VELA will do</b>
        {copy.items.map((item) => (
          <span key={item}>
            <Check />
            {item}
          </span>
        ))}
      </div>
      <button className="vela-approve" onClick={onApprove}>
        {copy.button}
      </button>
      <button className="vela-review" onClick={onBack}>
        Review details
      </button>
    </section>
  );
}

function CompleteCard({ journey, onAppointments, onReset }: { journey: CareJourneySnapshot; onAppointments: () => void; onReset: () => void }) {
  const slot = journey.selected_booking_slot;
  return (
    <section className="vela-complete-card">
      <div className="vela-verified">
        <Check />
      </div>
      <h2>Your appointment is booked.</h2>
      <p>
        {slot?.hospital ?? journey.selected_care_path?.hospital}
        <br />
        {slot ? new Date(slot.starts_at).toLocaleString() : "Confirmed appointment"}
      </p>
      <small>
        Sandbox booking confirmation
        <br />
        {journey.receipts.length} permissioned action receipt
        {journey.receipts.length === 1 ? "" : "s"} saved
      </small>
      <button className="vela-primary" onClick={onAppointments}>
        View appointment
      </button>
      <button className="vela-secondary" onClick={onReset}>
        Start another journey
      </button>
    </section>
  );
}

type ChatTurn = { role: "user" | "assistant"; text: string };
type ChatSuggestion = { label: string; text: string };

const CHAT_PROGRESS = [
  "Got it — reading that with your journey context",
  "Onboarding Agent is updating only the facts you supplied",
  "Knowledge Agent is checking the procedure catalog",
  "Preparing current-plan hospital options",
];

function likelyPendingReply(text: string, journey: CareJourneySnapshot | null): boolean {
  if (journey?.stage !== "intake" || journey.onboarding_questions.length === 0) return false;
  return !/\b(new|another|different|separate|reschedule|cancel|status|all journeys|start over)\b/i.test(text);
}

function suggestionsFor(journey: CareJourneySnapshot | null): ChatSuggestion[] {
  if (!journey || journey.stage !== "intake") {
    return [
      { label: "Book a knee MRI", text: "I need to book a knee MRI." },
      { label: "Book a blood test", text: "I need to book a blood test." },
      { label: "Reschedule care", text: "I need to reschedule an appointment." },
    ];
  }
  const questions = journey.onboarding_questions.join(" ").toLowerCase();
  const suggestions: ChatSuggestion[] = [];
  if (questions.includes("blood test")) suggestions.push({ label: "CBC with differential", text: "CBC with differential." });
  if (questions.includes("without contrast") || questions.includes("with contrast")) suggestions.push({ label: "Without contrast", text: "Without contrast." });
  if (questions.includes("ultrasound")) suggestions.push({ label: "Complete abdominal", text: "Complete abdominal ultrasound." });
  if (questions.includes("date") || questions.includes("coverage end")) suggestions.push({ label: "Add care dates", text: "Care by August 30; my coverage ends September 30." });
  suggestions.push({ label: "Upload the order", text: "I’ll upload the clinician order instead." });
  return suggestions.slice(0, 3);
}

function appointmentsFromContext(context: CareContext): VelaAppointment[] {
  return context.appointments.map((item) => {
    const owner = context.journeys.find((entry) => entry.journey_id === item.journey_id);
    const date = item.booked_for ? new Date(item.booked_for) : null;
    return {
      id: item.appointment_id,
      journeyId: item.journey_id,
      title: item.description || owner?.title || "Appointment",
      provider: owner?.selected_care_path?.hospital || "Provider",
      date: date
        ? date.toLocaleDateString("en-US", {
            weekday: "long",
            month: "long",
            day: "numeric",
          })
        : "Date pending",
      time: date
        ? date.toLocaleTimeString("en-US", {
            hour: "numeric",
            minute: "2-digit",
          })
        : "",
      location: "Seattle, WA",
      cost: owner?.selected_care_path?.estimated_member_cost || 0,
      status: item.status === "confirmed" ? ("Confirmed" as const) : ("Pending" as const),
    };
  });
}

function ChatPanel({ turns, value, busy, busyLabel, suggestions, onValue, onSend, onSuggestion }: { turns: ChatTurn[]; value: string; busy: boolean; busyLabel: string; suggestions: ChatSuggestion[]; onValue: (value: string) => void; onSend: () => void; onSuggestion: (text: string) => void }) {
  const turnsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = turnsRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [busy, turns]);
  return (
    <section className="vela-chat-panel" aria-label="Chat with VELA">
      <div className="vela-chat-turns" ref={turnsRef} aria-live="polite">
        {turns.slice(-4).map((turn, index) => (
          <div className={`vela-chat-turn is-${turn.role}`} key={`${turn.role}-${index}`}>
            <span>{turn.role === "assistant" ? "VELA" : "You"}</span>
            <p>{turn.text}</p>
          </div>
        ))}
        {busy && (
          <div className="vela-chat-turn is-assistant is-typing">
            <span>Working with your care team</span>
            <p>
              <b>{busyLabel}</b><i /><i /><i />
            </p>
          </div>
        )}
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSend();
        }}
      >
        <MessageCircle aria-hidden />
        <input autoFocus type="text" enterKeyHint="send" value={value} onChange={(event) => onValue(event.currentTarget.value)} placeholder="Describe the care you need…" aria-label="Message VELA" />
        <button type="submit" disabled={!value.trim() || busy} aria-label="Send message">
          <Send />
        </button>
      </form>
      <div className="vela-chat-suggestions">
        {suggestions.map((suggestion) => <button type="button" disabled={busy} key={suggestion.label} onClick={() => onSuggestion(suggestion.text)}>{suggestion.label}</button>)}
      </div>
    </section>
  );
}

function ChatDocumentDock({ busy, onCamera, onUpload }: DocumentPromptProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <aside className="vela-chat-document-dock" aria-label="Add a care order">
      <span>Care order</span>
      <button type="button" onClick={onCamera} disabled={busy} aria-label="Scan and analyze care order">
        <Camera />
        <small>Scan order</small>
      </button>
      <button type="button" onClick={() => inputRef.current?.click()} disabled={busy} aria-label="Upload and analyze care order">
        <Upload />
        <small>Upload order</small>
      </button>
      <input ref={inputRef} type="file" accept="image/*,.pdf,application/pdf" hidden onChange={(event) => onUpload(event.target.files)} />
    </aside>
  );
}

async function extractCareOrderImageText(file: File): Promise<string> {
  const { createWorker } = await import("tesseract.js");
  const worker = await createWorker("eng");
  try {
    const result = await worker.recognize(file);
    return result.data.text.trim();
  } finally {
    await worker.terminate();
  }
}

export function VelaExperience() {
  const mobile = useIsMobile();
  const liveMode = import.meta.env.VITE_LIVE_MODE === "true" && Boolean(getToken());
  const [tab, setTab] = useState<AppTab>("home");
  const [inputMode, setInputMode] = useState<"voice" | "chat">("voice");
  const [scene, setScene] = useState<Scene>(() => {
    const requested = new URLSearchParams(window.location.search).get("scene") as Scene | null;
    return requested && sceneOrder.includes(requested) ? requested : "listening";
  });
  const [busy, setBusy] = useState(false);
  const [journey, setJourney] = useState<CareJourneySnapshot | null>(null);
  const [careContext, setCareContext] = useState<CareContext | null>(null);
  const [matchingReason, setMatchingReason] = useState<string | null>(null);
  const [bookingText, setBookingText] = useState("2026-08-30 to 2026-09-15, any time");
  const [notice, setNotice] = useState<string | null>(null);
  const [chatValue, setChatValue] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatProgressIndex, setChatProgressIndex] = useState(0);
  const [chatStarted, setChatStarted] = useState(false);
  const [chatVisualProgress, setChatVisualProgress] = useState(0);
  const [voiceStarted, setVoiceStarted] = useState(false);
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([
    {
      role: "assistant",
      text: "Where do you need to go from here? Tell me what care you need and I’ll ask only what changes the recommendation.",
    },
  ]);
  const [documents, setDocuments] = useState<VelaDocument[]>(
    liveMode
      ? []
      : [
          {
            id: "demo-sbc",
            name: "Current Plan SBC.pdf",
            kind: "Summary of Benefits",
            status: "Verified",
            added: "Aug 15",
          },
          {
            id: "demo-referral",
            name: "Knee MRI referral.pdf",
            kind: "Referral",
            status: "Verified",
            added: "Aug 15",
          },
        ],
  );
  const [appointments, setAppointments] = useState<VelaAppointment[]>(
    liveMode
      ? []
      : [
          {
            id: "demo-appointment",
            title: "Knee MRI without contrast",
            provider: "Northwest Imaging",
            date: "Tuesday, September 3",
            time: "10:30 AM",
            location: "Seattle, WA",
            cost: 420,
            status: "Confirmed",
          },
        ],
  );
  const [cameraOpen, setCameraOpen] = useState(false);
  const adoptJourney = (next: CareJourneySnapshot, context?: CareContext) => {
    setJourney(next);
    if (context) setCareContext(context);
    const nextScene = sceneForJourney(next);
    setScene(nextScene);
    if (next.stage === "recommend") setTab("paths");
    if (next.stage === "book" || next.stage === "complete") setTab("appointments");
  };
  const adoptAgentResponse = (response: CareAgentResponse) => {
    setCareContext(response.context);
    if (response.journey) adoptJourney(response.journey, response.context);
    setChatTurns((turns) => [...turns, { role: "assistant", text: response.reply }]);
  };
  const voice = useVoiceSession({
    activeJourneyId: journey?.journey_id,
    onError: (message) => setNotice(message),
    onUiEvent: (target, payload) => {
      if (target === "care_journey") adoptAgentResponse(payload as CareAgentResponse);
    },
  });
  const demoMic = useDemoMicrophone();
  const index = sceneOrder.indexOf(scene);
  const progress = Math.max(0, index / (sceneOrder.length - 1));
  const copy = sceneCopy[scene];
  const requestedCare = String(journey?.procedure_resolution?.canonical_name ?? journey?.facts?.find((fact) => fact.name === "requested_procedure")?.value ?? "Your care request");
  const liveCopy =
    liveMode && journey
      ? {
          eyebrow: requestedCare,
          title: journey.stage === "intake" ? "A few details will\ncomplete your request." : journey.stage === "recommend" ? "Your current-plan\noptions are ready." : journey.stage === "verify" ? "Verify the path\nbefore booking." : journey.stage === "book" ? "Choose the exact\nappointment you want." : journey.stage === "complete" ? "Your appointment\nis confirmed." : copy.title,
          status: journey.onboarding_questions[0] ?? copy.status,
        }
      : copy;
  const resolved = ["recommendation", "consent", "booking", "complete"].includes(scene);
  const voiceLevel = inputMode === "chat" && chatBusy ? 0.72 : liveMode ? voice.micLevel : demoMic.level;
  const voiceFeedback = liveMode ? (voice.status === "listening" && voiceLevel > 0.08 ? "I can hear you…" : VOICE_LABEL[voice.status]) : voiceLevel > 0.08 ? "I can hear you…" : liveCopy.status;
  const voiceButtonLabel = liveMode ? (voice.isListening ? "Listening now" : voice.isProcessing ? VOICE_LABEL[voice.status] : voice.isActive ? VOICE_LABEL[voice.status] : "Start a care request") : demoMic.active ? "Listening now" : "Start a care request";
  const agentCount = useMemo(() => {
    if (scene === "working") return 2;
    if (["decision", "verifying"].includes(scene)) return 3;
    if (index >= sceneOrder.indexOf("recommendation")) return 4;
    return Math.max(0, index - 1);
  }, [index, scene]);
  const chatSuggestions = useMemo(() => suggestionsFor(journey), [journey]);

  useEffect(() => {
    if (!chatBusy) {
      setChatProgressIndex(0);
      return;
    }
    const timer = window.setInterval(
      () => setChatProgressIndex((current) => Math.min(current + 1, CHAT_PROGRESS.length - 1)),
      4200,
    );
    return () => window.clearInterval(timer);
  }, [chatBusy]);
  const verificationCopy: ConsentCopy = {
    title: "Approve provider and network verification.",
    description: journey?.selected_care_path ? `VELA will verify ${journey.selected_care_path.hospital} against your current ${journey.selected_care_path.plan_name}.` : "Choose a hospital before verification.",
    items: ["Share only this care request and current-plan details", "Check network and provider status in the sandbox", "Save a verification receipt; do not book care"],
    button: "Approve verification",
  };
  const demoConsentCopy: ConsentCopy = {
    title: "Your approval is required to continue.",
    description: "VELA is ready to schedule with the recommended provider on your behalf.",
    items: ["Share relevant information with the provider", "Request the next available appointment", "Receive and manage appointment details"],
    button: "Approve and continue",
  };

  useEffect(() => {
    if (liveMode) return;
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
  }, [liveMode, scene]);

  useEffect(() => {
    if (!liveMode) return;
    let cancelled = false;
    void api
      .careContext()
      .then(async (context) => {
        if (cancelled) return;
        setCareContext(context);
        const active = context.journeys.find((item) => item.status === "active") ?? context.journeys[0];
        if (active) {
          const snapshot = await api.journey(active.journey_id);
          if (!cancelled) {
            adoptJourney(snapshot, context);
            if (snapshot.stage === "intake" && snapshot.onboarding_questions.length > 0) {
              setChatTurns([{ role: "assistant", text: `Welcome back — I kept your progress. ${snapshot.onboarding_questions.join(" ")}` }]);
            }
          }
        }
        setAppointments(appointmentsFromContext(context));
      })
      .catch((error) => {
        if (!cancelled) setNotice(error instanceof Error ? error.message : "VELA could not load your care context.");
      });
    return () => {
      cancelled = true;
    };
    // Load once after authentication; journey mutations update state directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveMode]);

  useEffect(() => {
    if (!liveMode || !journey?.booking_tasks.some((task) => task.status === "scheduled")) return;
    const timer = window.setInterval(() => {
      void api
        .journey(journey.journey_id)
        .then(async (next) => {
          adoptJourney(next);
          if (next.stage === "complete") {
            const context = await api.careContext();
            setCareContext(context);
            setAppointments(appointmentsFromContext(context));
          }
        })
        .catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveMode, journey?.journey_id, journey?.booking_tasks]);

  const reset = () => {
    voice.disconnect();
    demoMic.stop();
    setScene("listening");
    setJourney(null);
    setNotice(null);
    setMatchingReason(null);
    setChatStarted(false);
    setChatVisualProgress(0);
    setVoiceStarted(false);
    setTab("home");
    setChatTurns([
      {
        role: "assistant",
        text: "Where do you need to go from here? Tell me what care you need and I’ll ask only what changes the recommendation.",
      },
    ]);
  };

  const begin = async () => {
    if (inputMode === "chat") return;
    try {
      if (liveMode) await voice.connect();
      else {
        await demoMic.start();
        setScene("documents");
      }
      setVoiceStarted(true);
    } catch (error) {
      setNotice(error instanceof Error && error.name === "NotAllowedError" ? "Microphone access was denied. You can continue by chat instead." : "Microphone unavailable. You can continue by chat instead.");
      setInputMode("chat");
    }
  };

  const sendChat = async (suggestedText?: string) => {
    const text = (suggestedText ?? chatValue).trim();
    if (!text) return;
    setChatStarted(true);
    setChatVisualProgress((current) => Math.min(0.62, current + 0.08));
    setChatTurns((turns) => [...turns, { role: "user", text }]);
    setChatValue("");
    setChatBusy(true);
    try {
      if (liveMode && voice.isActive) {
        voice.sendText(text);
      } else if (liveMode) {
        const response = await api.careAgentMessage(
          text,
          journey?.journey_id,
          likelyPendingReply(text, journey),
        );
        adoptAgentResponse(response);
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 420));
        setChatTurns((turns) => [
          ...turns,
          {
            role: "assistant",
            text: "I can help with that. First, show me your coverage so I can compare the complete cost instead of guessing from the procedure price alone.",
          },
        ]);
        setScene("documents");
      }
      setChatVisualProgress((current) => Math.min(0.78, current + 0.05));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "VELA could not send that message.");
    } finally {
      setChatBusy(false);
    }
  };

  const handleFiles = async (files: FileList | File[] | null) => {
    const file = files?.[0];
    if (!file) return;
    setBusy(true);
    setNotice(null);
    try {
      const newDocument: VelaDocument = {
        id: crypto.randomUUID(),
        name: file.name,
        kind: "Referral",
        status: "Processing",
        added: "Just now",
        preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined,
      };
      setDocuments((items) => [newDocument, ...items]);
      if (liveMode) {
        setNotice(file.type.startsWith("image/") ? "Reading the care order…" : "Extracting the care order…");
        const extractedText = file.type.startsWith("image/") ? await extractCareOrderImageText(file) : undefined;
        setNotice("Onboarding Agent is resolving the ordered procedure…");
        const result = await api.analyzeCareOrder(
          file,
          journey?.stage === "intake" ? journey.journey_id : undefined,
          extractedText,
        );
        adoptJourney(result.journey);
        const reply = result.options_ready
          ? `I extracted the order and found ${result.journey.current_plan_options.length} hospital options under your current plan.`
          : result.journey.onboarding_questions.join(" ");
        setChatTurns((turns) => [...turns, { role: "assistant", text: reply }]);
        setNotice(result.options_ready ? "Care order analyzed. Current-plan hospital options are ready." : "Care order analyzed. I only need the missing details shown in the conversation.");
      }
      setDocuments((items) => items.map((item) => (item.id === newDocument.id ? { ...item, status: "Verified" } : item)));
      if (!liveMode) setScene("understanding");
    } catch (error) {
      setDocuments((items) => items.map((item) => (item.status === "Processing" ? { ...item, status: "Review needed" } : item)));
      setNotice(error instanceof Error ? error.message : "VELA could not read that care order.");
    } finally {
      setBusy(false);
    }
  };

  const handleDecision = async () => {
    setBusy(true);
    try {
      if (liveMode && journey) {
        const compared = await api.journeyCompare(journey.journey_id);
        setJourney(compared);
      }
      setScene("verifying");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "VELA could not compare the paths.");
    } finally {
      setBusy(false);
    }
  };

  const verifySelectedPath = async () => {
    setBusy(true);
    try {
      if (!journey?.selected_care_path) throw new Error("Choose a hospital first.");
      const selected = journey.selected_care_path;
      const scope = `Dr. Lee / ${selected.hospital} / ${selected.plan_name}`;
      await api.journeyConsent(journey.journey_id, {
        action: "share_with_provider",
        scope,
        approved: true,
      });
      const actioned = await api.journeyAction(journey.journey_id, {
        action: "share_with_provider",
        scope,
        idempotency_key: `vela-verify-${journey.journey_id}`,
      });
      adoptJourney(actioned);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The approved action could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  const selectPath = async (hospitalId: number) => {
    if (!journey) return;
    setBusy(true);
    setNotice(null);
    try {
      const next = await api.journeySelectCurrentPath(journey.journey_id, hospitalId);
      adoptJourney(next);
      setTab("home");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "VELA could not select that path.");
    } finally {
      setBusy(false);
    }
  };

  const explainPaths = async () => {
    if (!journey) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await api.journeyMatchingReason(journey.journey_id, "Explain the current-plan hospital ranking and the separate alternate-coverage scenario without treating estimates as guarantees.");
      setJourney(result.journey);
      setMatchingReason(result.reason);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Nemotron could not explain the ranking.");
    } finally {
      setBusy(false);
    }
  };

  const openJourney = async (journeyId: string) => {
    setBusy(true);
    setNotice(null);
    try {
      adoptJourney(await api.journey(journeyId));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "VELA could not open that journey.");
    } finally {
      setBusy(false);
    }
  };

  const findSlots = async () => {
    if (!journey) return;
    setBusy(true);
    setNotice(null);
    try {
      adoptJourney(await api.journeyBookingPreferences(journey.journey_id, bookingText));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The Booking Agent could not read those preferences.");
    } finally {
      setBusy(false);
    }
  };

  const selectSlot = async (slotId: string) => {
    if (!journey) return;
    setBusy(true);
    setNotice(null);
    try {
      adoptJourney(await api.journeySelectBookingSlot(journey.journey_id, slotId));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "VELA could not select that slot.");
    } finally {
      setBusy(false);
    }
  };

  const bookSelectedSlot = async () => {
    if (!journey?.selected_booking_slot || !journey.booking_consent_scope) return;
    setBusy(true);
    setNotice(null);
    try {
      const scope = journey.booking_consent_scope;
      let next: CareJourneySnapshot;
      if (journey.reschedule_original_slot && journey.cancellation_consent_scope) {
        await api.journeyConsent(journey.journey_id, {
          action: "book_appointment",
          scope,
          approved: true,
        });
        await api.journeyConsent(journey.journey_id, {
          action: "cancel_appointment",
          scope: journey.cancellation_consent_scope,
          approved: true,
        });
        next = await api.journeyReschedule(journey.journey_id, {
          booking_scope: scope,
          cancellation_scope: journey.cancellation_consent_scope,
          idempotency_key: `vela-reschedule-${journey.journey_id}-${journey.selected_booking_slot.slot_id}`,
        });
      } else {
        await api.journeyConsent(journey.journey_id, {
          action: "book_appointment",
          scope,
          approved: true,
        });
        next = await api.journeyAction(journey.journey_id, {
          action: "book_appointment",
          scope,
          idempotency_key: `vela-book-${journey.journey_id}-${journey.selected_booking_slot.slot_id}`,
        });
      }
      adoptJourney(next);
      const context = await api.careContext();
      setCareContext(context);
      setAppointments(appointmentsFromContext(context));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The approved booking could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`vela-shell ${mobile ? "is-mobile" : "is-desktop"}`}>
      {!mobile && <Sidebar scene={scene} tab={tab} onTab={setTab} onReset={reset} />}
      {mobile && <MobileHeader onReset={reset} />}
      {tab === "home" ? (
        <main className={`vela-stage scene-${scene} is-neural-mode ${inputMode === "chat" ? "is-chat-mode" : "is-call-mode"}`}>
          <NeuralPath className={(inputMode === "chat" ? !chatStarted : !voiceStarted) ? "is-hidden" : ""} progress={inputMode === "chat" ? Math.max(chatVisualProgress, chatStarted ? progress : 0, voiceLevel * 0.55) : voiceStarted ? Math.max(progress, voiceLevel * 0.55) : 0} energy={voiceLevel} resolved={resolved} />
          <div className="vela-stage-content">
            <div className="vela-mode-switch">
              <button type="button" className={inputMode === "voice" ? "is-active" : ""} onClick={() => setInputMode("voice")}>
                <Phone />
                Voice
              </button>
              <button type="button" className={inputMode === "chat" ? "is-active" : ""} onClick={() => setInputMode("chat")}>
                <MessageCircle />
                Chat
              </button>
            </div>
            <p className="vela-eyebrow">{inputMode === "chat" && chatStarted ? requestedCare : liveCopy.eyebrow}</p>
            <h1>
              {(inputMode === "chat" && chatStarted ? "Finding your clearest path." : liveCopy.title).split("\n").map((line, lineIndex, lines) => (
                <span key={line}>
                  {line}
                  {lineIndex < lines.length - 1 && <br />}
                </span>
              ))}
            </h1>
            {inputMode === "voice" && (
              <>
                <div className={`vela-listener is-${liveMode ? voice.status : demoMic.active ? "listening" : "idle"}`} style={{ "--energy": voiceLevel } as React.CSSProperties}>
                  <Waveform />
                  <VoiceOrb active={liveMode ? voice.isListening || voice.status === "speaking" : scene !== "complete"} />
                  <Waveform />
                </div>
                <p className={`vela-status is-${liveMode ? voice.status : "idle"}`}>
                  <i aria-hidden />
                  {voiceFeedback}
                </p>
              </>
            )}
            {inputMode === "chat" && <ChatPanel turns={chatTurns} value={chatValue} busy={chatBusy} busyLabel={CHAT_PROGRESS[chatProgressIndex]} suggestions={chatSuggestions} onValue={setChatValue} onSend={() => void sendChat()} onSuggestion={(text) => void sendChat(text)} />}

            {scene === "listening" && inputMode === "voice" && (
              <div className="vela-start">
                <p>{liveMode && voice.isProcessing ? "Your turn is complete. The microphone is paused while VELA works." : "Tell VELA what care you need. A natural pause will end your turn automatically."}</p>
                <button disabled={liveMode && voice.isActive} onClick={() => void begin()}>
                  <Mic />
                  {voiceButtonLabel}
                </button>
              </div>
            )}
            {["understanding", "context", "working", "verifying"].includes(scene) && <AgentPanel activeCount={agentCount} />}
            {scene === "decision" && <DecisionCard onAnswer={handleDecision} />}
            {scene === "recommendation" && journey && <RecommendationCard journey={journey} onContinue={() => setTab("paths")} onExplain={() => void explainPaths()} />}
            {scene === "consent" && <ConsentCard copy={liveMode ? verificationCopy : demoConsentCopy} onApprove={liveMode ? verifySelectedPath : () => setScene("booking")} onBack={() => (liveMode ? setTab("paths") : setScene("recommendation"))} />}
            {scene === "booking" && (
              <section className="vela-booking-handoff">
                <AgentPanel activeCount={4} />
                <button className="vela-primary" onClick={() => setTab("appointments")}>
                  Choose an appointment
                </button>
              </section>
            )}
            {scene === "complete" && journey && <CompleteCard journey={journey} onAppointments={() => setTab("appointments")} onReset={reset} />}
          </div>
          {["listening", "documents"].includes(scene) && <ChatDocumentDock busy={busy} onCamera={() => void captureCard().then((file) => file && handleFiles([file]))} onUpload={handleFiles} />}
          {notice && (
            <div className="vela-notice">
              <span>{notice}</span>
              <button onClick={() => setNotice(null)} aria-label="Close">
                <X />
              </button>
            </div>
          )}
        </main>
      ) : (
        <main key={tab} className="vela-stage vela-tab-stage">
          {tab === "paths" && <PathsTab journey={journey} context={careContext} busy={busy} matchingReason={matchingReason} onSelect={(hospitalId) => void selectPath(hospitalId)} onExplain={() => void explainPaths()} onOpenJourney={(journeyId) => void openJourney(journeyId)} />}
          {tab === "appointments" && <AppointmentsTab items={appointments} onItems={setAppointments} liveMode={liveMode} journey={journey} busy={busy} bookingText={bookingText} onBookingText={setBookingText} onFindSlots={() => void findSlots()} onSelectSlot={(slotId) => void selectSlot(slotId)} onBook={() => void bookSelectedSlot()} />}
          {tab === "documents" && (
            <DocumentsTab
              documents={documents}
              onDocuments={setDocuments}
              liveMode={liveMode}
              openCamera={cameraOpen}
              onOpenCamera={setCameraOpen}
              onProcessFile={async (file) => {
                await handleFiles([file]);
              }}
            />
          )}
          {tab === "preferences" && <PreferencesTab journey={journey} />}
        </main>
      )}
      {mobile && <MobileNav scene={scene} tab={tab} onTab={setTab} onReset={reset} />}
    </div>
  );
}
