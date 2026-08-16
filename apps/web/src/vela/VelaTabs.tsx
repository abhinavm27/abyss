import { Bell, Building2, CalendarDays, Camera, Check, ChevronRight, CircleDollarSign, Clock3, CreditCard, Download, FileCheck2, FileText, HeartHandshake, Languages, MapPin, Network, Plus, ReceiptText, ScanLine, ShieldCheck, Stethoscope, Trash2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type CareContext, type CareJourneySnapshot, type MemberMemory, type MessagingPreference, type NotificationPreview, type PreparedReportDocument, type ReportAnalysis } from "@/lib/api";

export type VelaDocument = {
  id: string;
  name: string;
  kind: "Insurance card" | "Summary of Benefits" | "Referral/order" | "Bill";
  status: "Verified" | "Review needed" | "Processing";
  added: string;
  preview?: string;
};

export type VelaDocumentKind = VelaDocument["kind"];

export type ReferralIntakeReview = {
  documentId: string;
  fileName: string;
  prepared: PreparedReportDocument;
  analysis: ReportAnalysis | null;
  selectedOrderIds: string[];
  phase: "consent" | "analyzing" | "review" | "confirming" | "confirmed";
  error: string | null;
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

const money = (value: number) =>
  value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
const dateTile = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? { day: "—", month: "TBD" }
    : {
        day: parsed.toLocaleDateString("en-US", { day: "2-digit" }),
        month: parsed.toLocaleDateString("en-US", { month: "short" }).toUpperCase(),
      };
};

