import {
  Bell,
  Building2,
  CalendarDays,
  Camera,
  Check,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Download,
  FileText,
  HeartHandshake,
  Languages,
  MapPin,
  Network,
  Plus,
  ScanLine,
  ShieldCheck,
  Stethoscope,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type CareContext, type CareJourneySnapshot } from "@/lib/api";

export type VelaDocument = {
  id: string;
  name: string;
  kind: "Insurance card" | "Summary of Benefits" | "Referral" | "Other";
  status: "Verified" | "Review needed" | "Processing";
  added: string;
  preview?: string;
};

export type VelaAppointment = {
  id: string;
  journeyId?: string;
  title: string;
  provider: string;
  date: string;
  time: string;
  location: string;
  cost: number;
  status: "Confirmed" | "Pending";
};

const money = (value: number) => value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const dateTile = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? { day: "—", month: "TBD" }
    : { day: parsed.toLocaleDateString("en-US", { day: "2-digit" }), month: parsed.toLocaleDateString("en-US", { month: "short" }).toUpperCase() };
};

export function PathsTab({
  journey,
  context,
  busy,
  matchingReason,
  onSelect,
  onExplain,
  onOpenJourney,
}: {
  journey: CareJourneySnapshot | null;
  context: CareContext | null;
  busy: boolean;
  matchingReason: string | null;
  onSelect: (hospitalId: number) => void;
  onExplain: () => void;
  onOpenJourney: (journeyId: string) => void;
}) {
  const [expanded, setExpanded] = useState<number | null>(journey?.current_plan_options[0]?.hospital_id ?? null);
  const options = journey?.current_plan_options ?? [];
  const selected = journey?.selected_care_path;
  return (
    <section className="vela-tab-page vela-paths-page">
      <header><p>Current-plan comparison</p><h1>Your care paths</h1><span>Hospital-published prices are evaluated with your current plan. Network verification happens only after you choose, and choosing never books care.</span></header>
      {journey && <div className="vela-path-summary"><div><ShieldCheck /><span>{journey.current_plan_name}</span></div><div><Check /><span>{options.length} hospital options</span></div><div><CircleDollarSign /><span>{journey.alternative_plan ? `${money(journey.alternative_plan.estimated_annual_savings)} alternate-plan scenario` : "Current coverage"}</span></div></div>}
      {selected && <article className="vela-path-selected"><span>Selected care path</span><h2>{selected.hospital}</h2><p>{selected.plan_name} · {money(selected.estimated_member_cost)} estimated member cost</p><b>{selected.network_status === "sandbox_verified" ? "Network sandbox-verified" : "Verification pending"}</b></article>}
      {options.length > 0 ? <div className="vela-path-grid">
        {options.map((path, index) => {
          const isSelected = selected?.hospital_id === path.hospital_id;
          return <article className={`vela-path-card ${index === 0 ? "is-selected" : ""}`} key={path.hospital_id}>
            {index === 0 && <b className="vela-path-badge">Lowest current-plan scenario</b>}
            <div className="vela-path-card-top"><div><h2>{path.hospital}</h2><p><Building2 />{path.plan_name}</p></div><strong>{money(path.estimated_member_cost)}</strong></div>
            <div className="vela-path-metrics"><span><small>Published rate</small><b>{money(path.published_typical_rate)}</b></span><span><small>Annual scenario</small><b>{money(path.estimated_annual_total)}</b></span><span><small>Network</small><b>Pending</b></span></div>
            <p className="vela-path-detail">Scenario estimate, not a guarantee. Deductible remaining: {money(path.deductible_remaining)} · {Math.round(path.coinsurance_rate * 100)}% coinsurance.</p>
            <button onClick={() => setExpanded(expanded === path.hospital_id ? null : path.hospital_id)}>See evidence <ChevronRight /></button>
            {expanded === path.hospital_id && <div className="vela-evidence"><span><Check />Hospital-published rate retained with source</span><span><Check />Member cost calculated by deterministic rules</span><span><Check />Current insurance remains unchanged</span><span className="is-warning"><X />Network status still requires verification</span></div>}
            {!isSelected && <button className="vela-path-choose" disabled={busy || Boolean(selected)} onClick={() => onSelect(path.hospital_id)}>Choose this hospital</button>}
          </article>;
        })}
      </div> : <div className="vela-empty-live"><Network /><h2>No ranked paths for this journey yet</h2><p>Continue the intake conversation so the Knowledge and Matching agents can resolve the procedure and build current-plan options.</p></div>}
      {journey?.alternative_plan && <article className="vela-alternative-path"><span>Optional alternate coverage · informational only</span><h2>{journey.alternative_plan.plan_name}</h2><p>{money(journey.alternative_plan.estimated_annual_total)} annual scenario at {journey.alternative_plan.hospital}. Exploring this would start a separate eligibility and switching flow; it is not part of this booking journey.</p></article>}
      {journey && options.length > 0 && <button className="vela-explain-paths" disabled={busy} onClick={onExplain}>Ask Nemotron to explain the ranking</button>}
      {matchingReason && <div className="vela-matching-reason"><b>Matching Agent explanation</b><p>{matchingReason}</p></div>}
      {context && context.journeys.length > 1 && <section className="vela-journey-history"><h2>Other care journeys</h2>{context.journeys.filter((item) => item.journey_id !== journey?.journey_id).map((item) => <button key={item.journey_id} onClick={() => onOpenJourney(item.journey_id)}><span><b>{item.title}</b><small>{item.stage} · {item.status}</small></span><ChevronRight /></button>)}</section>}
    </section>
  );
}

