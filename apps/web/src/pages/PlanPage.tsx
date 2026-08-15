import { Check, FileText, LogOut, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { PlanCard, type PlanSnapshot } from "@/components/PlanCard";
import { api } from "@/lib/api";

/** View and correct the stored plan.
 *
 * Until this existed, a plan could be set once and never changed — onboarding
 * was unreachable the moment a plan existed, so the only way to record a bill
 * you'd paid was a SQL statement. The home screen puts deductible progress front
 * and centre, which makes a stale figure both very visible and, previously,
 * unfixable. */
export function PlanPage({
  dataVersion,
  hospitalCount,
  onChanged,
  onOpenCoverage,
  onReplacePlan,
  onSignOut,
}: {
  /** Refetch when the plan changed elsewhere — this screen stays mounted. */
  dataVersion: number;
  hospitalCount: number;
  /** Tell the shell the plan moved, so Home's ring follows. */
  onChanged: () => void;
  onOpenCoverage: () => void;
  onReplacePlan: () => void;
  onSignOut: () => void;
}) {
  const [email, setEmail] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<PlanSnapshot | null>(null);
  const [deductibleMet, setDeductibleMet] = useState("");
  const [oopMet, setOopMet] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const s = (await api.planSummary()) as PlanSnapshot;
    setSnapshot(s);
    setDeductibleMet(String(s.deductible_met ?? 0));
    setOopMet(String(s.oop_met ?? 0));
  }

  useEffect(() => {
    void refresh().catch((e) => setError(String(e)));
    void api
      .me()
      .then((u) => setEmail(u.email))
      .catch(() => setEmail(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataVersion]);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.updatePlanUsage({
        deductible_met: parseFloat(deductibleMet) || 0,
        oop_met: parseFloat(oopMet) || 0,
      });
      await refresh();
      onChanged();
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="abyss-plan mx-auto w-full max-w-md pb-[calc(6rem+env(safe-area-inset-bottom))]">
      <header className="abyss-plan__hero">
        <div className="abyss-home__brand"><span>S</span><b>ABYSS</b></div>
        <div className="abyss-plan__copy"><p>YOUR COVERAGE</p><h1>My Plan</h1><span>Your benefits guide for every dive.</span></div>
        <img src="/mascot/approved/abyss-present.png" alt="ABYSS presenting your health plan" />
      </header>
      <div className="abyss-plan__body">
      <p className="abyss-plan__intro">
        Keeping these two figures current is what makes every estimate accurate. Your insurer's
        member portal calls them "deductible applied" and "out-of-pocket year-to-date".
      </p>

      <div className="abyss-plan__inputs">
        {[
          { label: "Deductible met", value: deductibleMet, set: setDeductibleMet },
          { label: "Paid out of pocket", value: oopMet, set: setOopMet },
        ].map((f) => (
          <label key={f.label}>
            <span>{f.label}</span>
            <span className="abyss-plan__input">
              <span className="text-muted-foreground">$</span>
              <input
                type="number"
                inputMode="decimal"
                value={f.value}
                onChange={(e) => {
                  f.set(e.target.value);
                  setSaved(false);
                }}
                aria-label={f.label}
                className="w-full bg-transparent font-display text-lg text-foreground outline-none"
              />
            </span>
          </label>
        ))}
      </div>

      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

      <button
        onClick={save}
        disabled={saving}
        className="abyss-plan__save"
      >
        {saved ? (
          <>
            <Check className="h-4 w-4" aria-hidden /> Saved
          </>
        ) : saving ? (
          "Saving…"
        ) : (
          "Update"
        )}
      </button>

      {snapshot && (
        <div className="abyss-plan__card">
          <PlanCard plan={snapshot} />
        </div>
      )}

      <button
        onClick={onOpenCoverage}
        className="abyss-plan__action"
      >
        <FileText className="h-5 w-5 shrink-0 text-primary" aria-hidden />
        <span>
          <span className="block text-sm font-medium text-foreground">What ABYSS covers</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            {hospitalCount ? `${hospitalCount} hospitals` : "Every hospital"}, and when each
            published its prices
          </span>
        </span>
      </button>

      <button
        onClick={onReplacePlan}
        className="abyss-plan__action abyss-plan__action--center"
      >
        <RefreshCw className="h-4 w-4" aria-hidden />
        Change my plan
      </button>
      <p className="mt-2 text-center text-xs leading-relaxed text-muted-foreground">
        Starts over — pick a marketplace plan, upload a new document, or enter benefits by hand.
      </p>

      <div className="mt-8 border-t border-border pt-5">
        {email && <p className="text-xs text-muted-foreground">Signed in as {email}</p>}
        <button
          onClick={onSignOut}
          className="mt-2 flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <LogOut className="h-4 w-4" aria-hidden />
          Sign out
        </button>
      </div>
      </div>
    </main>
  );
}
