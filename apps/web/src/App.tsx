import { useCallback, useEffect, useRef, useState } from "react";
import { TabBar, isTab, type Tab } from "@/components/TabBar";
import { VoiceBar } from "@/components/VoiceBar";
import { useVoiceSession } from "@/hooks/useVoiceSession";
import { Appointments } from "@/pages/Appointments";
import { Ask } from "@/pages/Ask";
import { Bill } from "@/pages/Bill";
import { Coverage } from "@/pages/Coverage";
import { Insurance } from "@/pages/Insurance";
import { Home } from "@/pages/Home";
import { Onboarding } from "@/pages/Onboarding";
import { PlanPage } from "@/pages/PlanPage";
import { Welcome } from "@/pages/Welcome";
import { SignIn } from "@/pages/SignIn";
import { api, getToken, NotSignedIn, type PlanBody } from "@/lib/api";

/** Screens you pass through, rather than places you navigate between. Only the
 *  tabs live inside the shell. */
type Phase = "loading" | "welcome" | "signedOut" | "onboarding" | "shell" | "offline";

/** A screen pushed over a tab, rather than a tab of its own. */
type Overlay = "coverage" | "insurance" | "appointments" | "bill" | null;

const WELCOME_SEEN = "abyss.welcomeSeen";
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

const DEMO_PLAN: PlanBody & { id: number } = {
  id: 1,
  label: "Example PPO plan",
  payer_name: "Demo insurer",
  deductible: 2000,
  deductible_met: 650,
  coinsurance_pct: 0.2,
  copay: 30,
  oop_max: 8000,
  oop_met: 920,
};

/** The tab a URL points at. Anything unrecognised — a stale link, a hand-edited
 *  hash, a deep link from a future version — lands on Home rather than a blank
 *  shell. */
