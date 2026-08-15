import { useEffect, useState } from "react";
import { api, type CareJourneySnapshot } from "@/lib/api";

const money = (value: number) => value.toLocaleString("en-US", {
  style: "currency",
  currency: "USD",
});

export function Journey({ onBack }: { onBack: () => void }) {
  const [snapshot, setSnapshot] = useState<CareJourneySnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [matchingReason, setMatchingReason] = useState<string | null>(null);
  const [bookingText, setBookingText] = useState("2026-08-30 to 2026-09-15, any time");

  useEffect(() => {
    if (!snapshot?.booking_tasks.some((task) => task.status === "scheduled")) return;
    const timer = window.setInterval(() => {
      void api.journey(snapshot.journey_id).then(setSnapshot).catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [snapshot]);

  async function run(work: () => Promise<CareJourneySnapshot>) {
    setBusy(true);
    setError(null);
    try {
      setSnapshot(await work());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    const started = await api.startJourney();
    const onboarded = await api.journeyOnboard(
      started.journey_id,
      "MRI knee without contrast. Care date August 30, 2026. Coverage ends September 30, 2026.",
      "seeded_journey",
    );
    return api.journeyConsent(onboarded.journey_id, {
      action: "process_documents",
      scope: "synthetic request and documents",
      approved: true,
    });
  }

  async function compare() {
    if (!snapshot) throw new Error("Start a journey first.");
    return api.journeyCompare(snapshot.journey_id);
  }

  async function selectHospital(hospitalId: number) {
    if (!snapshot) throw new Error("Start a journey first.");
    return api.journeySelectCurrentPath(snapshot.journey_id, hospitalId);
  }

  async function explainMatch() {
    if (!snapshot) throw new Error("Start a journey first.");
    const result = await api.journeyMatchingReason(
      snapshot.journey_id,
      "Explain the current-plan hospital options and separate alternative coverage scenario without treating estimates as guarantees.",
    );
    setMatchingReason(result.reason);
    return result.journey;
  }

  async function verify() {
    if (!snapshot?.selected_care_path) throw new Error("Choose a hospital first.");
    const selected = snapshot.selected_care_path;
    const scope = `Dr. Lee / ${selected.hospital} / ${selected.plan_name}`;
    await api.journeyConsent(snapshot.journey_id, {
      action: "share_with_provider",
      scope,
      approved: true,
    });
    return api.journeyAction(snapshot.journey_id, {
      action: "share_with_provider",
      scope,
      idempotency_key: `verify-${snapshot.journey_id}`,
    });
  }

  async function book() {
    if (!snapshot?.selected_booking_slot || !snapshot.booking_consent_scope) {
      throw new Error("Choose an appointment slot first.");
    }
    const scope = snapshot.booking_consent_scope;
    await api.journeyConsent(snapshot.journey_id, {
      action: "book_appointment",
      scope,
      approved: true,
    });
    return api.journeyAction(snapshot.journey_id, {
      action: "book_appointment",
      scope,
      idempotency_key: `book-${snapshot.journey_id}-${snapshot.selected_booking_slot.slot_id}`,
    });
  }

  async function findBookingSlots() {
    if (!snapshot) throw new Error("Start a journey first.");
    return api.journeyBookingPreferences(snapshot.journey_id, bookingText);
  }

  async function selectBookingSlot(slotId: string) {
    if (!snapshot) throw new Error("Start a journey first.");
    return api.journeySelectBookingSlot(snapshot.journey_id, slotId);
  }

  return (
    <main className="mx-auto min-h-dvh w-full max-w-2xl bg-background px-5 pb-24 pt-8">
      <button onClick={onBack} className="text-sm text-muted-foreground">← Back</button>
      <p className="mt-8 text-xs font-medium uppercase tracking-[0.18em] text-primary">Care journey</p>
      <h1 className="mt-2 font-display text-3xl font-semibold text-foreground">Choose a complete care path</h1>
      <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
        Start with hospitals under your current coverage. Alternative coverage stays separate and never changes your plan without a dedicated flow.
      </p>

      {!snapshot ? (
        <button disabled={busy} onClick={() => void run(start)} className="mt-8 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">
          Start seeded MRI request
        </button>
      ) : (
        <>
          <div className="mt-6 flex items-center justify-between rounded-xl border border-border bg-card p-4 text-sm">
            <span><span className="text-muted-foreground">Current plan: </span><b>{snapshot.current_plan_name}</b></span>
            <span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium">{snapshot.stage}</span>
          </div>

          {snapshot.stage === "compare" && (
            <button disabled={busy} onClick={() => void run(compare)} className="mt-4 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">
              Build current-plan hospital options
            </button>
          )}

          {snapshot.selected_care_path && (
            <section className="mt-5 rounded-2xl border border-primary/40 bg-primary/5 p-5">
              <p className="text-xs font-medium uppercase tracking-[0.14em] text-primary">Selected care path</p>
              <h2 className="mt-2 font-display text-xl font-semibold">{snapshot.selected_care_path.hospital}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{snapshot.selected_care_path.plan_name} · scenario member cost {money(snapshot.selected_care_path.estimated_member_cost)}</p>
              <p className="mt-3 text-xs text-muted-foreground">{snapshot.selected_care_path.network_status === "sandbox_verified" ? "Network sandbox-verified." : "Network verification pending."} {snapshot.selected_care_path.booking_consent ? "Booking consent recorded." : "No appointment has been booked."}</p>
            </section>
          )}

          {!snapshot.selected_care_path && snapshot.current_plan_options.length > 0 && (
            <section className="mt-6 space-y-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.14em] text-primary">Stay with current coverage</p>
                <h2 className="mt-1 font-display text-2xl font-semibold">Hospital options under {snapshot.current_plan_name}</h2>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Estimates apply seeded benefit terms to hospital-published rates. Network status is verified after you choose.</p>
              </div>
              {snapshot.current_plan_options.slice(0, 3).map((option, index) => (
                <article key={option.hospital_id} className={`rounded-2xl border p-5 ${index === 0 ? "border-primary/50 bg-primary/5" : "border-border bg-card"}`}>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-primary">{index === 0 ? "Lowest current-plan scenario" : "Current-plan option"}</p>
                      <h3 className="mt-1 font-display text-lg font-semibold">{option.hospital}</h3>
                    </div>
                    <strong className="text-lg">{money(option.estimated_member_cost)}</strong>
                  </div>
                  <p className="mt-3 text-xs leading-relaxed text-muted-foreground">Hospital published {money(option.published_typical_rate)} typical · annual scenario {money(option.estimated_annual_total)} · network pending</p>
                  <button disabled={busy} onClick={() => void run(() => selectHospital(option.hospital_id))} className="mt-4 w-full rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground">Choose {option.hospital}</button>
                </article>
              ))}
            </section>
          )}

          {snapshot.alternative_plan && !snapshot.selected_care_path && (
            <section className="mt-7 rounded-2xl border border-amber-300/60 bg-amber-50/50 p-5 text-foreground">
              <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-amber-700">Optional alternative coverage</p>
              <div className="mt-2 flex items-start justify-between gap-4"><h2 className="font-display text-xl font-semibold">{snapshot.alternative_plan.plan_name}</h2><strong>{money(snapshot.alternative_plan.estimated_annual_total)} / year</strong></div>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Potential annual savings {money(snapshot.alternative_plan.estimated_annual_savings)}. This requires a separate eligibility and plan-switch flow that is not included in this demo.</p>
              <button type="button" onClick={() => setError("Plan-switch exploration is a separate flow and is not implemented in this demo. Your current coverage is unchanged.")} className="mt-4 w-full rounded-xl border border-amber-400 bg-transparent px-4 py-2.5 text-sm font-medium text-amber-800">Explore plan switch</button>
            </section>
          )}

          {snapshot.stage === "recommend" && snapshot.evaluations.length > 0 && (
            <button disabled={busy} onClick={() => void run(explainMatch)} className="mt-5 w-full rounded-xl border border-border px-4 py-3 text-sm text-foreground">Ask Nemotron to explain the scenarios</button>
          )}
          {matchingReason && <div className="mt-3 rounded-xl border border-primary/30 bg-primary/5 p-4 text-sm leading-relaxed"><span className="mb-1 block text-xs font-medium uppercase tracking-wider text-primary">Matching Agent reasoning</span>{matchingReason}</div>}

          {snapshot.stage === "verify" && <button disabled={busy} onClick={() => void run(verify)} className="mt-5 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">Approve sandbox network and provider verification</button>}
          {snapshot.stage === "book" && (
            <section className="mt-6 rounded-2xl border border-border bg-card p-5">
              <p className="text-xs font-medium uppercase tracking-[0.14em] text-primary">Booking Agent</p>
              <h2 className="mt-1 font-display text-xl font-semibold">Find a synthetic appointment</h2>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">The agent extracts your date and time preferences. Deterministic code searches slots and enforces consent for the exact appointment.</p>
              <div className="mt-4 flex gap-2">
                <input value={bookingText} onChange={(event) => setBookingText(event.target.value)} className="min-w-0 flex-1 rounded-xl border border-border bg-background px-3 py-2 text-sm" aria-label="Booking preferences" />
                <button disabled={busy} onClick={() => void run(findBookingSlots)} className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">Find slots</button>
              </div>
              {snapshot.booking_slots.length > 0 && (
                <div className="mt-4 space-y-2">
                  {snapshot.booking_slots.map((slot) => (
                    <button key={slot.slot_id} disabled={busy || slot.status !== "available"} onClick={() => void run(() => selectBookingSlot(slot.slot_id))} className={`w-full rounded-xl border p-3 text-left text-sm ${snapshot.selected_booking_slot?.slot_id === slot.slot_id ? "border-primary bg-primary/5" : "border-border"}`}>
                      <b>{new Date(slot.starts_at).toLocaleString()}</b>
                      <span className="mt-1 block text-xs text-muted-foreground">{slot.hospital} · {slot.duration_minutes} minutes{slot.retry_demo ? " · retry demonstration" : ""}</span>
                    </button>
                  ))}
                </div>
              )}
              {snapshot.selected_booking_slot && snapshot.booking_consent_scope && (
                <div className="mt-4 rounded-xl border border-primary/30 bg-primary/5 p-4">
                  <p className="text-xs leading-relaxed text-muted-foreground">Exact approval scope: {snapshot.booking_consent_scope}</p>
                  <button disabled={busy || snapshot.booking_tasks.some((task) => task.status === "scheduled")} onClick={() => void run(book)} className="mt-3 w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground">Approve this sandbox appointment</button>
                </div>
              )}
              {snapshot.booking_tasks.map((task) => <p key={task.task_id} className="mt-3 rounded-xl bg-secondary p-3 text-xs">Booking task: <b>{task.status}</b> · {task.attempts} attempt(s){task.status === "scheduled" ? ". Refresh shortly to see the retry result." : ""}</p>)}
              {snapshot.notifications.slice(-2).map((notification) => <p key={notification.notification_id} className="mt-2 text-xs leading-relaxed text-muted-foreground">{notification.message}</p>)}
            </section>
          )}
          {snapshot.stage === "complete" && <p className="mt-6 rounded-xl border border-primary/40 bg-primary/5 p-4 text-sm">Journey complete. The selection and permissioned actions are in the audit history.</p>}
        </>
      )}
      {error && <p className="mt-4 rounded-xl bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}
    </main>
  );
}