export function PathsTab({ journey, context, busy, matchingReason, onSelect, onExplain, onOpenJourney }: { journey: CareJourneySnapshot | null; context: CareContext | null; busy: boolean; matchingReason: string | null; onSelect: (hospitalId: number) => void; onExplain: () => void; onOpenJourney: (journeyId: string) => void }) {
  const [expanded, setExpanded] = useState<number | null>(journey?.current_plan_options[0]?.hospital_id ?? null);
  const options = journey?.current_plan_options ?? [];
  const selected = journey?.selected_care_path;
  return (
    <section className="vela-tab-page vela-paths-page">
      <header>
        <p>Current-plan comparison</p>
        <h1>Your care paths</h1>
        <span>Hospital-published prices are evaluated with your current plan. Network verification happens only after you choose, and choosing never books care.</span>
      </header>
      {journey && (
        <div className="vela-path-summary">
          <div>
            <ShieldCheck />
            <span>{journey.current_plan_name}</span>
          </div>
          <div>
            <Check />
            <span>{options.length} hospital options</span>
          </div>
          <div>
            <CircleDollarSign />
            <span>Current coverage only</span>
          </div>
        </div>
      )}
      {selected && (
        <article className="vela-path-selected">
          <span>Selected care path</span>
          <h2>{selected.hospital}</h2>
          <p>
            {selected.plan_name} · {money(selected.estimated_member_cost)} estimated member cost
          </p>
          <b>{selected.network_status === "sandbox_verified" ? "Network sandbox-verified" : "Verification pending"}</b>
        </article>
      )}
      {options.length > 0 ? (
        <div className="vela-path-grid">
          {options.map((path, index) => {
            const isSelected = selected?.hospital_id === path.hospital_id;
            return (
              <article className={`vela-path-card ${index === 0 ? "is-selected" : ""}`} key={path.hospital_id}>
                {index === 0 && <b className="vela-path-badge">Lowest current-plan scenario</b>}
                <div className="vela-path-card-top">
                  <div>
                    <h2>{path.hospital}</h2>
                    <p>
                      <Building2 />
                      {path.plan_name}
                    </p>
                  </div>
                  <strong>{money(path.estimated_member_cost)}</strong>
                </div>
                <div className="vela-path-metrics">
                  <span>
                    <small>Published rate</small>
                    <b>{money(path.published_typical_rate)}</b>
                  </span>
                  <span>
                    <small>Annual scenario</small>
                    <b>{money(path.estimated_annual_total)}</b>
                  </span>
                  <span>
                    <small>Network</small>
                    <b>Pending</b>
                  </span>
                </div>
                <p className="vela-path-detail">
                  Scenario estimate, not a guarantee. Deductible remaining: {money(path.deductible_remaining)} · {Math.round(path.coinsurance_rate * 100)}% coinsurance.
                </p>
                <button onClick={() => setExpanded(expanded === path.hospital_id ? null : path.hospital_id)}>
                  See evidence <ChevronRight />
                </button>
                {expanded === path.hospital_id && (
                  <div className="vela-evidence">
                    <span>
                      <Check />
                      Hospital-published rate retained with source
                    </span>
                    <span>
                      <Check />
                      Member cost calculated by deterministic rules
                    </span>
                    <span>
                      <Check />
                      Current insurance remains unchanged
                    </span>
                    <span className="is-warning">
                      <X />
                      Network status still requires verification
                    </span>
                  </div>
                )}
                {!isSelected && (
                  <button className="vela-path-choose" disabled={busy || Boolean(selected)} onClick={() => onSelect(path.hospital_id)}>
                    Choose this hospital
                  </button>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="vela-empty-live">
          <Network />
          <h2>No ranked paths for this journey yet</h2>
          <p>Continue the intake conversation so the Knowledge and Matching agents can resolve the procedure and build current-plan options.</p>
        </div>
      )}
      {journey && options.length > 0 && (
        <button className="vela-explain-paths" disabled={busy} onClick={onExplain}>
          Ask Nemotron to explain the ranking
        </button>
      )}
      {matchingReason && (
        <div className="vela-matching-reason">
          <b>Matching Agent explanation</b>
          <p>{matchingReason}</p>
        </div>
      )}
      {context && context.journeys.length > 1 && (
        <section className="vela-journey-history">
          <h2>Other care journeys</h2>
          {context.journeys
            .filter((item) => item.journey_id !== journey?.journey_id)
            .map((item) => (
              <button key={item.journey_id} onClick={() => onOpenJourney(item.journey_id)}>
                <span>
                  <b>{item.title}</b>
                  <small>
                    {item.stage} · {item.status}
                  </small>
                </span>
                <ChevronRight />
              </button>
            ))}
        </section>
      )}
    </section>
  );
}

export function AppointmentsTab({ items, onItems, liveMode, journey, busy, bookingText, onBookingText, onFindSlots, onSelectSlot, onBook }: { items: VelaAppointment[]; onItems: (items: VelaAppointment[]) => void; liveMode: boolean; journey: CareJourneySnapshot | null; busy: boolean; bookingText: string; onBookingText: (text: string) => void; onFindSlots: () => void; onSelectSlot: (slotId: string) => void; onBook: () => void }) {
  const [adding, setAdding] = useState(false);
  const [receiptItem, setReceiptItem] = useState<VelaAppointment | null>(null);
  const [receiptJourney, setReceiptJourney] = useState<CareJourneySnapshot | null>(null);
  const [form, setForm] = useState({
    title: "",
    provider: "",
    date: "",
    time: "",
    cost: "",
  });
  const save = async () => {
    if (!form.title.trim()) return;
    const next: VelaAppointment = {
      id: crypto.randomUUID(),
      title: form.title,
      provider: form.provider || "Provider pending",
      date: form.date || "Date pending",
      time: form.time,
      location: "Seattle, WA",
      cost: Number(form.cost) || 0,
      status: "Confirmed",
    };
    if (liveMode)
      await api
        .addAppointment({
          description: next.title,
          booked_for: next.date,
          estimated_cost: next.cost,
          note: next.provider,
        })
        .catch(() => {});
    onItems([...items, next]);
    setAdding(false);
    setForm({ title: "", provider: "", date: "", time: "", cost: "" });
  };
  const openReceipt = async (item: VelaAppointment) => {
    setReceiptItem(item);
    setReceiptJourney(item.journeyId && item.journeyId !== journey?.journey_id ? null : journey);
    if (item.journeyId && item.journeyId !== journey?.journey_id) {
      try {
        setReceiptJourney(await api.journey(item.journeyId));
      } catch {
        setReceiptJourney(null);
      }
    }
  };
  return (
    <section className="vela-tab-page vela-appointments-page">
      <header>
        <p>Your care calendar</p>
        <h1>Appointments</h1>
        <span>Verified times, expected responsibility, preparation details, and receipts stay together.</span>
        <button onClick={() => setAdding(true)}>
          <Plus />
          Add appointment
        </button>
      </header>
      {journey?.stage === "book" && (
        <section className="vela-booking-live">
          <div>
            <span>Booking Agent</span>
            <h2>{journey.reschedule_original_slot ? "Choose a replacement appointment" : "Choose a synthetic appointment"}</h2>
            <p>{journey.reschedule_original_slot ? "Your original appointment stays confirmed until its replacement is confirmed. Both the replacement booking and original cancellation have exact approval scopes." : "Tell the agent your date range and time preference. Selecting a slot does not book it; the exact appointment gets a separate approval."}</p>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              onFindSlots();
            }}
          >
            <input value={bookingText} onChange={(event) => onBookingText(event.target.value)} aria-label="Booking preferences" placeholder="Aug 30 to Sep 15, mornings" />
            <button disabled={busy || !bookingText.trim()}>Find slots</button>
          </form>
          {journey.booking_slots.length > 0 && (
            <div className="vela-live-slots">
              {journey.booking_slots.map((slot) => (
                <button key={slot.slot_id} disabled={busy || slot.status !== "available"} className={journey.selected_booking_slot?.slot_id === slot.slot_id ? "is-selected" : ""} onClick={() => onSelectSlot(slot.slot_id)}>
                  <CalendarDays />
                  <span>
                    <b>{new Date(slot.starts_at).toLocaleString()}</b>
                    <small>
                      {slot.hospital} · {slot.duration_minutes} minutes
                      {slot.retry_demo ? " · retry demonstration" : ""}
                    </small>
                  </span>
                  {journey.selected_booking_slot?.slot_id === slot.slot_id && <Check />}
                </button>
              ))}
            </div>
          )}
          {journey.selected_booking_slot && journey.booking_consent_scope && (
            <div className="vela-exact-consent">
              <ShieldCheck />
              <div>
                <b>{journey.reschedule_original_slot ? "Exact replacement and cancellation approval" : "Exact booking approval"}</b>
                <p>
                  {journey.booking_consent_scope}
                  {journey.cancellation_consent_scope ? ` · then ${journey.cancellation_consent_scope}` : ""}
                </p>
              </div>
              <button disabled={busy || journey.booking_tasks.some((task) => task.status === "scheduled")} onClick={onBook}>
                {journey.reschedule_original_slot ? "Approve replacement, then cancel original" : "Approve and book this slot"}
              </button>
            </div>
          )}
          {journey.booking_tasks.map((task) => (
            <div className={`vela-booking-task status-${task.status}`} key={task.task_id}>
              <b>Booking task: {task.status}</b>
              <span>
                {task.attempts} attempt(s)
                {task.status === "scheduled" ? ` · retry ${new Date(task.next_attempt_at).toLocaleTimeString()}` : ""}
              </span>
            </div>
          ))}
        </section>
      )}
      <div className="vela-appointment-list">
        {items.map((item) => {
          const tile = dateTile(item.date);
          return (
            <article key={item.id}>
              <div className="vela-date-tile">
                <b>{tile.day}</b>
                <span>{tile.month}</span>
              </div>
              <div className="vela-appointment-copy">
                <span className="vela-confirmed">
                  <Check />
                  {item.status}
                </span>
                <h2>{item.title}</h2>
                <p>
                  <Stethoscope />
                  {item.provider}
                </p>
                <p>
                  <Clock3 />
                  {item.date} {item.time}
                </p>
                <p>
                  <MapPin />
                  {item.location}
                </p>
              </div>
              <div className="vela-appointment-cost">
                <small>Estimated responsibility</small>
                <b>${item.cost}</b>
                <button onClick={() => void openReceipt(item)}>View receipt</button>
              </div>
            </article>
          );
        })}
      </div>
      {items.length === 0 && journey?.stage !== "book" && (
        <div className="vela-empty-live">
          <CalendarDays />
          <h2>No confirmed appointments yet</h2>
          <p>Start or resume a care journey. Once an exact sandbox booking is approved and confirmed, it appears here with its receipt.</p>
        </div>
      )}
      {adding && (
        <div className="vela-modal-backdrop">
          <section className="vela-form-modal">
            <button className="vela-modal-close" onClick={() => setAdding(false)}>
              <X />
            </button>
            <p>New appointment</p>
            <h2>Keep care details together</h2>
            {["title", "provider", "date", "time", "cost"].map((key) => (
              <label key={key}>
                <span>{key === "title" ? "Care or procedure" : key === "cost" ? "Expected cost" : key[0].toUpperCase() + key.slice(1)}</span>
                <input type={key === "date" ? "date" : key === "time" ? "time" : key === "cost" ? "number" : "text"} value={form[key as keyof typeof form]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              </label>
            ))}
            <button className="vela-primary" onClick={() => void save()}>
              Save appointment
            </button>
          </section>
        </div>
      )}
      {receiptItem && (
        <div className="vela-modal-backdrop">
          <section className="vela-form-modal vela-receipt-modal">
            <button
              className="vela-modal-close"
              aria-label="Close receipt"
              onClick={() => {
                setReceiptItem(null);
                setReceiptJourney(null);
              }}
            >
              <X />
            </button>
            <p>Sandbox audit receipt</p>
            <h2>{receiptItem.title}</h2>
            <div className="vela-receipt-summary">
              <span>
                <Check />
                {receiptItem.status}
              </span>
              <b>{receiptItem.provider}</b>
              <small>
                {receiptItem.date} {receiptItem.time}
              </small>
            </div>
            <div className="vela-receipt-list">
              {receiptJourney?.receipts.length ? (
                receiptJourney.receipts.map((receipt) => (
                  <div key={`${receipt.action}-${receipt.recorded_at}`}>
                    <span>{receipt.action.replace(/_/g, " ")}</span>
                    <b>{receipt.status}</b>
                    <small>{receipt.scope}</small>
                  </div>
                ))
              ) : (
                <p>{receiptItem.journeyId ? "Loading this journey’s receipts…" : "This appointment was recorded manually and has no sandbox action receipt."}</p>
              )}
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

const documentChoices: Array<{
  kind: VelaDocumentKind;
  title: string;
  detail: string;
  accept: string;
  icon: typeof CreditCard;
}> = [
  { kind: "Insurance card", title: "Insurance card", detail: "Read payer and member details", accept: "image/*", icon: CreditCard },
  { kind: "Summary of Benefits", title: "Summary of Benefits", detail: "Read deductible and coverage rules", accept: ".pdf,application/pdf", icon: FileCheck2 },
  { kind: "Referral/order", title: "Referral or order", detail: "Confirm exactly what was ordered", accept: ".pdf,.txt,application/pdf,text/plain", icon: FileText },
  { kind: "Bill", title: "Medical bill", detail: "Prepare a published-rate check", accept: "image/*,.pdf,application/pdf", icon: ReceiptText },
];

function DocumentIcon({ kind }: { kind: VelaDocumentKind }) {
  if (kind === "Insurance card") return <ScanLine />;
  if (kind === "Bill") return <ReceiptText />;
  if (kind === "Summary of Benefits") return <FileCheck2 />;
  return <FileText />;
}

function ReportIntakePanel({ review, busy, onAnalyze, onToggleOrder, onConfirm, onClose }: {
  review: ReferralIntakeReview;
  busy: boolean;
  onAnalyze: () => void;
  onToggleOrder: (orderId: string) => void;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const orders = review.analysis?.orders ?? [];
  const canConfirm = review.selectedOrderIds.length > 0 && review.phase === "review";
  return (
    <section className="vela-report-review" aria-labelledby="report-review-title">
      <header>
        <div>
          <span>Referral intake</span>
          <h2 id="report-review-title">Review before it enters your journey</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="Close referral review"><X /></button>
      </header>

      <div className="vela-report-source">
        <FileText aria-hidden />
        <div>
          <b>{review.fileName}</b>
          <small>{(review.prepared.byte_count / 1024).toFixed(1)} KB · raw file not retained</small>
        </div>
        <span>Prepared</span>
      </div>

      {review.phase === "consent" && (
        <div className="vela-report-consent">
          <ShieldCheck aria-hidden />
          <div>
            <span>Exact processing permission</span>
            <p>{review.prepared.consent_scope}</p>
            <code>{review.prepared.source_hash}</code>
            <small>Analyze sends this exact file to the authenticated Hermes gateway for order extraction. Uploading alone did not analyze it.</small>
          </div>
          <button type="button" disabled={busy} onClick={onAnalyze}>Analyze this exact file</button>
        </div>
      )}

      {review.phase === "analyzing" && (
        <div className="vela-report-working" role="status" aria-live="polite">
          <i /><div><b>Reading only explicit clinician orders</b><span>Checking every candidate against its source quote…</span></div>
        </div>
      )}

      {review.analysis && review.phase !== "analyzing" && review.phase !== "confirmed" && (
        <div className="vela-report-candidates">
          <div className="vela-report-candidates-heading">
            <div><span>Source-backed candidates</span><h3>{orders.length ? `Select what applies (${orders.length})` : "No explicit order found"}</h3></div>
            <small>{review.analysis.consent.approved ? "Processing approved" : "Not approved"}</small>
          </div>
          {orders.length ? (
            <fieldset>
              <legend className="vela-visually-hidden">Select orders to add to the care journey</legend>
              {orders.map((order) => {
                const selected = review.selectedOrderIds.includes(order.order_id);
                return (
                  <label className={selected ? "is-selected" : ""} key={order.order_id}>
                    <input type="checkbox" checked={selected} onChange={() => onToggleOrder(order.order_id)} />
                    <span className="vela-report-check"><Check /></span>
                    <span className="vela-report-order-copy">
                      <b>{order.service_name}{order.service_code ? <em>{order.service_code}</em> : null}</b>
                      <q>{order.source_quote}</q>
                      <small>{order.source_location} · {Math.round(order.confidence * 100)}% extraction confidence · {order.verification_status.replace(/_/g, " ")}</small>
                    </span>
                  </label>
                );
              })}
            </fieldset>
          ) : (
            <div className="vela-report-empty">
              <FileText />
              <p>VELA could not find a test, procedure, imaging order, or referral explicitly written in this document. Nothing was added to a journey.</p>
            </div>
          )}
          {orders.length > 0 && (
            <footer>
              <p>Only selected orders become verified journey facts. You can leave uncertain candidates unchecked.</p>
              <button type="button" disabled={busy || !canConfirm} onClick={onConfirm}>
                {review.phase === "confirming" ? "Confirming…" : `Confirm ${review.selectedOrderIds.length || "selected"} order${review.selectedOrderIds.length === 1 ? "" : "s"}`}
              </button>
            </footer>
          )}
        </div>
      )}

      {review.phase === "confirmed" && (
        <div className="vela-report-complete" role="status">
          <Check />
          <div><b>Confirmed and added to your journey</b><span>The selected order is now a source-backed fact. VELA can use it to find current-plan hospital options.</span></div>
        </div>
      )}

      {review.error && <div className="vela-report-error" role="alert">{review.error}</div>}
    </section>
  );
}

export function DocumentsTab({ documents, onDocuments, busy, referralReview, onUploadDocument, onCaptureReferral, onAnalyzeReferral, onToggleReferralOrder, onConfirmReferral, onCloseReferral }: {
  documents: VelaDocument[];
  onDocuments: (items: VelaDocument[]) => void;
  busy: boolean;
  referralReview: ReferralIntakeReview | null;
  onUploadDocument: (kind: VelaDocumentKind, file: File) => Promise<void>;
  onCaptureReferral: () => void;
  onAnalyzeReferral: () => void;
  onToggleReferralOrder: (orderId: string) => void;
  onConfirmReferral: () => void;
  onCloseReferral: () => void;
}) {
  const inputRefs = useRef<Partial<Record<VelaDocumentKind, HTMLInputElement | null>>>({});
  return (
    <section className="vela-tab-page vela-documents-page">
      <header>
        <p>Your evidence locker</p>
        <h1>Documents</h1>
        <span>Choose the document you have. VELA applies a different, bounded workflow to each source.</span>
      </header>

      <div className="vela-document-choices" aria-label="Choose a document type">
        {documentChoices.map((choice) => {
          const Icon = choice.icon;
          return (
            <div key={choice.kind}>
              <button type="button" disabled={busy} onClick={() => inputRefs.current[choice.kind]?.click()}>
                <Icon aria-hidden />
                <span><b>{choice.title}</b><small>{choice.detail}</small></span>
                <Upload aria-hidden />
              </button>
              {choice.kind === "Referral/order" && (
                <button className="vela-document-camera" type="button" disabled={busy} onClick={onCaptureReferral}>
                  <Camera aria-hidden /> Scan with camera
                </button>
              )}
              <input
                ref={(element) => { inputRefs.current[choice.kind] = element; }}
                hidden
                type="file"
                accept={choice.accept}
                aria-label={`Upload ${choice.title}`}
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) void onUploadDocument(choice.kind, file);
                  event.currentTarget.value = "";
                }}
              />
            </div>
          );
        })}
      </div>

      {referralReview && (
        <ReportIntakePanel review={referralReview} busy={busy} onAnalyze={onAnalyzeReferral} onToggleOrder={onToggleReferralOrder} onConfirm={onConfirmReferral} onClose={onCloseReferral} />
      )}

      <div className="vela-document-layout">
        <aside>
          <ShieldCheck />
          <h2>Permission is a step</h2>
          <p>Uploading identifies the source. Referral analysis starts only after you approve the exact hash-bound scope, and extracted orders remain candidates until you confirm them.</p>
          <span><Check /> Raw referral files are not retained</span>
          <span><Check /> Quotes and page locations stay visible</span>
          <span><Check /> Confirmed facts keep their provenance</span>
        </aside>
        <div className="vela-document-list">
          {documents.length ? documents.map((document) => (
            <article key={document.id}>
              {document.preview ? <img src={document.preview} alt="Uploaded document preview" /> : <div className="vela-file-icon"><DocumentIcon kind={document.kind} /></div>}
              <div>
                <span>{document.kind}</span>
                <h2>{document.name}</h2>
                <p>Added {document.added}</p>
              </div>
              <b className={`status-${document.status.toLowerCase().replace(" ", "-")}`}>
                {document.status === "Verified" && <Check />}
                {document.status}
              </b>
              <button aria-label={`Remove ${document.name}`} onClick={() => onDocuments(documents.filter((item) => item.id !== document.id))}>
                <Trash2 />
              </button>
            </article>
          )) : (
            <div className="vela-document-empty"><FileText /><h2>No documents yet</h2><p>Add only the source needed for this care journey.</p></div>
          )}
        </div>
      </div>
    </section>
  );
}

export function PreferencesTab({ journey }: { journey: CareJourneySnapshot | null }) {
  const [prefs, setPrefs] = useState({
    distance: 15,
    maxCost: 500,
    language: "English",
    keepDoctor: true,
    emailReceipts: true,
    morning: true,
  });
  const [messaging, setMessaging] = useState<MessagingPreference | null>(null);
  const [memory, setMemory] = useState<MemberMemory | null>(null);
  const [messagePreview, setMessagePreview] = useState<NotificationPreview | null>(null);
  const [messageBusy, setMessageBusy] = useState(false);
  const [messageStatus, setMessageStatus] = useState("");
  useEffect(() => {
    void api.messagingPreference().then(setMessaging).catch(() => setMessaging(null));
    void api.memberMemory().then(setMemory).catch(() => setMemory(null));
  }, []);
  const toggle = (key: keyof typeof prefs) => setPrefs({ ...prefs, [key]: !prefs[key] });
  const toggleDiscord = async () => {
    if (!messaging || messageBusy) return;
    setMessageBusy(true);
    setMessageStatus("");
    try {
      const next = await api.setMessagingPreference(!messaging.enabled, messaging.destination_label);
      setMessaging(next);
      setMessagePreview(null);
      setMessageStatus(next.enabled ? "Discord link notifications enabled." : "Discord notifications disabled.");
    } catch (error) {
      setMessageStatus(error instanceof Error ? error.message : "Discord preference could not be updated.");
    } finally {
      setMessageBusy(false);
    }
  };
  const previewDiscord = async () => {
    if (!journey || messageBusy) return;
    setMessageBusy(true);
    setMessageStatus("");
    try {
      setMessagePreview(await api.notificationPreview(journey.journey_id));
    } catch (error) {
      setMessageStatus(error instanceof Error ? error.message : "The notice could not be prepared.");
    } finally {
      setMessageBusy(false);
    }
  };
  const sendDiscord = async () => {
    if (!messagePreview || messageBusy) return;
    setMessageBusy(true);
    try {
      const receipt = await api.sendNotification(messagePreview.result_ref, messagePreview.consent_scope);
      setMessageStatus(`Delivered to Discord · receipt ${receipt.confirmation_reference}`);
      setMessagePreview(null);
    } catch (error) {
      setMessageStatus(error instanceof Error ? error.message : "The approved notice could not be sent.");
    } finally {
      setMessageBusy(false);
    }
  };
  return (
    <section className="vela-tab-page vela-preferences-page">
      <header>
        <p>Your decision rules</p>
        <h1>Preferences</h1>
        <span>VELA applies these boundaries before it ranks a care path. You can change them at any time.</span>
      </header>
      <article className="vela-alternative-path">
        <span>Separate feature</span>
        <h2>Insurance price comparison</h2>
        <p>Explore premium and annual-cost scenarios separately from hospital matching. It does not change your current plan or interrupt an active booking journey.</p>
      </article>
      <div className="vela-preference-grid">
        <article>
          <div className="vela-pref-title">
            <MapPin />
            <div>
              <h2>Travel distance</h2>
              <p>Maximum distance for recommended care</p>
            </div>
            <b>{prefs.distance} miles</b>
          </div>
          <input type="range" min="1" max="50" value={prefs.distance} onChange={(e) => setPrefs({ ...prefs, distance: Number(e.target.value) })} />
        </article>
        <article>
          <div className="vela-pref-title">
            <CircleDollarSign />
            <div>
              <h2>Comfortable out of pocket cost</h2>
              <p>VELA flags options above this amount</p>
            </div>
            <b>${prefs.maxCost}</b>
          </div>
          <input type="range" min="50" max="2000" step="50" value={prefs.maxCost} onChange={(e) => setPrefs({ ...prefs, maxCost: Number(e.target.value) })} />
        </article>
        <article>
          <div className="vela-pref-title">
            <HeartHandshake />
            <div>
              <h2>Keep my current physician</h2>
              <p>Treat this as a hard matching constraint</p>
            </div>
            <button className={prefs.keepDoctor ? "is-on" : ""} onClick={() => toggle("keepDoctor")}>
              <i />
            </button>
          </div>
        </article>
        <article>
          <div className="vela-pref-title">
            <Clock3 />
            <div>
              <h2>Morning appointments</h2>
              <p>Prefer appointments before noon</p>
            </div>
            <button className={prefs.morning ? "is-on" : ""} onClick={() => toggle("morning")}>
              <i />
            </button>
          </div>
        </article>
        <article>
          <div className="vela-pref-title">
            <Languages />
            <div>
              <h2>Language</h2>
              <p>Voice, explanations, and receipts</p>
            </div>
            <select value={prefs.language} onChange={(e) => setPrefs({ ...prefs, language: e.target.value })}>
              <option>English</option>
              <option>Spanish</option>
              <option>French</option>
              <option>Mandarin</option>
            </select>
          </div>
        </article>
        <article>
          <div className="vela-pref-title">
            <Bell />
            <div>
              <h2>Discord updates</h2>
              <p>Link-only notices · no care details or prices</p>
            </div>
            <button
              className={messaging?.enabled ? "is-on" : ""}
              disabled={!messaging?.webhook_configured || messageBusy}
              onClick={() => void toggleDiscord()}
              aria-label="Toggle Discord link notifications"
            >
              <i />
            </button>
          </div>
          <div className="vela-discord-detail">
            <span>{messaging?.webhook_configured ? `Connected · ${messaging.destination_label}` : "Discord webhook is not configured"}</span>
            {messaging?.enabled && journey && !messagePreview && <button onClick={() => void previewDiscord()} disabled={messageBusy}>Preview journey notice</button>}
            {messagePreview && (
              <div>
                <p>{messagePreview.body}</p>
                <button onClick={() => void sendDiscord()} disabled={messageBusy}>Approve and send this exact notice</button>
              </div>
            )}
            {messageStatus && <b>{messageStatus}</b>}
          </div>
          <div className="vela-pref-title second">
            <Download />
            <div>
              <h2>Email receipts</h2>
              <p>Send consent and sandbox action receipts</p>
            </div>
            <button className={prefs.emailReceipts ? "is-on" : ""} onClick={() => toggle("emailReceipts")}>
              <i />
            </button>
          </div>
        </article>
        <article>
          <div className="vela-pref-title">
            <Network />
            <div>
              <h2>Shared member memory</h2>
              <p>Available to journey, voice, and Discord agents</p>
            </div>
            <b>{memory?.current_facts.length ?? 0} facts</b>
          </div>
          <div className="vela-memory-detail">
            <span>{memory?.active_plan?.label || memory?.active_plan?.payer_name || "No current plan saved"}</span>
            <small>{memory?.agent_events.length ?? 0} recent ledger events · model snapshots exclude credentials and member identifiers</small>
          </div>
        </article>
      </div>
      <p className="vela-preferences-saved">
        <Check />
        Decision preferences stay on this device; member memory and messaging consent are stored on the server
      </p>
    </section>
  );
}
