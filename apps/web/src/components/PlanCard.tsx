import { ShieldCheck } from "lucide-react";
import { CATEGORY_LABELS, moneyExact } from "@/lib/api";

export interface PlanSnapshot {
  configured: boolean;
  label?: string | null;
  payer_name?: string | null;
  source?: string;
  deductible?: number;
  deductible_met?: number;
  deductible_remaining?: number;
  oop_max?: number;
  oop_met?: number;
  oop_remaining?: number | null;
  benefits?: {
    category: string;
    kind: string;
    amount: number;
    after_deductible: number;
    description: string;
  }[];
  /** The category the member asked about, so it can be pulled to the top. */
  highlight?: string;
}

/** Rendered when a voice turn asks about the member's own coverage.
 *
 * Progress bars rather than bare numbers: "you have $2,800 of your deductible
 * left" is the thing people actually want to know, and it is much easier to read
 * as a filled bar than as two figures to subtract. */
export function PlanCard({ plan }: { plan: PlanSnapshot }) {
  if (!plan.configured) {
    return (
      <article className="rounded-[var(--radius-lg)] border border-border bg-card p-5 shadow-sm">
        <h3 className="font-display text-lg font-semibold text-foreground">
          No plan set up yet
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Add your plan and ABYSS can tell you what you'll actually pay, rather than what a
          hospital charges.
        </p>
      </article>
    );
  }

  const bar = (met: number, total: number) =>
    total > 0 ? Math.min(100, Math.max(0, (met / total) * 100)) : 0;

  const benefits = plan.benefits ?? [];
  const highlighted = plan.highlight
    ? benefits.filter((b) => b.category === plan.highlight)
    : [];
  const rest = plan.highlight
    ? benefits.filter((b) => b.category !== plan.highlight)
    : benefits;

  return (
    <article className="rounded-[var(--radius-lg)] border border-border bg-card p-5 shadow-sm">
      <header className="flex items-start gap-2.5">
        <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
        <div>
          <h3 className="font-display text-lg font-semibold leading-snug text-foreground">
            {plan.label || "Your plan"}
          </h3>
          {(plan.payer_name || plan.source) && (
            <p className="text-xs text-muted-foreground">
              {[plan.payer_name, plan.source].filter(Boolean).join(" · ")}
            </p>
          )}
        </div>
      </header>

      <div className="mt-4 space-y-3">
        {[
          {
            label: "Deductible",
            met: plan.deductible_met ?? 0,
            total: plan.deductible ?? 0,
            remaining: plan.deductible_remaining ?? 0,
          },
          {
            label: "Out-of-pocket maximum",
            met: plan.oop_met ?? 0,
            total: plan.oop_max ?? 0,
            remaining: plan.oop_remaining ?? null,
          },
        ]
          .filter((r) => r.total > 0)
          .map((r) => (
            <div key={r.label}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="text-muted-foreground">{r.label}</span>
                <span className="shrink-0 whitespace-nowrap font-medium tabular-nums text-foreground">
                  {moneyExact(r.met)} of {moneyExact(r.total)}
                </span>
              </div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-[width]"
                  style={{ width: `${bar(r.met, r.total)}%` }}
                />
              </div>
              {r.remaining != null && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {r.remaining > 0
                    ? `${moneyExact(r.remaining)} to go`
                    : "Met — your plan pays from here"}
                </p>
              )}
            </div>
          ))}
      </div>

      {/* Stacked, not two columns: the thing they asked about deserves the
          emphasis, and descriptions like "20% coinsurance after the deductible"
          are too long to sit opposite a label on a phone-width card. */}
      {highlighted.length > 0 && (
        <div className="mt-4 rounded-[var(--radius-sm)] bg-secondary/60 p-3">
          {highlighted.map((b) => (
            <div key={b.category}>
              <p className="text-xs text-muted-foreground">
                {CATEGORY_LABELS[b.category] ?? b.category}
              </p>
              <p
                className={`mt-0.5 font-display text-lg font-semibold leading-snug ${
                  b.kind === "not_covered" ? "text-destructive" : "text-foreground"
                }`}
              >
                {b.description}
              </p>
            </div>
          ))}
        </div>
      )}

      {rest.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            What this plan charges ({rest.length} more)
          </summary>
          {/* Stacked rather than two columns. "20% coinsurance after the
              deductible" opposite a label overflows a phone-width card, and
              truncating the part that says when it applies would be worse than
              using a second line. */}
          <ul className="mt-2 max-h-56 space-y-2.5 overflow-y-auto pr-1">
            {rest.map((b) => (
              <li key={b.category} className="text-sm">
                <p className="text-xs text-muted-foreground">
                  {CATEGORY_LABELS[b.category] ?? b.category}
                </p>
                <p
                  className={`font-medium ${
                    b.kind === "not_covered" ? "text-destructive" : "text-foreground"
                  }`}
                >
                  {b.description}
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
