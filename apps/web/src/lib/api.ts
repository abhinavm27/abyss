// REST client. Same origin in dev (Vite proxies /api); VITE_API_URL points at
// the backend directly when the app is packaged by Capacitor.

const BASE = import.meta.env.VITE_API_URL || "";

// The session token. Held in localStorage so a reload does not sign you out;
// sent as a bearer header rather than a cookie because the packaged iOS app
// runs on capacitor://localhost and calls the API cross-origin.
const TOKEN_KEY = "abyss.token";

let token: string | null = null;
try {
  token = localStorage.getItem(TOKEN_KEY);
} catch {
  // Private browsing can throw on access; the app still works, just signed out.
}

export function getToken(): string | null {
  return token;
}

export function setToken(next: string | null): void {
  token = next;
  try {
    if (next) localStorage.setItem(TOKEN_KEY, next);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* see above */
  }
}

/** Thrown when the server rejects the session, so the shell can sign out
 *  rather than showing an error on a screen the member cannot use. */
export class NotSignedIn extends Error {
  constructor() {
    super("session expired");
    this.name = "NotSignedIn";
  }
}

export interface Citation {
  mrf_url: string | null;
  source_page_url: string | null;
  last_updated_on: string | null;
}

export interface Breakdown {
  label: string;
  amount: number;
  detail: string;
}

export interface Estimate {
  expected: number;
  low: number;
  high: number;
  allowed: number;
  breakdown: Breakdown[];
  caveats: string[];
  /** False when the plan carries no rule for this service, so `expected` is a
   *  floor rather than a forecast. The card says "at least" in that case. */
  complete?: boolean;
}

export interface HospitalPrice {
  hospital_id: number;
  hospital: string;
  description: string | null;
  code: string;
  code_type: string | null;
  rate_count: number;
  low: number;
  typical: number;
  high: number;
  address: string | null;
  citation: Citation;
  estimate: Estimate;
}

export interface Candidate {
  code: string;
  code_type: string | null;
  description: string | null;
  n: number;
}

export interface PriceResponse {
  query: string;
  resolved: { code: string; code_type: string | null; description?: string | null } | null;
  resolution: string;
  plan_configured?: boolean;
  needs_confirmation?: boolean;
  candidates?: Candidate[];
  hospitals: HospitalPrice[];
  cash_prices?: { hospital: string; low: number; high: number }[];
  formula_priced_rows?: number;
  message?: string;
}

export interface PlanBody {
  label?: string | null;
  payer_name?: string | null;
  qhp_plan_id?: string | null;
  deductible: number;
  deductible_met: number;
  coinsurance_pct: number;
  copay?: number | null;
  oop_max: number;
  oop_met: number;
}

export interface SbcBenefit {
  kind: "copay" | "coinsurance" | "no_charge" | "not_covered";
  amount: number;
  after_deductible: boolean;
  /** The cell as it appeared in the PDF, so the member can check it. */
  source_text: string;
}

export interface SbcResult {
  filename: string;
  plan_name: string | null;
  coverage_period: string | null;
  plan_type: string | null;
  deductible: number | null;
  oop_max: number | null;
  benefits: Record<string, SbcBenefit>;
  warnings: string[];
}

export interface SbcApply {
  label?: string | null;
  payer_name?: string | null;
  deductible: number;
  deductible_met: number;
  oop_max: number;
  oop_met: number;
  benefits: {
    category: string;
    kind: string;
    amount: number;
    after_deductible: boolean;
  }[];
}

/** One ingested hospital, as listed on the coverage screen. */
export interface Hospital {
  id: number;
  name: string;
  address: string | null;
  last_updated_on: string | null;
  mrf_url: string | null;
  rates: number;
}

/** What a photo of an insurance card can actually yield.
 *
 * Note what is absent: deductible, out-of-pocket maximum and coinsurance. Cards
 * do not print them, so the scan does not report them — `provides_cost_sharing`
 * is always false and exists to make that explicit to any caller. */
export interface CardScan {
  filename: string;
  payer_name: string | null;
  plan_name: string | null;
  plan_type: string | null;
  member_id: string | null;
  group_number: string | null;
  rx_bin: string | null;
  copays: Record<string, number>;
  warnings: string[];
  provides_cost_sharing: false;
}