export function tabFromHash(hash: string = window.location.hash): Tab {
  const h = hash.replace(/^#/, "");
  return isTab(h) ? h : "home";
}

export default function App() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [plan, setPlan] = useState<(PlanBody & { id: number }) | null>(null);

  // How many hospitals are loaded, from the health check we already make. This
  // number appears in user-facing copy, and it moved 3 → 25 → 41 → 57 over a
  // few days of ingest, so it is read from the data rather than typed in.
  const [hospitalCount, setHospitalCount] = useState(0);
  const [tab, setTab] = useState<Tab>(tabFromHash);

  // Screens pushed on top of a tab. A single `showCoverage` boolean was fine
  // for one of them; with three it becomes a stack of one, pushed onto history
  // so back closes the overlay before it changes tab.
  const [overlay, setOverlay] = useState<Overlay>(null);

  // Tabs mount lazily and then stay mounted, which is what lets Ask keep both
  // its answer and its WebSocket. `seen` tracks which have been visited so an
  // unopened tab costs nothing.
  const [seen, setSeen] = useState<Set<Tab>>(() => new Set<Tab>([tabFromHash()]));

  // Nothing remounts any more, so a mounted Home would hold a stale deductible
  // ring after the plan is edited on another tab. Every screen that reads
  // server state takes this and refetches when it changes.
  const [dataVersion, setDataVersion] = useState(0);
  const refreshData = useCallback(() => setDataVersion((v) => v + 1), []);

  // A question handed to Ask. The nonce changes on every hand-off, so asking
  // the same question twice still runs.
  const [pending, setPending] = useState<{ question?: string; voice?: boolean; nonce: number }>({
    nonce: 0,
  });

  // The voice session lives here so it survives leaving the Ask tab. Ask
  // registers what to do with `ui` events once it is mounted.
  const uiHandler = useRef<(target: string, payload: unknown) => void>(() => {});
  const onVoiceUi = useCallback((h: (target: string, payload: unknown) => void) => {
    uiHandler.current = h;
  }, []);
  const voice = useVoiceSession({
    onUiEvent: (target, payload) => uiHandler.current(target, payload),
  });

  const goTab = useCallback((next: Tab, viaHistory = false) => {
    setTab(next);
    setSeen((s) => (s.has(next) ? s : new Set(s).add(next)));
    setOverlay(null);
    if (!viaHistory) window.history.pushState({ tab: next }, "", `#${next}`);
  }, []);

  const openOverlay = useCallback((next: Exclude<Overlay, null>) => {
    setOverlay(next);
    window.history.pushState({ tab: tabFromHash(), overlay: next }, "", `#${next}`);
  }, []);

  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      // One handler for both, because they share a history stack: a state entry
      // carrying an overlay restores it, and any other entry closes it.
      const next = (e.state?.overlay as Overlay) ?? null;
      setOverlay(next);
      if (!next) {
        const t = (e.state?.tab as Tab) ?? tabFromHash();
        setTab(t);
        setSeen((s) => (s.has(t) ? s : new Set(s).add(t)));
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  async function load() {
    if (DEMO_MODE) {
      setHospitalCount(41);
      setPlan(DEMO_PLAN);
      setPhase("shell");
      return;
    }
    try {
      const h = await api.health();
      setHospitalCount(h.hospitals ?? 0);
    } catch {
      setPhase("offline");
      return;
    }

    // Welcome explains what ABYSS is, so it comes before being asked to hand
    // over an email address.
    if (!localStorage.getItem(WELCOME_SEEN)) {
      setPhase("welcome");
      return;
    }
    if (!getToken()) {
      setPhase("signedOut");
      return;
    }

    try {
      const p = await api.getPlan();
      setPlan(p);
      refreshData();
      setPhase(p ? "shell" : "onboarding");
    } catch (e) {
      // An expired or revoked session is not an outage — send them to sign in
      // rather than to the "can't reach the price data" screen.
      setPhase(e instanceof NotSignedIn ? "signedOut" : "offline");
    }
  }

  useEffect(() => {
    void load();
    // Replace rather than push, so the first back press leaves the app instead
    // of stepping through a tab the person never chose.
    window.history.replaceState({ tab: tabFromHash() }, "", `#${tabFromHash()}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (phase === "loading") {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-background px-6">
        <p className="text-center text-sm leading-relaxed text-muted-foreground">
          Getting your plan details together…
        </p>
      </main>
    );
  }

  if (phase === "offline") {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="font-display text-2xl font-semibold leading-snug text-foreground">
          ABYSS can't reach its price data
        </h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Nothing is wrong with your plan details — the service that holds the published hospital
          prices just isn't responding.
        </p>
        <button
          onClick={() => {
            setPhase("loading");
            void load();
          }}
          className="mt-1 rounded-[var(--radius-sm)] bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground"
        >
          Try again
        </button>

        {/* A real affordance for whoever is running this locally, but not the
            first thing a person reads when something looks broken. */}
        <details className="mt-3 text-left">
          <summary className="cursor-pointer text-center text-xs text-muted-foreground">
            Running ABYSS yourself?
          </summary>
          <code className="mt-2 block rounded-[var(--radius-sm)] bg-muted px-3 py-2 text-xs text-foreground">
            cd backend &amp;&amp; .venv/bin/uvicorn app.api:app --port 8010
          </code>
        </details>
      </main>
    );
  }

  if (phase === "welcome") {
    return (
      <Welcome
        onStart={() => {
          localStorage.setItem(WELCOME_SEEN, "1");
          setPhase(getToken() ? "onboarding" : "signedOut");
        }}
      />
    );
  }

  if (phase === "signedOut") {
    return <SignIn onSignedIn={() => void load()} />;
  }

  if (phase === "onboarding") {
    return <Onboarding onDone={() => void load()} />;
  }

  const configured = Boolean(
    plan && (plan.deductible || plan.oop_max || plan.coinsurance_pct || plan.copay),
  );

  // Reference and detail screens, reached from Home or Plan rather than given a
  // tab each — four tabs of equal weight would bury the thing people came for.
  if (overlay) {
    const back = () => window.history.back();
    return (
      <div className="min-h-dvh bg-background">
        {overlay === "coverage" && <Coverage onBack={back} />}
        {overlay === "insurance" && (
          <Insurance
            dataVersion={dataVersion}
            onBack={back}
            onChanged={refreshData}
            onAsk={(q) => {
              setPending((p) => ({ question: q, nonce: p.nonce + 1 }));
              goTab("ask");
            }}
          />
        )}
        {overlay === "bill" && <Bill onBack={back} />}
        {overlay === "appointments" && (
          <Appointments dataVersion={dataVersion} onBack={back} onChanged={refreshData} />
        )}
        <TabBar active={tab} onChange={goTab} />
      </div>
    );
  }

  const voiceLive = voice.isActive && tab !== "ask";

  return (
    <div className="min-h-dvh bg-background">
      {seen.has("home") && (
        <div hidden={tab !== "home"}>
          <Home
            dataVersion={dataVersion}
            onAsk={(question, viaVoice) => {
              setPending((p) => ({ question, voice: viaVoice, nonce: p.nonce + 1 }));
              goTab("ask");
            }}
            onOpenPlan={() => goTab("plan")}
            onOpen={(where) => (where === "ask" ? goTab("ask") : openOverlay(where))}
          />
        </div>
      )}

      {seen.has("ask") && (
        <div hidden={tab !== "ask"}>
          <Ask
            planConfigured={configured}
            hospitalCount={hospitalCount}
            pending={pending}
            voice={voice}
            onVoiceUi={onVoiceUi}
            onBooked={refreshData}
          />
        </div>
      )}

      {seen.has("plan") && (
        <div hidden={tab !== "plan"}>
          <PlanPage
            dataVersion={dataVersion}
            hospitalCount={hospitalCount}
            onChanged={refreshData}
            onOpenCoverage={() => openOverlay("coverage")}
            onSignOut={async () => {
              await api.logout();
              setPlan(null);
              setSeen(new Set<Tab>(["home"]));
              setTab("home");
              setPhase("signedOut");
            }}
            onReplacePlan={async () => {
              // Clear the stored plan so onboarding is reachable again. Benefits
              // from an uploaded document survive under their reserved id.
              await api.deletePlan().catch(() => {});
              setPlan(null);
              setPhase("onboarding");
            }}
          />
        </div>
      )}

      {voiceLive && (
        <VoiceBar
          status={voice.status}
          micLevel={voice.micLevel}
          onReturn={() => goTab("ask")}
        />
      )}
      <TabBar active={tab} onChange={goTab} />
    </div>
  );
}
