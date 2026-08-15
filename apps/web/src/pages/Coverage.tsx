import { ArrowLeft, ExternalLink, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, campuses, publishedOn, type Hospital } from "@/lib/api";

/** Where the numbers come from.
 *
 * ABYSS's whole claim is that these are prices hospitals published themselves,
 * and until now that claim could not be checked from inside the app. This is the
 * same instinct as the citation footer on an estimate, at the level of the whole
 * dataset: every hospital, how many rates it published, and when. */
export function Coverage({ onBack }: { onBack: () => void }) {
  const [hospitals, setHospitals] = useState<Hospital[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .hospitals()
      .then((h) => setHospitals([...h].sort((a, b) => a.name.localeCompare(b.name))))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const totalRates = hospitals?.reduce((sum, h) => sum + (h.rates ?? 0), 0) ?? 0;

  return (
    <main className="mx-auto w-full max-w-md px-5 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-[calc(env(safe-area-inset-top)+1.5rem)]">
      <header className="mb-5">
        <button
          onClick={onBack}
          className="-ml-1 flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Plan
        </button>
      </header>

      <h1 className="font-display text-2xl font-semibold text-foreground">What ABYSS covers</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        Every hospital below publishes its own prices, as federal law requires. ABYSS reads those
        files directly — it never estimates or averages across them.
      </p>

      {hospitals && (
        <p className="mt-4 rounded-[var(--radius-sm)] bg-secondary/60 px-3 py-2 text-sm text-secondary-foreground">
          {hospitals.length} hospitals · {totalRates.toLocaleString("en-US")} published rates
        </p>
      )}

      {!hospitals && !error && (
        <div className="flex items-center gap-3 py-10 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
          <span className="text-sm">Loading…</span>
        </div>
      )}

      {error && (
        <p className="mt-4 rounded-[var(--radius-sm)] border border-destructive/30 bg-destructive/10 p-3 text-sm text-foreground">
          {error}
        </p>
      )}

      <ul className="mt-4 space-y-2">
        {hospitals?.map((h) => {
          const sites = campuses(h.address);
          return (
          <li
            key={h.id}
            className="rounded-[var(--radius-sm)] border border-border bg-card p-3"
          >
            <p className="text-sm font-medium leading-snug text-foreground">{h.name}</p>
            {sites.length > 0 && (
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                {sites[0]}
                {sites.length > 1 && (
                  <span className="text-muted-foreground/80">
                    {" "}
                    + {sites.length - 1} more {sites.length === 2 ? "campus" : "campuses"}
                  </span>
                )}
              </p>
            )}
            <p className="mt-1.5 text-xs text-muted-foreground">
              {(h.rates ?? 0).toLocaleString("en-US")} rates
              {h.last_updated_on ? ` · published ${publishedOn(h.last_updated_on)}` : ""}
            </p>
            {h.mrf_url && (
              <a
                href={h.mrf_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1.5 inline-flex items-center gap-1.5 text-xs font-medium text-primary underline underline-offset-2"
              >
                <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
                source file
              </a>
            )}
          </li>
          );
        })}
      </ul>
    </main>
  );
}