export interface PreparedReportDocument {
  source_name: string;
  media_type: "application/pdf" | "text/plain";
  byte_count: number;
  source_hash: string;
  consent_action: "process_documents";
  consent_scope: string;
  raw_document_persisted: false;
}

export interface ReportCandidateOrder {
  order_id: string;
  service_name: string;
  service_code: string | null;
  source_quote: string;
  source_location: string;
  source: string;
  observed_at: string;
  confidence: number;
  verification_status: string;
  confirmed: boolean;
}

export interface ReportAnalysis {
  analysis_id: string;
  source_name: string;
  source_hash: string;
  observed_at: string;
  journey_id: string | null;
  orders: ReportCandidateOrder[];
  confirmed_orders: Array<{
    order_id: string;
    journey_id: string | null;
    source_quote: string;
    source_location: string;
    confirmed_at: string;
  }>;
  requires_confirmation: boolean;
  consent: {
    action: "process_documents";
    approved: boolean;
    actor: string;
    scope: string;
    recorded_at: string;
  };
  raw_document_persisted: false;
}

export interface ConfirmedReportIntake {
  analysis: ReportAnalysis;
  options_ready: boolean;
  journey: CareJourneySnapshot;
}

/** Which figure off a bill the member is holding.
 *
 * Not cosmetic: a gross charge runs several times the negotiated rate, so the
 * same number is unremarkable as one and alarming as the other. */
export type AmountKind = "allowed" | "charged" | "paid";

export interface BillCheck {
  resolved: { code: string; description?: string | null } | null;
  candidates?: Candidate[];
  message?: string;
  amount_kind?: AmountKind;
  amount?: number;
  hospital?: string | null;
  verdict?: {
    status: "above" | "within" | "below";
    over_by?: number;
    /** Share of published rates below this amount. Carries the answer when the
     *  range is too wide to discriminate. */
    percentile?: number;
    headline: string;
    detail: string;
  };
  /** Present when the check ran against every hospital at once, where the
   *  spread is wide enough that any amount looks normal. */
  scope_warning?: string | null;
  reference?: { low: number; high: number; median?: number; count?: number; basis: string };
  cash_price?: { low: number; high: number } | null;
  estimate?: Estimate;
  note?: string;
}

/** An appointment the member arranged themselves. ABYSS never books. */
export interface Appointment {
  id: number;
  hospital_id: number | null;
  hospital: string | null;
  address: string | null;
  source_page_url: string | null;
  code: string | null;
  description: string | null;
  booked_for: string | null;
  estimated_cost: number | null;
  note: string | null;
  created_at: string;
}

/** One of the member's own plans, as listed for comparison. */
export interface MyPlan {
  id: number;
  label: string | null;
  payer_name: string | null;
  qhp_plan_id: string | null;
  deductible: number;
  deductible_met: number;
  coinsurance_pct: number;
  copay: number | null;
  oop_max: number;
  oop_met: number;
  is_active: number;
}

export interface PlanComparison {
  query: string;
  resolved: { code: string; description?: string | null } | null;
  hospital?: string;
  allowed?: number;
  plans: {
    plan_id: number;
    label: string | null;
    payer_name: string | null;
    is_active: number;
    estimate: Estimate;
  }[];
  message?: string;
}