export function AppointmentsTab({ items, onItems, liveMode, journey, busy, bookingText, onBookingText, onFindSlots, onSelectSlot, onBook }: { items: VelaAppointment[]; onItems: (items: VelaAppointment[]) => void; liveMode: boolean; journey: CareJourneySnapshot | null; busy: boolean; bookingText: string; onBookingText: (text: string) => void; onFindSlots: () => void; onSelectSlot: (slotId: string) => void; onBook: () => void }) {
  const [adding, setAdding] = useState(false);
  const [receiptItem, setReceiptItem] = useState<VelaAppointment | null>(null);
  const [receiptJourney, setReceiptJourney] = useState<CareJourneySnapshot | null>(null);
  const [form, setForm] = useState({ title: "", provider: "", date: "", time: "", cost: "" });
  const save = async () => {
    if (!form.title.trim()) return;
    const next: VelaAppointment = { id: crypto.randomUUID(), title: form.title, provider: form.provider || "Provider pending", date: form.date || "Date pending", time: form.time, location: "Seattle, WA", cost: Number(form.cost) || 0, status: "Confirmed" };
    if (liveMode) await api.addAppointment({ description: next.title, booked_for: next.date, estimated_cost: next.cost, note: next.provider }).catch(() => {});
    onItems([...items, next]); setAdding(false); setForm({ title: "", provider: "", date: "", time: "", cost: "" });
  };
  const openReceipt = async (item: VelaAppointment) => {
    setReceiptItem(item);
    setReceiptJourney(item.journeyId && item.journeyId !== journey?.journey_id ? null : journey);
    if (item.journeyId && item.journeyId !== journey?.journey_id) {
      try { setReceiptJourney(await api.journey(item.journeyId)); }
      catch { setReceiptJourney(null); }
    }
  };
  return (
    <section className="vela-tab-page vela-appointments-page">
      <header><p>Your care calendar</p><h1>Appointments</h1><span>Verified times, expected responsibility, preparation details, and receipts stay together.</span><button onClick={() => setAdding(true)}><Plus />Add appointment</button></header>
      {journey?.stage === "book" && <section className="vela-booking-live"><div><span>Booking Agent</span><h2>{journey.reschedule_original_slot ? "Choose a replacement appointment" : "Choose a synthetic appointment"}</h2><p>{journey.reschedule_original_slot ? "Your original appointment stays confirmed until its replacement is confirmed. Both the replacement booking and original cancellation have exact approval scopes." : "Tell the agent your date range and time preference. Selecting a slot does not book it; the exact appointment gets a separate approval."}</p></div><form onSubmit={(event) => { event.preventDefault(); onFindSlots(); }}><input value={bookingText} onChange={(event) => onBookingText(event.target.value)} aria-label="Booking preferences" placeholder="Aug 30 to Sep 15, mornings" /><button disabled={busy || !bookingText.trim()}>Find slots</button></form>{journey.booking_slots.length > 0 && <div className="vela-live-slots">{journey.booking_slots.map((slot) => <button key={slot.slot_id} disabled={busy || slot.status !== "available"} className={journey.selected_booking_slot?.slot_id === slot.slot_id ? "is-selected" : ""} onClick={() => onSelectSlot(slot.slot_id)}><CalendarDays /><span><b>{new Date(slot.starts_at).toLocaleString()}</b><small>{slot.hospital} · {slot.duration_minutes} minutes{slot.retry_demo ? " · retry demonstration" : ""}</small></span>{journey.selected_booking_slot?.slot_id === slot.slot_id && <Check />}</button>)}</div>}{journey.selected_booking_slot && journey.booking_consent_scope && <div className="vela-exact-consent"><ShieldCheck /><div><b>{journey.reschedule_original_slot ? "Exact replacement and cancellation approval" : "Exact booking approval"}</b><p>{journey.booking_consent_scope}{journey.cancellation_consent_scope ? ` · then ${journey.cancellation_consent_scope}` : ""}</p></div><button disabled={busy || journey.booking_tasks.some((task) => task.status === "scheduled")} onClick={onBook}>{journey.reschedule_original_slot ? "Approve replacement, then cancel original" : "Approve and book this slot"}</button></div>}{journey.booking_tasks.map((task) => <div className={`vela-booking-task status-${task.status}`} key={task.task_id}><b>Booking task: {task.status}</b><span>{task.attempts} attempt(s){task.status === "scheduled" ? ` · retry ${new Date(task.next_attempt_at).toLocaleTimeString()}` : ""}</span></div>)}</section>}
      <div className="vela-appointment-list">
        {items.map((item) => { const tile = dateTile(item.date); return <article key={item.id}><div className="vela-date-tile"><b>{tile.day}</b><span>{tile.month}</span></div><div className="vela-appointment-copy"><span className="vela-confirmed"><Check />{item.status}</span><h2>{item.title}</h2><p><Stethoscope />{item.provider}</p><p><Clock3 />{item.date} {item.time}</p><p><MapPin />{item.location}</p></div><div className="vela-appointment-cost"><small>Estimated responsibility</small><b>${item.cost}</b><button onClick={() => void openReceipt(item)}>View receipt</button></div></article>; })}
      </div>
      {items.length === 0 && journey?.stage !== "book" && <div className="vela-empty-live"><CalendarDays /><h2>No confirmed appointments yet</h2><p>Start or resume a care journey. Once an exact sandbox booking is approved and confirmed, it appears here with its receipt.</p></div>}
      {adding && <div className="vela-modal-backdrop"><section className="vela-form-modal"><button className="vela-modal-close" onClick={() => setAdding(false)}><X /></button><p>New appointment</p><h2>Keep care details together</h2>{["title","provider","date","time","cost"].map((key) => <label key={key}><span>{key === "title" ? "Care or procedure" : key === "cost" ? "Expected cost" : key[0].toUpperCase()+key.slice(1)}</span><input type={key === "date" ? "date" : key === "time" ? "time" : key === "cost" ? "number" : "text"} value={form[key as keyof typeof form]} onChange={(e) => setForm({...form,[key]:e.target.value})} /></label>)}<button className="vela-primary" onClick={() => void save()}>Save appointment</button></section></div>}
      {receiptItem && <div className="vela-modal-backdrop"><section className="vela-form-modal vela-receipt-modal"><button className="vela-modal-close" aria-label="Close receipt" onClick={() => { setReceiptItem(null); setReceiptJourney(null); }}><X /></button><p>Sandbox audit receipt</p><h2>{receiptItem.title}</h2><div className="vela-receipt-summary"><span><Check />{receiptItem.status}</span><b>{receiptItem.provider}</b><small>{receiptItem.date} {receiptItem.time}</small></div><div className="vela-receipt-list">{receiptJourney?.receipts.length ? receiptJourney.receipts.map((receipt) => <div key={`${receipt.action}-${receipt.recorded_at}`}><span>{receipt.action.replace(/_/g, " ")}</span><b>{receipt.status}</b><small>{receipt.scope}</small></div>) : <p>{receiptItem.journeyId ? "Loading this journey’s receipts…" : "This appointment was recorded manually and has no sandbox action receipt."}</p>}</div></section></div>}
    </section>
  );
}

