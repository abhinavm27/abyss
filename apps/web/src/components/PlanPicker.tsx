import { ArrowLeft, Check, Loader2, Search } from "lucide-react";
import { useEffect, useState } from "react";
import {
  api,
  CATEGORY_LABELS,
  describeBenefit,
  money,
  type PlanBenefit,
  type QhpPlan,
} from "@/lib/api";

/** Find and confirm a real marketplace plan.
 *
 * Linking a plan is what lets ABYSS use the plan's actual per-service rules —
 * a $30 primary-care copay and 25%-after-deductible for an MRI are different
 * numbers, and a single blended rate gets both wrong. */
export function PlanPicker({
  onSelect,
  onBack,
}: {
  onSelect: (plan: QhpPlan) => void;
  onBack: () => void;
}) {
  const [states, setStates] = useState<{ state: string; plans: number }[]>([]);
  const [state, setState] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [plans, setPlans] = useState<QhpPlan[]>([]);
  const [chosen, setChosen] = useState<QhpPlan | null>(null);
  const [benefits, setBenefits] = useState<PlanBenefit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.planStates().then(setStates).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!state) return;
    setLoading(true);
    api
      .searchPlans(state, query || undefined)
      .then((r) => setPlans(r.plans))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [state, query]);

  async function preview(plan: QhpPlan) {
    setChosen(plan);
    setBenefits(null);
    try {
      setBenefits((await api.planBenefits(plan.plan_id)).benefits);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  // --- confirmation: show what the plan actually charges -------------------
  if (chosen) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-border bg-card p-6 shadow-sm">
        <button
          onClick={() => {
            setChosen(null);
            setBenefits(null);
          }}
          className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back to plans
        </button>

        <h1 className="font-display text-xl font-semibold leading-snug text-foreground">
          {chosen.marketing_name}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {chosen.issuer_name} · {chosen.metal_level} · {chosen.plan_type}
          {chosen.hsa_eligible ? " · HSA eligible" : ""}
        </p>

        <div className="mt-4 flex gap-4">
          <div className="flex-1 rounded-[var(--radius-sm)] bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">Deductible</p>
            <p className="font-display text-lg font-semibold text-foreground">
              {money(chosen.deductible)}
            </p>
          </div>
          <div className="flex-1 rounded-[var(--radius-sm)] bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">Out-of-pocket max</p>
            <p className="font-display text-lg font-semibold text-foreground">
              {money(chosen.oop_max)}
            </p>
          </div>
        </div>

        <p className="mt-5 text-sm font-medium text-foreground">What this plan charges you</p>
        {!benefits && (
          <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading cost sharing…
          </div>
        )}
        {benefits && (
          <ul className="mt-2 max-h-64 space-y-1.5 overflow-y-auto pr-1">
            {benefits
              .filter((b) => CATEGORY_LABELS[b.category])
              .map((b) => (
                <li key={b.category} className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">{CATEGORY_LABELS[b.category]}</span>
                  <span
                    className={`shrink-0 text-right font-medium ${
                      b.kind === "not_covered" ? "text-destructive" : "text-foreground"
                    }`}
                  >
                    {describeBenefit(b)}
                  </span>
                </li>
              ))}
          </ul>
        )}

        <button
          onClick={() => onSelect(chosen)}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] bg-primary px-4 py-3 font-medium text-primary-foreground"
        >
          <Check className="h-4 w-4" aria-hidden /> This is my plan
        </button>
      </div>
    );
  }

  // --- state selection -----------------------------------------------------
  if (!state) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-border bg-card p-6 shadow-sm">
        <button
          onClick={onBack}
          className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back
        </button>
        <h1 className="font-display text-2xl font-semibold leading-snug text-foreground">
          Which state is your plan in?
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          These are the states that publish plan data federally.
        </p>

        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

        <div className="mt-5 grid grid-cols-4 gap-2">
          {states.map((s) => (
            <button
              key={s.state}
              onClick={() => setState(s.state)}
              className="rounded-[var(--radius-sm)] border border-border bg-background py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
            >
              {s.state}
            </button>
          ))}
        </div>

        <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
          Don't see your state? States like Massachusetts, Rhode Island, California and New York run
          their own marketplaces and aren't published here. Employer plans never are. Go back and
          enter your benefits by hand instead — ABYSS still works, it just can't look up the
          per-service details for you.
        </p>
      </div>
    );
  }

  // --- plan search ---------------------------------------------------------
  return (
    <div className="rounded-[var(--radius-lg)] border border-border bg-card p-6 shadow-sm">
      <button
        onClick={() => {
          setState(null);
          setQuery("");
          setPlans([]);
        }}
        className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden /> {state}
      </button>
      <h1 className="font-display text-2xl font-semibold leading-snug text-foreground">
        Find your plan
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Search by carrier or plan name — it's on your insurance card.
      </p>

      <div className="mt-4 flex items-center gap-2 rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2.5 focus-within:ring-2 focus-within:ring-ring">
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Anthem, Blue Cross, Bronze…"
          aria-label="Search plans"
          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
        />
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />}
      </div>

      <ul className="mt-4 max-h-80 space-y-2 overflow-y-auto pr-1">
        {plans.map((p) => (
          <li key={p.plan_id}>
            <button
              onClick={() => preview(p)}
              className="w-full rounded-[var(--radius-sm)] border border-border bg-background p-3 text-left transition-colors hover:bg-secondary"
            >
              <p className="text-sm font-medium leading-snug text-foreground">
                {p.marketing_name}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {p.metal_level} · {p.plan_type} · {money(p.deductible)} deductible ·{" "}
                {money(p.oop_max)} max
              </p>
            </button>
          </li>
        ))}
        {!loading && plans.length === 0 && (
          <li className="py-6 text-center text-sm text-muted-foreground">
            No plans match that search.
          </li>
        )}
      </ul>
    </div>
  );
}