export interface CareJourneySnapshot {
  journey_id: string;
  stage: string;
  onboarding_missing: string[];
  onboarding_questions: string[];
  procedure_resolution: { code: string | null; canonical_name: string | null; confidence: string; candidates: string[]; needs_confirmation: boolean } | null;
  evaluations: {
    plan_id: string;
    plan_name: string;
    feasible: boolean;
    annual_total: number;
    annual_premium: number;
    hard_failures: string[];
  }[];
  hospital_rates: {
    hospital_id: number;
    hospital: string;
    address: string | null;
    description: string | null;
    procedure_code: string;
    code_type: string | null;
    rate_count: number;
    low: number;
    typical: number;
    high: number;
    source: { mrf_url: string | null; source_page_url: string | null; published_at: string | null; retrieved_at: string };
    confidence: number;
    verification_status: string;
    consent_requirement: string;
    network_status: "unknown";
  }[];
  current_plan: string;
  current_plan_name: string;
  current_plan_options: {
    plan_id: string;
    plan_name: string;
    coverage_status: "current";
    hospital_id: number;
    hospital: string;
    address: string | null;
    procedure_code: string;
    published_typical_rate: number;
    published_low_rate: number;
    published_high_rate: number;
    estimated_member_cost: number;
    estimated_annual_total: number;
    deductible_remaining: number;
    coinsurance_rate: number;
    network_status: "pending_verification";
    estimate_status: "scenario_not_guarantee";
    source_page_url: string | null;
    rate_published_at: string | null;
  }[];
  alternative_plan: {
    plan_id: string;
    plan_name: string;
    hospital_id: number;
    hospital: string;
    estimated_member_cost: number;
    estimated_annual_total: number;
    estimated_annual_savings: number;
    requires_plan_switch: true;
    action_status: "exploration_only";
  } | null;
  selected_care_path: {
    plan_id: string;
    plan_name: string;
    coverage_status: "current";
    hospital_id: number;
    hospital: string;
    procedure_code: string;
    published_typical_rate: number;
    estimated_member_cost: number;
    network_status: "pending_verification" | "sandbox_verified";
    selected_at: string;
    booking_consent: boolean;
  } | null;
  booking_preferences: {
    date_from: string;
    date_to: string;
    time_of_day: "morning" | "afternoon" | "any";
    source: string;
    confidence: number;
  } | null;
  booking_slots: {
    slot_id: string;
    hospital_id: number;
    hospital: string;
    procedure_code: string;
    starts_at: string;
    duration_minutes: number;
    status: string;
    source: string;
    retry_demo: boolean;
    consent_scope: string;
  }[];
  selected_booking_slot: {
    slot_id: string;
    hospital_id: number;
    hospital: string;
    procedure_code: string;
    starts_at: string;
    duration_minutes: number;
    status: string;
    source: string;
    retry_demo: boolean;
    consent_scope: string;
  } | null;
  booking_consent_scope: string | null;
  cancellation_consent_scope?: string | null;
  reschedule_original_slot?: CareJourneySnapshot["selected_booking_slot"];
  reschedule_pending?: boolean;
  booking_tasks: {
    task_id: string;
    slot_id: string;
    status: "scheduled" | "completed" | "needs_user_action";
    attempts: number;
    next_attempt_at: string;
    last_error: string;
    created_at: string;
    completed_at: string | null;
  }[];
  notifications: {
    notification_id: string;
    kind: string;
    message: string;
    created_at: string;
    read: boolean;
  }[];
  receipts: {
    action: string;
    status: string;
    sandbox: boolean;
    scope: string;
    idempotency_key: string;
    recorded_at: string;
  }[];
  events: {
    sequence: number;
    type: string;
    actor: string;
    payload: Record<string, unknown>;
    recorded_at: string;
  }[];
  facts?: {
    name: string;
    value: unknown;
    source: string;
    observed_at: string;
    confidence: number;
    verification_status: string;
    consent_requirement: string | null;
  }[];
}

export interface CareContextJourney {
  journey_id: string;
  title: string;
  stage: string;
  status: "active" | "complete" | string;
  selected_care_path: CareJourneySnapshot["selected_care_path"];
  pending_fields: string[];
  pending_questions: string[];
  intake_facts: Record<string, { value: unknown; source: string; verification_status: string }>;
  updated_at: string;
}

export interface CareContextAppointment {
  appointment_id: string;
  journey_id: string;
  slot_id: string;
  hospital_id: number | null;
  code: string | null;
  description: string | null;
  booked_for: string | null;
  status: string;
  source: string;
  updated_at: string;
}

export interface CareContext {
  user: { user_id: string };
  current_plan: { plan_id: number; label: string | null; payer_name: string | null; is_active: boolean } | null;
  journeys: CareContextJourney[];
  appointments: CareContextAppointment[];
  scheduled_tasks: CareJourneySnapshot["booking_tasks"];
}

export interface CareAgentPlan {
  intent: string;
  correlation_id: string;
  utterance_id: string;
  target_journey_id: string | null;
  target_appointment_id: string | null;
  steps: string[];
  reuse: string[];
  refresh: string[];
  missing: string[];
  source: string;
  confidence: number;
}