export function CameraModal({ onCapture, onClose }: { onCapture: (file: File, preview: string) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void navigator.mediaDevices?.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false }).then((stream) => { streamRef.current = stream; if (videoRef.current) { videoRef.current.srcObject = stream; void videoRef.current.play(); } }).catch(() => setError("Camera access is unavailable. You can upload a photo instead."));
    return () => streamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);
  const capture = () => {
    const video = videoRef.current; if (!video) return;
    const canvas = document.createElement("canvas"); canvas.width = video.videoWidth || 1280; canvas.height = video.videoHeight || 720;
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => { if (!blob) return; const preview = URL.createObjectURL(blob); onCapture(new File([blob], `insurance-card-${Date.now()}.jpg`, { type: "image/jpeg" }), preview); }, "image/jpeg", .86);
  };
  return <div className="vela-camera-modal"><header><button onClick={onClose}><X /></button><LogoMark /><span>Insurance card</span></header><div className="vela-camera-frame">{error ? <div className="vela-camera-error"><Camera /><p>{error}</p></div> : <video ref={videoRef} playsInline muted />}<i /><i /><i /><i /><div className="vela-scan-line" /></div><p>Place the front of your card inside the frame. VELA will only extract visible coverage details.</p><button className="vela-shutter" onClick={capture} disabled={Boolean(error)}><span /></button></div>;
}

