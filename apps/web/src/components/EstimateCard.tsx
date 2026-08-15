import { Check, ChevronDown, ExternalLink, FileText, MapPin } from "lucide-react";
import { useState } from "react";
import type { HospitalPrice } from "@/lib/api";
import { api, money, moneyExact, publishedOn } from "@/lib/api";

/** Verdict first, then the reasoning, then the receipt.
 *
 * The order matters: someone asking what an MRI costs wants the number, not a
 * rate table. The breakdown explains how their benefits produced it, and the
 * citation names the file it came from — that footer is the difference between
 * a price-transparency tool and a guess. */
export function EstimateCard({
  price,
  rank,
  onBooked,
}: {
  price: HospitalPrice;
  rank: number;
  /** Lets the shell refresh Home's "coming up" once something is recorded. */
  onBooked?: () => void;
}) {
  const [open, setOpen] = useState(rank === 0);
  const [saved, setSaved] = useState(false);
  const { estimate: est, citation } = price;
  const isRange = est.low !== est.high;

  return (
    <article className="rounded-[var(--radius-lg)] border border-border bg-card p-5 shadow-sm">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="font-display text-lg font-semibold text-foreground">{price.hospital}</h3>
        {rank === 0 && (
          <span className="shrink-0 rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
            Lowest
          </span>
        )}
      </header>

      {/* When the plan has no rule covering this service the figure is only the
          part that can be proven, so it is shown as a floor. Presenting it as
          "your estimated share" would be a confident number that is too low. */}
      <p className="mt-3 font-display text-3xl font-semibold tracking-tight text-primary">
        {est.complete === false && <span className="text-2xl">at least </span>}
        {isRange && est.complete !== false
          ? `${money(est.low)} – ${money(est.high)}`
          : moneyExact(est.expected)}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        {est.complete === false ? (
          "based on your deductible alone"
        ) : (
          <>
            your estimated share
            {isRange && <> · around {moneyExact(est.expected)} typical</>}
          </>
        )}
      </p>

      <p className="mt-3 text-sm text-muted-foreground">
        Hospital publishes {money(price.low)}–{money(price.high)} across {price.rate_count}{" "}
        {price.rate_count === 1 ? "plan" : "plans"}
        {price.description ? ` · ${price.description}` : ""}
      </p>

      {est.breakdown.length > 0 && (
        <button
          onClick={() => setOpen((v) => !v)}
          className="mt-4 flex w-full items-center justify-between rounded-[var(--radius-sm)] bg-muted/60 px-3 py-2 text-left text-sm font-medium text-foreground transition-colors hover:bg-muted"
          aria-expanded={open}
        >
          How this is calculated
          <ChevronDown
            className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
            aria-hidden
          />
        </button>
      )}

      {open && (
        <div className="mt-3 space-y-2">
          {est.breakdown.map((b) => (
            <div key={b.label} className="flex items-start justify-between gap-4 text-sm">
              <div>
                <p className="font-medium text-foreground">{b.label}</p>
                <p className="text-xs text-muted-foreground">{b.detail}</p>
              </div>
              <p className="shrink-0 font-medium tabular-nums text-foreground">
                {moneyExact(b.amount)}
              </p>
            </div>
          ))}

          <ul className="mt-3 space-y-1 border-t border-border pt-3">
            {est.caveats.map((c) => (
              <li key={c} className="text-xs leading-relaxed text-muted-foreground">
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      <footer className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-3 text-xs text-muted-foreground">
        <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>
          {price.code_type} {price.code}
        </span>
        {citation.last_updated_on && <span>· published {publishedOn(citation.last_updated_on)}</span>}
        {citation.mrf_url && (
          <a
            href={citation.mrf_url}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-foreground"
          >
            source file
          </a>
        )}
      </footer>

      {/* ABYSS has no scheduling integration, so it does not offer to book.
          What it does have is the hospital's real address and its own pricing
          page, both read from the file this estimate came from. */}
      {(price.address || citation.source_page_url) && (
        <div className="mt-4 space-y-2 rounded-[var(--radius-sm)] bg-muted/50 p-3">
          {price.address && (
            <p className="flex items-start gap-2 text-xs leading-relaxed text-muted-foreground">
              <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              {price.address}
            </p>
          )}
          {citation.source_page_url && (
            <a
              href={citation.source_page_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 text-xs font-medium text-primary underline underline-offset-2"
            >
              <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />
              Get an official estimate from {price.hospital}
            </a>
          )}
        </div>
      )}

      {/* Booking still happens on the phone. What ABYSS can do is stop the
          estimate evaporating the moment the call ends. */}
      {saved ? (
        <p className="mt-3 flex items-center gap-2 text-xs font-medium text-primary">
          <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />
          Saved to your appointments
        </p>
      ) : (
        <button
          onClick={async () => {
            await api
              .addAppointment({
                hospital_id: price.hospital_id,
                code: price.code,
                description: `${price.description || price.code} at ${price.hospital}`,
                estimated_cost: price.estimate.expected,
              })
              .catch(() => {});
            setSaved(true);
            onBooked?.();
          }}
          className="mt-3 w-full rounded-[var(--radius-sm)] border border-border px-4 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
        >
          I booked this — keep the estimate
        </button>
      )}
    </article>
  );
}