export interface CareAgentResponse {
  reply: string;
  plan: CareAgentPlan;
  journey: CareJourneySnapshot | null;
  context: CareContext;
}

export interface AgentSessionTurn {
  utterance_id: string;
  correlation_id: string;
  journey_id: string | null;
  intent: string;
  message: string;
  channel: "chat" | "voice";
  status: "completed" | "failed";
  error: string | null;
  created_at: string;
  completed_at: string | null;
  plan: CareAgentPlan | { validation_error: string };
}

export interface AgentSession {
  correlation_id: string;
  channel: "chat" | "voice";
  status: "completed" | "failed";
  started_at: string;
  updated_at: string;
  turns: AgentSessionTurn[];
}

/** A question that has already been asked, offered again on the home screen. */
export interface RecentLookup {
  query: string;
  code: string;
  description: string | null;
  low: number | null;
  high: number | null;
  asked_at: string;
}

/** Shape returned by /api/plan/summary and by the voice `plan` ui event. */
export interface PlanSnapshotResponse {
  configured: boolean;
  [key: string]: unknown;
}

/** Words that mean "tell me about my coverage" rather than "price this".
 *
 * Deterministic on purpose: a keyword check that occasionally routes to the
 * price path is recoverable, whereas asking the model to classify every typed
 * question adds a round trip and a new way to be wrong. */
const PLAN_INTENT =
  /\b(my|our)\s+(plan|coverage|insurance|deductible|benefits)\b|\bdeductible\b|\bout[- ]of[- ]pocket\b|\bcoinsurance\b|\bwhat (do|does) (i|my plan) (pay|cover|charge)\b|\b(am i|do i have) covered\b|\bcovered\b/i;

/** Map a typed question onto a plan cost-sharing category, when it names one. */
const CATEGORY_HINTS: [RegExp, string][] = [
  [/\bmri\b|\bct\b|\bcat scan\b|\bpet scan\b|\bimaging\b/i, "advanced_imaging"],
  [/\bspecialist\b/i, "specialist"],
  [/\bprimary care\b|\bpcp\b|\bdoctor.s? visit\b|\boffice visit\b/i, "pcp"],
  [/\burgent care\b/i, "urgent_care"],
  [/\bemergency\b|\ber\b/i, "emergency_room"],
  [/\bgeneric\b/i, "rx_generic"],
  [/\bbrand\b/i, "rx_preferred_brand"],
  [/\blab\b|\bblood work\b/i, "lab"],
  [/\bx.?ray\b/i, "xray"],
  [/\bphysical therapy\b|\bpt\b/i, "physical_therapy"],
  [/\bchiropract/i, "chiropractic"],
  [/\bmental health\b|\btherapy\b|\btherapist\b/i, "mental_health_outpatient"],
];

export function isPlanQuestion(text: string): boolean {
  return PLAN_INTENT.test(text);
}

export function categoryFor(text: string): string | undefined {
  return CATEGORY_HINTS.find(([re]) => re.test(text))?.[1];
}

export interface QhpPlan {
  plan_id: string;
  state: string;
  issuer_name: string;
  marketing_name: string;
  metal_level: string;
  plan_type: string;
  hsa_eligible: number;
  deductible: number;
  oop_max: number;
}

export interface PlanBenefit {
  category: string;
  kind: "copay" | "coinsurance" | "no_charge" | "not_covered";
  amount: number;
  after_deductible: number;
  covered: number;
}

/** Human labels for the CMS benefit categories. */
export const CATEGORY_LABELS: Record<string, string> = {
  pcp: "Primary care visit",
  specialist: "Specialist visit",
  urgent_care: "Urgent care",
  emergency_room: "Emergency room",
  ambulance: "Ambulance",
  advanced_imaging: "MRI / CT / PET scan",
  xray: "X-ray",
  lab: "Lab work",
  outpatient_facility: "Outpatient facility",
  outpatient_surgery: "Outpatient surgery",
  inpatient_facility: "Hospital stay",
  inpatient_physician: "Inpatient surgeon",
  rx_generic: "Generic drugs",
  rx_preferred_brand: "Preferred brand drugs",
  rx_nonpreferred_brand: "Non-preferred brand drugs",
  rx_specialty: "Specialty drugs",
  physical_therapy: "Physical therapy",
  chiropractic: "Chiropractic",
  prenatal: "Prenatal care",
  delivery: "Delivery",
  mental_health_outpatient: "Mental health (outpatient)",
  substance_use_outpatient: "Substance use (outpatient)",
};