function LogoMark() { return <span className="vela-camera-logo">VELA</span>; }

export function DocumentsTab({ documents, onDocuments, liveMode, openCamera, onOpenCamera, onProcessFile }: { documents: VelaDocument[]; onDocuments: (items: VelaDocument[]) => void; liveMode: boolean; openCamera: boolean; onOpenCamera: (open: boolean) => void; onProcessFile?: (file: File) => Promise<void> }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const addFile = async (file: File, preview?: string) => {
    if (liveMode && onProcessFile) {
      await onProcessFile(file);
      return;
    }
    const kind: VelaDocument["kind"] = file.type.includes("pdf") ? "Summary of Benefits" : "Insurance card";
    const item: VelaDocument = { id: crypto.randomUUID(), name: file.name, kind, status: "Processing", added: "Just now", preview };
    onDocuments([item, ...documents]);
    try { if (liveMode) { if (kind === "Insurance card") await api.scanCard(file); else await api.parseSbc(file); } window.setTimeout(() => onDocuments([{...item,status:"Verified"}, ...documents]), 900); } catch { onDocuments([{...item,status:"Review needed"}, ...documents]); }
  };
  return <section className="vela-tab-page vela-documents-page"><header><p>Your evidence locker</p><h1>Documents</h1><span>Coverage details remain connected to their source, confidence, and review status.</span><div><button onClick={() => onOpenCamera(true)}><Camera />Scan card</button><button onClick={() => inputRef.current?.click()}><Upload />Upload PDF</button><input ref={inputRef} hidden type="file" accept="image/*,.pdf" multiple onChange={(e) => Array.from(e.target.files || []).forEach((file) => void addFile(file))} /></div></header><div className="vela-document-layout"><aside><ShieldCheck /><h2>Private by design</h2><p>VELA records provenance and verification status for every extracted fact. Model output never replaces the original document.</p><span><Check />Encrypted transport</span><span><Check />Consent before processing</span><span><Check />Source retained in audit history</span></aside><div className="vela-document-list">{documents.map((document) => <article key={document.id}>{document.preview ? <img src={document.preview} alt="Captured insurance card" /> : <div className="vela-file-icon">{document.kind === "Insurance card" ? <ScanLine /> : <FileText />}</div>}<div><span>{document.kind}</span><h2>{document.name}</h2><p>Added {document.added}</p></div><b className={`status-${document.status.toLowerCase().replace(" ","-")}`}>{document.status === "Verified" && <Check />}{document.status}</b><button aria-label={`Remove ${document.name}`} onClick={() => onDocuments(documents.filter((item) => item.id !== document.id))}><Trash2 /></button></article>)}</div></div>{openCamera && <CameraModal onClose={() => onOpenCamera(false)} onCapture={(file, preview) => { onOpenCamera(false); void addFile(file, preview); }} />}</section>;
}

