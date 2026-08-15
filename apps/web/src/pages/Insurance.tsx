import {
  ArrowLeft,
  Camera,
  Check,
  FileUp,
  Loader2,
  Scale,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { captureCard } from "@/lib/cardScan";
import { api, money, type CardScan, type MyPlan, type PlanComparison } from "@/lib/api";

/** Insurance: the plans you hold, and what they actually cost you.
 *
 * The comparison is built on documents the member supplies rather than on the
 * marketplace catalogue, because the catalogue cannot help them. All 20,671
 * plans in it come from the 31 states on the federal exchange; Massachusetts
 * runs its own Health Connector and is absent — while every hospital ABYSS has
 * priced is in Massachusetts.
 *
 * What ABYSS can do that a plan-comparison site cannot is compare plans against
 * a real published hospital rate rather than against premiums. */
export function Insurance({
  dataVersion,
  onBack,
  onChanged,
  onAsk,
}: {
  dataVersion: number;
  onBack: () => void;
  onChanged: () => void;
  onAsk: (question: string) => void;
}) {
  const [plans, setPlans] = useState<MyPlan[] | null>(null);
  const [query, setQuery] = useState("");
  const [comparison, setComparison] = useState<PlanComparison | null>(null);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scan, setScan] = useState<CardScan | null>(null);

  async function scanCard() {
    setError(null);
    const file = await captureCard().catch(() => null);
    if (!file) return;
    setScanning(true);
    try {
      setScan(await api.scanCard(file));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setScanning(false);
    }
  }

  async function refresh() {
    const r = await api.myPlans();
    setPlans(r.plans);
  }

  useEffect(() => {
    void refresh().catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataVersion]);

  async function compare(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setComparing(true);
    setError(null);
    try {
      setComparison(await api.comparePlans(query.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setComparing(false);
    }
  }

  async function activate(id: number) {
    await api.activatePlan(id).catch(() => {});
    await refresh();
    onChanged();
  }

  async function remove(id: number) {
    await api.removePlan(id).catch(() => {});
    await refresh();
    setComparison(null);
    onChanged();
  }

  const canCompare = (plans?.length ?? 0) >= 2;

  // Rows arrive cheapest first, so the gap between the ends is what choosing
  // the better plan is worth for this one procedure.
  const rows = comparison?.plans ?? [];
  const spread =
    rows.length > 1 ? rows[rows.length - 1].estimate.expected - rows[0].estimate.expected : 0;

  return (
    <main className="mx-auto w-full max-w-md px-5 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-[calc(env(safe-area-inset-top)+1.5rem)]">
      <header className="mb-5">
        <button
          onClick={onBack}
          className="-ml-1 flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back
        </button>
      </header>

      <h1 className="font-display text-2xl font-semibold text-foreground">Insurance</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        Add the plans you're weighing up, then price the care you actually expect to need against
        each one.
      </p>

      {error && (
        <p className="mt-4 rounded-[var(--radius-sm)] border border-destructive/30 bg-destructive/10 p-3 text-sm text-foreground">
          {error}
        </p>
      )}

      {/* --- two ways in ---------------------------------------------------- */}
      <div className="mt-5 grid gap-2">
        <button
          onClick={() => void scanCard()}
          disabled={scanning}
          className="flex items-center gap-3 rounded-[var(--radius-sm)] border border-border bg-card p-4 text-left transition-colors hover:bg-secondary disabled:opacity-60"
        >
          {scanning ? (
            <Loader2 className="h-5 w-5 shrink-0 animate-spin text-primary" aria-hidden />
          ) : (
            <Camera className="h-5 w-5 shrink-0 text-primary" aria-hidden />
          )}
          <span>
            <span className="block text-sm font-medium text-foreground">
              {scanning ? "Reading your card…" : "Scan the card I already have"}
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Reads your payer and plan name from the photo
            </span>
          </span>
        </button>

        <button
          onClick={() => onAsk("upload my summary of benefits")}
          className="flex items-center gap-3 rounded-[var(--radius-sm)] border border-border bg-card p-4 text-left transition-colors hover:bg-secondary"
        >
          <FileUp className="h-5 w-5 shrink-0 text-primary" aria-hidden />
          <span>
            <span className="block text-sm font-medium text-foreground">
              Add a plan from its document
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              A Summary of Benefits PDF carries the real numbers
            </span>
          </span>
        </button>
      </div>

      {scan && (
        <div className="mt-2 rounded-[var(--radius-sm)] border border-border bg-card p-4">
          {scan.warnings.map((w) => (
            <p key={w} className="text-xs leading-relaxed text-muted-foreground">
              {w}
            </p>
          ))}

          {(scan.payer_name || scan.plan_name) && (
            <>
              <p className="text-sm font-medium text-foreground">
                {scan.plan_name || scan.payer_name}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {[scan.payer_name, scan.plan_type, scan.member_id && `member ${scan.member_id}`]
                  .filter(Boolean)
                  .join(" · ")}
              </p>

              {Object.keys(scan.copays).length > 0 && (
                <ul className="mt-3 space-y-1">
                  {Object.entries(scan.copays).map(([label, amount]) => (
                    <li key={label} className="flex justify-between text-xs">
                      <span className="text-muted-foreground">{label}</span>
                      <span className="font-medium text-foreground">{money(amount)}</span>
                    </li>
                  ))}
                </ul>
              )}

              {/* The load-bearing sentence on this screen. A card identifies the
                  plan and nothing more; saying so is what stops a scan being
                  mistaken for a finished setup. */}
              <p className="mt-3 rounded-[var(--radius-sm)] bg-secondary/60 p-3 text-xs leading-relaxed text-secondary-foreground">
                That's everything the card carries. It doesn't print your deductible,
                out-of-pocket maximum or coinsurance — so ABYSS can't estimate from this alone.
                Add the Summary of Benefits for that plan and the estimates become exact.
              </p>
            </>
          )}
        </div>
      )}

      {/* --- the plans held ------------------------------------------------- */}
      {plans && plans.length > 0 && (
        <section className="mt-7">
          <h2 className="text-sm font-medium text-foreground">Your plans</h2>
          <ul className="mt-2 space-y-2">
            {plans.map((p) => (
              <li
                key={p.id}
                className={`flex items-start gap-3 rounded-[var(--radius-sm)] border p-3 ${
                  p.is_active ? "border-primary/40 bg-primary/5" : "border-border bg-card"
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium leading-snug text-foreground">
                    {p.label || "Untitled plan"}
                  </span>
                  {/* Coinsurance is only shown when the plan actually carries a
                      blended rate. Plans with per-service benefits store 0 here
                      and keep the real rules in plan_benefit, so printing it
                      unconditionally reported "0% coinsurance" for a plan with
                      20% in its own name. */}
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {[
                      `${money(p.deductible)} deductible`,
                      p.coinsurance_pct > 0
                        ? `${Math.round(p.coinsurance_pct * 100)}% coinsurance`
                        : null,
                      `${money(p.oop_max)} out-of-pocket cap`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                  {p.is_active ? (
                    <span className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary">
                      <Check className="h-3 w-3" aria-hidden /> Used for your estimates
                    </span>
                  ) : (
                    <button
                      onClick={() => void activate(p.id)}
                      className="mt-1 text-xs font-medium text-primary underline underline-offset-2"
                    >
                      Use this one
                    </button>
                  )}
                </span>
                <button
                  onClick={() => void remove(p.id)}
                  aria-label={`Remove ${p.label || "plan"}`}
                  className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* --- comparison ----------------------------------------------------- */}
      <section className="mt-7">
        <h2 className="text-sm font-medium text-foreground">Compare on real prices</h2>
        {!canCompare ? (
          <p className="mt-2 rounded-[var(--radius-sm)] border border-border bg-card p-4 text-sm leading-relaxed text-muted-foreground">
            Add a second plan and ABYSS will price the same procedure, at the same hospital,
            under each of them.
          </p>
        ) : (
          <>
            <form onSubmit={compare} className="mt-2 flex gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="MRI of my knee"
                aria-label="Procedure to compare"
                className="min-w-0 flex-1 rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
              />
              <button
                type="submit"
                disabled={comparing}
                className="flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-60"
              >
                {comparing ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Scale className="h-4 w-4" aria-hidden />
                )}
                Compare
              </button>
            </form>

            {comparison && (
              <div className="mt-4">
                {comparison.message && (
                  <p className="text-sm text-muted-foreground">{comparison.message}</p>
                )}
                {comparison.plans.length > 0 && (
                  <>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {comparison.resolved?.description} at {comparison.hospital} — the cheapest
                      hospital publishing this. Same care, same place; only the plan changes.
                    </p>

                    {/* A tie is a real answer, not a failure. Below every
                        deductible the member pays the full allowed amount
                        whichever plan they are on, and saying so is more use
                        than two identical figures and no explanation. */}
                    {spread === 0 && (
                      <p className="mt-2 rounded-[var(--radius-sm)] bg-secondary/60 p-3 text-xs leading-relaxed text-secondary-foreground">
                        Same cost on every plan here — at {money(comparison.allowed ?? 0)} this
                        falls below each deductible, so you pay the full amount either way. Plans
                        start to differ on bills large enough to cross one.
                      </p>
                    )}
                    <ul className="mt-3 space-y-2">
                      {comparison.plans.map((row, i) => (
                        <li
                          key={row.plan_id}
                          className={`rounded-[var(--radius-sm)] border p-3 ${
                            i === 0 ? "border-primary/40 bg-primary/5" : "border-border bg-card"
                          }`}
                        >
                          <div className="flex items-baseline justify-between gap-3">
                            <span className="min-w-0 truncate text-sm font-medium text-foreground">
                              {row.label || "Untitled plan"}
                            </span>
                            <span className="shrink-0 font-display text-lg text-foreground">
                              {money(row.estimate.expected)}
                            </span>
                          </div>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {money(row.estimate.low)} – {money(row.estimate.high)}
                            {i === 0 && spread > 0 && (
                              <span className="ml-1 font-medium text-primary">
                                · saves {money(spread)}
                              </span>
                            )}
                          </p>
                        </li>
                      ))}
                    </ul>
                    <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                      This is what you'd pay at the counter. It doesn't include premiums — ABYSS
                      has no premium data, and leaving that unsaid would make the comparison look
                      more complete than it is.
                    </p>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}