/** "25% after deductible", "$30", "Covered in full", "Not covered". */
export function describeBenefit(b: PlanBenefit): string {
  if (b.kind === "not_covered") return "Not covered";
  if (b.kind === "no_charge") return b.after_deductible ? "Free after deductible" : "Covered in full";
  const base =
    b.kind === "copay"
      ? `$${b.amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`
      : `${Math.round(b.amount * 100)}%`;
  return b.after_deductible ? `${base} after deductible` : base;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (r.status === 401) {
    setToken(null);
    throw new NotSignedIn();
  }
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}${detail ? ` — ${detail}` : ""}`);
  }
  return r.json() as Promise<T>;
}

/** The server sends `detail` as a sentence meant to be read. */
async function readDetail(r: Response): Promise<string> {
  try {
    const body = await r.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    /* fall through */
  }
  return `Something went wrong (${r.status}).`;
}

async function authRequest(path: string, email: string, password: string): Promise<string> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error(await readDetail(r));
  const { token: next } = (await r.json()) as { token: string };
  setToken(next);
  return next;
}

export const api = {
  health: () => req<{ ok: boolean; rates: number; hospitals: number }>("/api/health"),

  signup: (email: string, password: string) => authRequest("/api/auth/signup", email, password),
  login: (email: string, password: string) => authRequest("/api/auth/login", email, password),
  me: () => req<{ id: number; email: string; created_at: string }>("/api/auth/me"),
  logout: async () => {
    // Revoke server-side first, but drop the local token either way — a failed
    // network call must not leave someone still signed in on a shared phone.
    await req("/api/auth/logout", { method: "POST" }).catch(() => {});
    setToken(null);
  },

  price: (q: string, code?: string) =>
    req<PriceResponse>(
      `/api/price?q=${encodeURIComponent(q)}${code ? `&code=${encodeURIComponent(code)}` : ""}`,
    ),

  agentChat: (question: string, evidence: unknown) =>
    req<{ reply: string }>("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify({ question, evidence }),
    }),

  careContext: () => req<CareContext>("/api/care-context"),

  careAgentMessage: (text: string, activeJourneyId?: string | null, replyToPending = false) =>
    req<CareAgentResponse>("/api/care-agent/messages", {
      method: "POST",
      body: JSON.stringify({
        text,
        active_journey_id: activeJourneyId ?? null,
        reply_to_pending: replyToPending,
      }),
    }),

  startJourney: (body?: { procedure?: string; provider?: string; facility?: string; empty?: boolean }) =>
    req<CareJourneySnapshot>("/api/journeys", {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),

  journey: (journeyId: string) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}`),

  adminJourneys: () => req<{ journeys: CareJourneySnapshot[] }>("/api/admin/journeys"),
  adminAgentSessions: () => req<{ sessions: AgentSession[] }>("/api/admin/agent-sessions"),
  clearDemoData: () => req<{ cleared: Record<string, number> }>("/api/admin/demo-data", { method: "DELETE" }),

  journeyOnboard: (journeyId: string, text: string, source = "user_request") =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/onboard`, {
      method: "POST",
      body: JSON.stringify({ text, source }),
    }),

  journeyConsent: (journeyId: string, body: { action: string; scope: string; approved: boolean }) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/consents`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  journeyCompare: (journeyId: string) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/compare`, { method: "POST" }),

  journeySelectCurrentPath: (journeyId: string, hospitalId: number) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/selection`, {
      method: "POST",
      body: JSON.stringify({ hospital_id: hospitalId }),
    }),

  journeyBookingPreferences: (journeyId: string, text: string) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/booking/preferences`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  journeySelectBookingSlot: (journeyId: string, slotId: string) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/booking/slots/${encodeURIComponent(slotId)}/select`, {
      method: "POST",
    }),

  journeyReschedule: (journeyId: string, body: { booking_scope: string; cancellation_scope: string; idempotency_key: string }) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/reschedule`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  journeyMatchingReason: (journeyId: string, question?: string) =>
    req<{ reason: string; journey: CareJourneySnapshot }>(`/api/journeys/${encodeURIComponent(journeyId)}/matching-reason`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  journeyAdvance: (journeyId: string) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/advance`, { method: "POST" }),

  journeyAction: (journeyId: string, body: { action: string; scope: string; idempotency_key: string; new_effective_date?: string; first_premium_confirmed?: boolean }) =>
    req<CareJourneySnapshot>(`/api/journeys/${encodeURIComponent(journeyId)}/actions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  providers: (code: string) =>
    req<{ code: string; providers: HospitalPrice[] }>(
      `/api/providers?code=${encodeURIComponent(code)}`,
    ),

  parseSbc: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const r = await fetch(`${BASE}/api/sbc/parse`, { method: "POST", body: form });
    if (!r.ok) throw new Error((await r.text().catch(() => "")) || `${r.status}`);
    return r.json() as Promise<SbcResult>;
  },

  scanCard: async (file: File, extractedText?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (extractedText) form.append("extracted_text", extractedText);
    const r = await fetch(`${BASE}/api/insurance/scan`, {
      method: "POST",
      headers: token ? { authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!r.ok) throw new Error(await readDetail(r));
    return r.json() as Promise<CardScan>;
  },

  prepareReportIntake: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const r = await fetch(`${BASE}/api/report-intake/prepare`, {
      method: "POST",
      headers: token ? { authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!r.ok) throw new Error(await readDetail(r));
    return r.json() as Promise<PreparedReportDocument>;
  },

  analyzeReportIntake: async (
    file: File,
    consentScope: string,
    journeyId?: string,
    extractedText?: string,
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("consent_scope", consentScope);
    form.append("consent_approved", "true");
    if (journeyId) form.append("journey_id", journeyId);
    if (extractedText) form.append("extracted_text", extractedText);
    const r = await fetch(`${BASE}/api/report-intake/analyze`, {
      method: "POST",
      headers: token ? { authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!r.ok) throw new Error(await readDetail(r));
    return r.json() as Promise<ReportAnalysis>;
  },

  confirmReportOrders: (
    analysisId: string,
    orderIds: string[],
    journeyId?: string | null,
  ) =>
    req<ConfirmedReportIntake>(
      `/api/report-intake/${encodeURIComponent(analysisId)}/confirm`,
      {
        method: "POST",
        body: JSON.stringify({
          order_ids: orderIds,
          journey_id: journeyId || null,
        }),
      },
    ),

  applySbc: (body: SbcApply) =>
    req<{ id: number; benefits_saved: number }>("/api/sbc/apply", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  planSummary: (category?: string) =>
    req<PlanSnapshotResponse>(
      `/api/plan/summary${category ? `?category=${encodeURIComponent(category)}` : ""}`,
    ),

  hospitals: () => req<Hospital[]>("/api/hospitals"),

  myPlans: () => req<{ plans: MyPlan[] }>("/api/plans/mine"),

  comparePlans: (q: string) =>
    req<PlanComparison>(`/api/plans/compare?q=${encodeURIComponent(q)}`),

  activatePlan: (planId: number) =>
    req<{ ok: boolean }>(`/api/plans/${planId}/activate`, { method: "POST" }),

  removePlan: (planId: number) =>
    req<{ ok: boolean }>(`/api/plans/${planId}`, { method: "DELETE" }),

  checkBill: (body: {
    query: string;
    amount: number;
    amount_kind: AmountKind;
    hospital_id?: number | null;
  }) => req<BillCheck>("/api/bill/check", { method: "POST", body: JSON.stringify(body) }),

  appointments: () => req<{ appointments: Appointment[] }>("/api/appointments"),

  addAppointment: (body: {
    hospital_id?: number | null;
    code?: string | null;
    description?: string | null;
    booked_for?: string | null;
    estimated_cost?: number | null;
    note?: string | null;
  }) => req<{ id: number }>("/api/appointments", { method: "POST", body: JSON.stringify(body) }),

  removeAppointment: (id: number) =>
    req<{ ok: boolean }>(`/api/appointments/${id}`, { method: "DELETE" }),

  history: (limit = 5) => req<{ recent: RecentLookup[] }>(`/api/history?limit=${limit}`),

  updatePlanUsage: (body: { deductible_met?: number; oop_met?: number }) =>
    req<{ deductible_met: number; oop_met: number }>("/api/plan/usage", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deletePlan: () => req<{ ok: boolean }>("/api/plan", { method: "DELETE" }),

  planStates: () => req<{ state: string; plans: number }[]>("/api/plans/states"),

  searchPlans: (state: string, q?: string, metal?: string) =>
    req<{ state: string; count: number; plans: QhpPlan[] }>(
      `/api/plans/search?state=${encodeURIComponent(state)}` +
        (q ? `&q=${encodeURIComponent(q)}` : "") +
        (metal ? `&metal=${encodeURIComponent(metal)}` : ""),
    ),

  planBenefits: (planId: string) =>
    req<{ plan: QhpPlan; benefits: PlanBenefit[] }>(
      `/api/plans/${encodeURIComponent(planId)}/benefits`,
    ),

  getPlan: () => req<(PlanBody & { id: number }) | null>("/api/plan"),

  putPlan: (body: PlanBody) =>
    req<PlanBody & { id: number }>("/api/plan", { method: "PUT", body: JSON.stringify(body) }),

  memberMemory: () => req<MemberMemory>("/api/me/memory"),

  messagingPreference: () => req<MessagingPreference>("/api/me/messaging"),

  setMessagingPreference: (enabled: boolean, destinationLabel = "discord:eevee") =>
    req<MessagingPreference>("/api/me/messaging", {
      method: "PUT",
      body: JSON.stringify({ enabled, destination_label: destinationLabel }),
    }),

  notificationPreview: (resultRef: string) =>
    req<NotificationPreview>("/api/results/notify/preview", {
      method: "POST",
      body: JSON.stringify({ result_ref: resultRef }),
    }),

  sendNotification: (resultRef: string, consentScope: string) =>
    req<NotificationReceipt>("/api/results/notify", {
      method: "POST",
      body: JSON.stringify({ result_ref: resultRef, consent_scope: consentScope, consent_approved: true }),
    }),


};

export type MemberMemory = {
  user_id: string;
  current_facts: Array<{ id: number; name: string; value: unknown; source: string; confidence: number; verification_status: string }>;
  active_plan: null | { label?: string | null; payer_name?: string | null };
  agent_events: Array<{ id: number; agent_role: string; event_type: string; created_at: string }>;
};

export type MessagingPreference = {
  channel: "discord";
  destination_label: string;
  enabled: boolean;
  webhook_configured: boolean;
  consent_scope?: string | null;
};

export type NotificationPreview = {
  channel: "discord";
  destination_label: string;
  result_ref: string;
  body: string;
  consent_scope: string;
};

export type NotificationReceipt = {
  ok: boolean;
  channel: "discord";
  confirmation_reference: string;
  destination_redacted: string;
  sandbox: boolean;
};

/** Format a publish date that came verbatim out of an MRF.
 *
 * Hospitals write this field however they like — most emit `2026-04-01`, but 13
 * of the 57 emit `6/5/2026`. Showing both side by side in one list reads like a
 * data error. Parsed by hand rather than with `new Date(s)`, because
 * `new Date("2026-04-01")` is UTC midnight and renders as March 31 in any US
 * timezone. Anything unrecognised is passed through untouched — a date we can't
 * parse is still a date the hospital published. */
export function publishedOn(raw: string): string {
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(raw);
  const us = /^(\d{1,2})\/(\d{1,2})\/(\d{4})/.exec(raw);
  const [y, m, d] = iso
    ? [+iso[1], +iso[2], +iso[3]]
    : us
      ? [+us[3], +us[1], +us[2]]
      : [0, 0, 0];
  if (!y || m < 1 || m > 12 || d < 1 || d > 31) return raw;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Split the pipe-joined address list some systems publish for multi-campus
 *  hospitals. All seven in the current data are genuinely distinct sites. */
export function campuses(address: string | null): string[] {
  return (address ?? "")
    .split("|")
    .map((s) => s.trim())
    .filter(Boolean);
}

export const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const moneyExact = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
