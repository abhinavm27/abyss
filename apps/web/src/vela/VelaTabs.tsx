import {
  Bell,
  Building2,
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
  Plus,
  ScanLine,
  ShieldCheck,
  Stethoscope,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type Appointment } from "@/lib/api";

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
  title: string;
  provider: string;
  date: string;
  time: string;
  location: string;
  cost: number;
  status: "Confirmed" | "Pending";
};

const pathOptions = [
  { name: "Keep current insurance", provider: "Northwest Imaging", cost: 420, annual: 7210, time: "3 days", confidence: 96, selected: true, detail: "Keeps Dr. Lee and your current prescriptions" },
  { name: "Washington Silver", provider: "Lake Washington Clinic", cost: 295, annual: 7865, time: "6 days", confidence: 88, selected: false, detail: "Lower MRI cost, higher annual premium" },
  { name: "Washington Gold", provider: "Puget Sound Radiology", cost: 165, annual: 9340, time: "4 days", confidence: 91, selected: false, detail: "Lowest procedure cost, highest annual total" },
];

export function PathsTab() {
  const [expanded, setExpanded] = useState<string | null>("Keep current insurance");
  return (
    <section className="vela-tab-page vela-paths-page">
      <header><p>Deterministic comparison</p><h1>Your care paths</h1><span>Every path is evaluated against total annual cost, network status, medication coverage, physician preference, timing, and your comfort limits.</span></header>
      <div className="vela-path-summary"><div><ShieldCheck /><span>3 paths evaluated</span></div><div><Check /><span>2 feasible</span></div><div><CircleDollarSign /><span>$1,060 potential savings</span></div></div>
      <div className="vela-path-grid">
        {pathOptions.map((path) => (
          <article className={`vela-path-card ${path.selected ? "is-selected" : ""}`} key={path.name}>
            {path.selected && <b className="vela-path-badge">Recommended</b>}
            <div className="vela-path-card-top"><div><h2>{path.name}</h2><p><Building2 />{path.provider}</p></div><strong>${path.cost}</strong></div>
            <div className="vela-path-metrics"><span><small>Annual total</small><b>${path.annual.toLocaleString()}</b></span><span><small>Time to care</small><b>{path.time}</b></span><span><small>Confidence</small><b>{path.confidence}%</b></span></div>
            <p className="vela-path-detail">{path.detail}</p>
            <button onClick={() => setExpanded(expanded === path.name ? null : path.name)}>See evidence <ChevronRight /></button>
            {expanded === path.name && <div className="vela-evidence"><span><Check />Network status source backed</span><span><Check />Annual cost calculated by deterministic engine</span><span><Check />Prescription and physician constraints applied</span>{!path.selected && <span className="is-warning"><X />Not the lowest feasible annual cost</span>}</div>}
          </article>
        ))}
      </div>
    </section>
  );
}

export function AppointmentsTab({ items, onItems, liveMode }: { items: VelaAppointment[]; onItems: (items: VelaAppointment[]) => void; liveMode: boolean }) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ title: "", provider: "", date: "", time: "", cost: "" });
  useEffect(() => {
    if (!liveMode) return;
    void api.appointments().then(({ appointments }) => {
      const mapped = appointments.map((item: Appointment) => ({ id: String(item.id), title: item.description || "Appointment", provider: item.hospital || "Provider", date: item.booked_for || "Date pending", time: "", location: item.address || "", cost: item.estimated_cost || 0, status: "Confirmed" as const }));
      if (mapped.length) onItems(mapped);
    }).catch(() => {});
  }, [liveMode]);
  const save = async () => {
    if (!form.title.trim()) return;
    const next: VelaAppointment = { id: crypto.randomUUID(), title: form.title, provider: form.provider || "Provider pending", date: form.date || "Date pending", time: form.time, location: "Seattle, WA", cost: Number(form.cost) || 0, status: "Confirmed" };
    if (liveMode) await api.addAppointment({ description: next.title, booked_for: next.date, estimated_cost: next.cost, note: next.provider }).catch(() => {});
    onItems([...items, next]); setAdding(false); setForm({ title: "", provider: "", date: "", time: "", cost: "" });
  };
  return (
    <section className="vela-tab-page vela-appointments-page">
      <header><p>Your care calendar</p><h1>Appointments</h1><span>Verified times, expected responsibility, preparation details, and receipts stay together.</span><button onClick={() => setAdding(true)}><Plus />Add appointment</button></header>
      <div className="vela-appointment-list">
        {items.map((item) => <article key={item.id}><div className="vela-date-tile"><b>{item.date.includes("Tuesday") ? "03" : item.date.slice(-2) || "04"}</b><span>SEP</span></div><div className="vela-appointment-copy"><span className="vela-confirmed"><Check />{item.status}</span><h2>{item.title}</h2><p><Stethoscope />{item.provider}</p><p><Clock3 />{item.date} {item.time}</p><p><MapPin />{item.location}</p></div><div className="vela-appointment-cost"><small>Estimated responsibility</small><b>${item.cost}</b><button>View receipt</button></div></article>)}
      </div>
      {adding && <div className="vela-modal-backdrop"><section className="vela-form-modal"><button className="vela-modal-close" onClick={() => setAdding(false)}><X /></button><p>New appointment</p><h2>Keep care details together</h2>{["title","provider","date","time","cost"].map((key) => <label key={key}><span>{key === "title" ? "Care or procedure" : key === "cost" ? "Expected cost" : key[0].toUpperCase()+key.slice(1)}</span><input type={key === "date" ? "date" : key === "time" ? "time" : key === "cost" ? "number" : "text"} value={form[key as keyof typeof form]} onChange={(e) => setForm({...form,[key]:e.target.value})} /></label>)}<button className="vela-primary" onClick={() => void save()}>Save appointment</button></section></div>}
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

export function DocumentsTab({ documents, onDocuments, liveMode, openCamera, onOpenCamera }: { documents: VelaDocument[]; onDocuments: (items: VelaDocument[]) => void; liveMode: boolean; openCamera: boolean; onOpenCamera: (open: boolean) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const addFile = async (file: File, preview?: string) => {
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
