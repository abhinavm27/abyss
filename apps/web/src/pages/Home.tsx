import {
  Building2,
  CalendarCheck,
  ChevronRight,
  Mic,
  Receipt,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { DeductibleRing } from "@/components/DeductibleRing";
import {
  api,
  money,
  publishedOn,
  type Appointment,
  type PlanSnapshotResponse,
  type RecentLookup,
} from "@/lib/api";

/** Where you land, and where you come back to.
 *
 * Before this existed the app opened onto a search box with a large empty
 * middle. A home screen gives it somewhere calm to rest: where you stand on your
 * deductible, the questions you've already asked, and one obvious way to ask
 * another. */

/** The things ABYSS can do, as places you can go.
 *
 * Named here rather than only in the tab bar because three tabs cannot carry
 * five features, and a capability nobody can find is the same as one that does
 * not exist. */
const FEATURES = [
  {
    key: "ask" as const,
    icon: Search,
    title: "What will it cost?",
    body: "Price a procedure against real published rates",
  },
  {
    key: "insurance" as const,
    icon: ShieldCheck,
    title: "Insurance",
    body: "Compare plans, or scan the card you already have",
  },
  {
    key: "bill" as const,
    icon: Receipt,
    title: "Check a bill",
    body: "Compare what you were charged to published rates",
  },
  {
    key: "appointments" as const,
    icon: CalendarCheck,
    title: "Appointments",
    body: "Keep what you booked, and what it should cost",
  },
  {
    key: "coverage" as const,
    icon: Building2,
    title: "What ABYSS covers",
    body: "Every hospital, and when it published prices",
  },
];

export type HomeDestination = (typeof FEATURES)[number]["key"];

export function Home({
  dataVersion,
  onAsk,
  onOpenPlan,
  onOpen,
}: {
  /** Bumped when the plan changes elsewhere. This screen is never unmounted, so
   *  without it the deductible ring would keep showing a stale figure. */
  dataVersion: number;
  onAsk: (question?: string, viaVoice?: boolean) => void;
  onOpenPlan: () => void;
  onOpen: (where: HomeDestination) => void;
}) {
  const [plan, setPlan] = useState<PlanSnapshotResponse | null>(null);
  const [recent, setRecent] = useState<RecentLookup[]>([]);
  const [nextAppt, setNextAppt] = useState<Appointment | null>(null);

  useEffect(() => {
    void api.planSummary().then(setPlan).catch(() => {});
    void api
      .history(3)
      .then((r) => setRecent(r.recent))
      .catch(() => {});
    void api
      .appointments()
      .then((r) => setNextAppt(r.appointments[0] ?? null))
      .catch(() => {});
  }, [dataVersion]);

  const deductible = Number(plan?.deductible ?? 0);
  const deductibleMet = Number(plan?.deductible_met ?? 0);
  const hasDeductible = plan?.configured === true && deductible > 0;
  const isMet = hasDeductible && deductibleMet >= deductible;

  return (
    <main className="abyss-home mx-auto w-full max-w-md pb-[calc(6rem+env(safe-area-inset-bottom))]">
      <header className="abyss-home__hero">
        <div className="abyss-home__brand"><span>S</span><b>ABYSS</b></div>
        <div className="abyss-home__copy">
          <p>VOICE-FIRST HEALTHCARE<br />PRICE TRANSPARENCY.</p>
          <h1>ABYSS —<br />Dive for Answers</h1>
          <h2>Ask ABYSS.</h2>
          <span>ABYSS dives deep so<br />you don’t have to.</span>
        </div>
        <img src="/mascot/approved/abyss-wave.png" alt="ABYSS waving in the ocean" />
      </header>

      <div className="abyss-home__body">
        <section className="abyss-home__ask">
          <p>WHAT CAN ABYSS FIND FOR YOU?</p>
          <h2>Healthcare prices,<br />made clear.</h2>
          <button onClick={() => onAsk(undefined, true)} aria-label="Ask ABYSS by voice">
            <span><Mic aria-hidden /></span><b>Tap to ask anything<br />about healthcare costs.</b>
          </button>
          <button className="abyss-home__type" onClick={() => onAsk()}>or type a question</button>
        </section>

        <section className="abyss-home__features" aria-label="ABYSS features">
          <button onClick={() => onOpen("coverage")}><span>⌖</span><b>Find Care</b><small>Compare in-network providers and facilities.</small></button>
          <button onClick={() => onAsk()}><span>$</span><b>Understand Costs</b><small>See real costs before you get care.</small></button>
          <button onClick={onOpenPlan}><span>✓</span><b>Feel Confident</b><small>Make informed decisions with confidence.</small></button>
        </section>
      </div>

      <div className="abyss-home__body abyss-home__details">
      {hasDeductible && (
        <section>
          {/* The ring is the natural way into the plan now that the header link
              is gone — the tab bar covers the rest. */}
          <button onClick={onOpenPlan} className="block w-full" aria-label="Open your plan">
            <DeductibleRing met={deductibleMet} total={deductible} />
          </button>
          {isMet && (
            <img
              src="/illustrations/growth.webp"
              alt=""
              width={1000}
              height={1400}
              loading="lazy"
              className="mx-auto mt-4 h-24 w-auto object-contain"
            />
          )}
        </section>
      )}

      {nextAppt && (
        <section className="mt-8">
          <h2 className="text-sm font-medium text-foreground">Coming up</h2>
          <button
            onClick={() => onOpen("appointments")}
            className="mt-2 flex w-full items-center gap-3 rounded-[var(--radius-sm)] border border-border bg-card p-3 text-left transition-colors hover:bg-secondary"
          >
            <CalendarCheck className="h-5 w-5 shrink-0 text-primary" aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-foreground">
                {nextAppt.description || nextAppt.code}
              </span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                {[
                  nextAppt.hospital,
                  nextAppt.booked_for ? publishedOn(nextAppt.booked_for) : null,
                  nextAppt.estimated_cost != null
                    ? `about ${money(nextAppt.estimated_cost)}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          </button>
        </section>
      )}

      <section className="mt-8">
        <h2 className="text-sm font-medium text-foreground">Everything ABYSS does</h2>
        <ul className="mt-2 grid grid-cols-2 gap-2">
          {FEATURES.map(({ key, icon: Icon, title, body }) => (
            <li key={key}>
              <button
                onClick={() => onOpen(key)}
                className="flex h-full w-full flex-col rounded-[var(--radius-sm)] border border-border bg-card p-3 text-left transition-colors hover:bg-secondary"
              >
                <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
                <span className="mt-2 text-sm font-medium leading-snug text-foreground">
                  {title}
                </span>
                <span className="mt-1 text-xs leading-relaxed text-muted-foreground">{body}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {recent.length > 0 && (
        <section className="mt-9">
          <h2 className="text-sm font-medium text-foreground">Recently asked</h2>
          <ul className="mt-2 space-y-2">
            {recent.map((r) => (
              <li key={r.code}>
                <button
                  onClick={() => onAsk(r.query)}
                  className="flex w-full items-center gap-3 rounded-[var(--radius-sm)] border border-border bg-card p-3 text-left transition-colors hover:bg-secondary"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-foreground">
                      {r.description || r.query}
                    </span>
                    {r.low != null && r.high != null && (
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {r.low === r.high
                          ? money(r.low)
                          : `${money(r.low)} – ${money(r.high)}`}{" "}
                        your share
                      </span>
                    )}
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      </div>
    </main>
  );
}