export function PreferencesTab() {
  const [prefs, setPrefs] = useState({ distance: 15, maxCost: 500, language: "English", keepDoctor: true, textUpdates: true, emailReceipts: true, morning: true });
  const toggle = (key: keyof typeof prefs) => setPrefs({...prefs,[key]:!prefs[key]});
  return <section className="vela-tab-page vela-preferences-page"><header><p>Your decision rules</p><h1>Preferences</h1><span>VELA applies these boundaries before it ranks a care path. You can change them at any time.</span></header><div className="vela-preference-grid"><article><div className="vela-pref-title"><MapPin /><div><h2>Travel distance</h2><p>Maximum distance for recommended care</p></div><b>{prefs.distance} miles</b></div><input type="range" min="1" max="50" value={prefs.distance} onChange={(e)=>setPrefs({...prefs,distance:Number(e.target.value)})} /></article><article><div className="vela-pref-title"><CircleDollarSign /><div><h2>Comfortable out of pocket cost</h2><p>VELA flags options above this amount</p></div><b>${prefs.maxCost}</b></div><input type="range" min="50" max="2000" step="50" value={prefs.maxCost} onChange={(e)=>setPrefs({...prefs,maxCost:Number(e.target.value)})} /></article><article><div className="vela-pref-title"><HeartHandshake /><div><h2>Keep my current physician</h2><p>Treat this as a hard matching constraint</p></div><button className={prefs.keepDoctor ? "is-on" : ""} onClick={()=>toggle("keepDoctor")}><i /></button></div></article><article><div className="vela-pref-title"><Clock3 /><div><h2>Morning appointments</h2><p>Prefer appointments before noon</p></div><button className={prefs.morning ? "is-on" : ""} onClick={()=>toggle("morning")}><i /></button></div></article><article><div className="vela-pref-title"><Languages /><div><h2>Language</h2><p>Voice, explanations, and receipts</p></div><select value={prefs.language} onChange={(e)=>setPrefs({...prefs,language:e.target.value})}><option>English</option><option>Spanish</option><option>French</option><option>Mandarin</option></select></div></article><article><div className="vela-pref-title"><Bell /><div><h2>Text updates</h2><p>Appointment and action status messages</p></div><button className={prefs.textUpdates ? "is-on" : ""} onClick={()=>toggle("textUpdates")}><i /></button></div><div className="vela-pref-title second"><Download /><div><h2>Email receipts</h2><p>Send consent and sandbox action receipts</p></div><button className={prefs.emailReceipts ? "is-on" : ""} onClick={()=>toggle("emailReceipts")}><i /></button></div></article></div><p className="vela-preferences-saved"><Check />Preferences saved on this device</p></section>;
}
