import { AlertCircle, ArrowUp, Loader2, Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { EstimateCard } from "@/components/EstimateCard";
import { PlanCard, type PlanSnapshot } from "@/components/PlanCard";
import { VOICE_LABEL, type useVoiceSession } from "@/hooks/useVoiceSession";
import {
  api,
  categoryFor,
  isPlanQuestion,
  money,
  type PriceResponse,
} from "@/lib/api";

const SUGGESTIONS = [
  "MRI of my knee",
  "Colonoscopy",
  "What's my deductible?",
  "What do I pay for a specialist?",
];

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

function demoResult(query: string): PriceResponse {
  return {
    query,
    resolved: { code: "73721", code_type: "CPT", description: query || "MRI without contrast" },
    resolution: "demo",
    plan_configured: true,
    hospitals: [
      {
        hospital_id: 1,
        hospital: "Coastal Imaging Center",
        description: query,
        code: "73721",
        code_type: "CPT",
        rate_count: 18,
        low: 980,
        typical: 1310,
        high: 1680,
        address: "128 Harbor Way, Seattle, WA",
        citation: { mrf_url: null, source_page_url: null, last_updated_on: "2026-07-01" },
        estimate: {
          expected: 612,
          low: 520,
          high: 730,
          allowed: 1310,
          complete: true,
          breakdown: [
            { label: "Deductible", amount: 450, detail: "Remaining deductible" },
            { label: "Coinsurance", amount: 120, detail: "20% after deductible" },
            { label: "Facility fee", amount: 42, detail: "Published facility component" },
          ],
          caveats: ["Demo estimate using representative plan information."],
        },
      },
    ],
    cash_prices: [{ hospital: "Coastal Imaging Center", low: 980, high: 1680 }],
  };
}

export function Ask({
  planConfigured,
  hospitalCount,
  pending,
  voice,
  onVoiceUi,
  onBooked,
}: {
  planConfigured: boolean;
  /** Something was recorded as an appointment, so Home should refresh. */
  onBooked: () => void;
  /** Shown when a question doesn't resolve, so "no match" reads as the limit of
   *  the dataset rather than a broken app. */
  hospitalCount: number;
  /** A question handed over from Home. `nonce` changes on every hand-off so the
   *  same question asked twice still runs — this tab is never unmounted, so a
   *  run-once guard would silently swallow every question after the first. */
  pending: { question?: string; voice?: boolean; nonce: number };
  voice: ReturnType<typeof useVoiceSession>;
  onVoiceUi: (handler: (target: string, payload: unknown) => void) => void;
}) {
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState("");
  const [result, setResult] = useState<PriceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planSnapshot, setPlanSnapshot] = useState<PlanSnapshot | null>(null);
  const [agentReply, setAgentReply] = useState<string | null>(null);
  const [answeredCount, setAnsweredCount] = useState(0);
  const [inputMode, setInputMode] = useState<"voice" | "chat">("chat");

  async function toggleVoice() {
    if (voice.isActive) {
      voice.disconnect();
      return;
    }
    try {
      await voice.connect();
    } catch (e) {
      setError(
        e instanceof Error && e.name === "NotAllowedError"
          ? "Microphone access was denied. Enable it in your browser settings to use voice."
          : e instanceof Error
            ? e.message
            : String(e),
      );
    }
  }

  // The session lives in App so it survives leaving this tab; Ask registers
  // what to do with its `ui` events, so the spoken answer and the card on
  // screen still come from the same lookup.
  useEffect(() => {
    onVoiceUi((target, payload) => {
      if (target === "estimate") {
        setResult(payload as PriceResponse);
        setPlanSnapshot(null);
        setLoading(false);
        setError(null);
        setAnsweredCount((count) => Math.min(12, count + 1));
      } else if (target === "plan") {
        // A coverage question, not a price question — show the plan instead of
        // leaving a stale estimate on screen.
        setPlanSnapshot(payload as PlanSnapshot);
        setResult(null);
        setLoading(false);
        setError(null);
      }
    });
  }, [onVoiceUi]);

  async function ask(text: string, code?: string) {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setPlanSnapshot(null);
    setAgentReply(null);
    setAsked(text);
    try {
      if (DEMO_MODE) {
        await new Promise((resolve) => window.setTimeout(resolve, 650));
        setResult(demoResult(text));
        setAnsweredCount((count) => Math.min(12, count + 1));
        return;
      }
      // A coverage question and a price question are different questions.
      // Routing both to the price lookup made "what's my deductible?" fail to
      // resolve to a billing code, which is a confusing way to answer it.
      if (!code && isPlanQuestion(text)) {
        const evidence = (await api.planSummary(categoryFor(text))) as PlanSnapshot;
        setPlanSnapshot(evidence);
        setAgentReply((await api.agentChat(text, evidence)).reply);
        return;
      }
      const evidence = await api.price(text, code);
      setResult(evidence);
      setAgentReply((await api.agentChat(text, evidence)).reply);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  // Keyed on the nonce rather than run-once: this tab stays mounted, so a ref
  // guard would make every question after the first do nothing.
  const lastNonce = useRef(0);
  useEffect(() => {
    if (pending.nonce === lastNonce.current) return;
    lastNonce.current = pending.nonce;
    if (pending.question) {
      setQ(pending.question);
      void ask(pending.question);
    } else if (pending.voice) {
      void voice.connect().catch((e) =>
        setError(
          e instanceof Error && e.name === "NotAllowedError"
            ? "Microphone access was denied. Enable it in your browser settings to use voice."
            : e instanceof Error
              ? e.message
              : String(e),
        ),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending.nonce]);


  return (
    // viewport-fit=cover means the WebView extends under the Dynamic Island,
    // so the top inset has to be added back explicitly.
    <div className="ask-ocean mx-auto w-full max-w-md px-5 pb-52 pt-[calc(env(safe-area-inset-top)+1rem)]">
      <DiveScene
        answered={answeredCount}
        active={voice.isActive}
        loading={loading}
        hasAnswer={Boolean(result || planSnapshot)}
        mode={inputMode}
        voiceStatus={voice.status}
        onMode={setInputMode}
        onVoice={() => void toggleVoice()}
      />
      {!planConfigured && (
        <div className="mb-5 flex gap-3 rounded-[var(--radius-sm)] border border-warning/30 bg-warning/10 p-3">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
          <p className="text-sm text-foreground">
            Add your plan details to see what <em>you</em> pay, not just the hospital's rate.
          </p>
        </div>
      )}

      {!result && !planSnapshot && !loading && (
        <div className="mb-6 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => {
                setQ(s);
                ask(s);
              }}
              className="rounded-full border border-border bg-card px-3.5 py-1.5 text-sm text-foreground transition-colors hover:bg-secondary"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-3 py-10 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
          <span className="text-sm">Looking up published rates…</span>
        </div>
      )}

      {error && (
        <div className="rounded-[var(--radius-sm)] border border-destructive/30 bg-destructive/10 p-4 text-sm text-foreground">
          {error}
        </div>
      )}

      {agentReply && (
        <div className="mb-5 rounded-[var(--radius-sm)] border border-border bg-card p-4 text-sm text-foreground">
          <p className="mb-1 font-semibold">Hermes</p>
          <p>{agentReply}</p>
        </div>
      )}


      {voice.transcript.length > 0 && (
        <section className="mb-5 space-y-2" aria-live="polite">
          {voice.transcript.slice(-4).map((t) => (
            <p
              key={`${t.role}-${t.at}`}
              className={
                t.role === "user"
                  ? "ml-auto max-w-[85%] rounded-[var(--radius-sm)] bg-secondary px-3 py-2 text-sm text-secondary-foreground"
                  : "max-w-[90%] text-sm leading-relaxed text-foreground"
              }
            >
              {t.text}
            </p>
          ))}
        </section>
      )}

      {planSnapshot && !loading && (
        <div className="mb-5">
          <PlanCard plan={planSnapshot} />
        </div>
      )}

      {result && !loading && <Result result={result} asked={asked} onPick={ask} />}

      {inputMode === "chat" && (
        <Composer
          value={q}
          onChange={setQ}
          onSubmit={() => ask(q)}
          voice={voice}
          onVoiceError={setError}
        />
      )}
    </div>
  );

  function Result({
    result,
    asked,
    onPick,
  }: {
    result: PriceResponse;
    asked: string;
    onPick: (t: string, code?: string) => void;
  }) {
    // Ambiguous query: offer the candidates rather than pricing a guess.
    if (result.needs_confirmation) {
      return (
        <section>
          <p className="mb-3 text-sm text-muted-foreground">{result.message}</p>
          <div className="space-y-2">
            {result.candidates?.map((c) => (
              <button
                key={c.code}
                onClick={() => onPick(asked, c.code)}
                className="w-full rounded-[var(--radius-sm)] border border-border bg-card p-3 text-left transition-colors hover:bg-secondary"
              >
                <p className="text-sm font-medium text-foreground">{c.description}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {c.code_type} {c.code}
                </p>
              </button>
            ))}
          </div>
        </section>
      );
    }

    if (!result.resolved) {
      return (
        <div className="rounded-[var(--radius-lg)] border border-border bg-card p-5">
          <p className="text-sm text-foreground">{result.message}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            ABYSS covers {hospitalCount || "dozens of"} loaded hospitals. Try naming the
            procedure, or enter its billing code directly.
          </p>
        </div>
      );
    }

    // The code exists but every hospital publishes it as a formula. Say so
    // plainly — abstaining is the honest answer, not an error state.
    if (result.hospitals.length === 0) {
      return (
        <div className="rounded-[var(--radius-lg)] border border-border bg-card p-5">
          <h2 className="font-display text-lg font-semibold text-foreground">
            No dollar amount published
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{result.message}</p>
          <p className="mt-3 text-xs text-muted-foreground">
            {result.resolved.code_type} {result.resolved.code}
            {result.formula_priced_rows
              ? ` · ${result.formula_priced_rows.toLocaleString()} contract rows carry a formula instead of a price`
              : ""}
          </p>
        </div>
      );
    }

    return (
      <section>
        <div className="mb-4">
          <p className="text-sm text-muted-foreground">
            {result.resolved.description}
            <span className="ml-1 text-xs">
              ({result.resolved.code_type} {result.resolved.code})
            </span>
          </p>
          {result.cash_prices && result.cash_prices.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              Cash price without insurance: {money(result.cash_prices[0].low)}–
              {money(result.cash_prices[result.cash_prices.length - 1].high)}
            </p>
          )}
        </div>

        <div className="space-y-4">
          {result.hospitals.map((h, i) => (
            <EstimateCard key={h.hospital_id} price={h} rank={i} onBooked={onBooked} />
          ))}
        </div>

        {result.hospitals.length > 1 && (
          <p className="mt-4 text-center text-sm text-muted-foreground">
            Choosing {result.hospitals[0].hospital} over{" "}
            {result.hospitals[result.hospitals.length - 1].hospital} could save you{" "}
            <strong className="text-foreground">
              {money(
                result.hospitals[result.hospitals.length - 1].estimate.expected -
                  result.hospitals[0].estimate.expected,
              )}
            </strong>
            .
          </p>
        )}
      </section>
    );
  }
}

function DiveScene({
  answered,
  active,
  loading,
  hasAnswer,
  mode,
  voiceStatus,
  onMode,
  onVoice,
}: {
  answered: number;
  active: boolean;
  loading: boolean;
  hasAnswer: boolean;
  mode: "voice" | "chat";
  voiceStatus: string;
  onMode: (mode: "voice" | "chat") => void;
  onVoice: () => void;
}) {
  const pose = loading ? "dive" : hasAnswer ? "discover" : active ? "swim" : "surface";
  const depth = Math.min(100, answered * 12);
  const poseSrc = `/mascot/full-body/v2/abyss-full-${pose === "swim" ? "discover" : pose}.png`;
  return (
    <section className="dive-scene" style={{ "--dive-depth": `${depth * 1.6}px` } as React.CSSProperties}>
      <header className="dive-scene__header"><span className="dive-scene__badge">S</span><strong>ABYSS</strong></header>
      <div className="dive-scene__modes" role="tablist" aria-label="Choose how to ask">
        <button className={mode === "voice" ? "is-active" : ""} onClick={() => onMode("voice")}>Voice</button>
        <button className={mode === "chat" ? "is-active" : ""} onClick={() => onMode("chat")}>Chat</button>
      </div>
      <img className={`dive-abyss dive-abyss--${pose}`} src={poseSrc} alt="ABYSS diving" />
      <div className="dive-scene__copy">
        <p className="dive-scene__eyebrow">Dive for answers</p>
        <h1>Ask ABYSS</h1>
        <p>{answered ? `${answered} answer${answered === 1 ? "" : "s"} found · ${depth}% explored` : "Every answer takes you a little deeper."}</p>
      </div>
      <div className="dive-scene__depth" aria-label={`${depth}% ocean depth explored`}>
        <span style={{ height: `${depth}%` }} />
      </div>
      {mode === "voice" && (
        <div className="dive-voice">
          <button className={active ? "dive-voice__orb is-live" : "dive-voice__orb"} onClick={onVoice} aria-label={active ? "Stop talking to ABYSS" : "Talk to ABYSS"}>
            {active ? <Square aria-hidden /> : <Mic aria-hidden />}
          </button>
          {active && (
            <button
              type="button"
              onClick={onVoice}
              className="mt-3 rounded-full border border-destructive px-5 py-2 text-sm font-semibold text-destructive"
              aria-label="Stop listening"
            >
              Stop listening
            </button>
          )}
          <h2>{active ? "I’m listening. Ask me naturally." : "Tap to ask anything about healthcare costs."}</h2>
          <p>{active ? VOICE_LABEL[voiceStatus as keyof typeof VOICE_LABEL] : "Ready when you are"}</p>
          <button className="dive-voice__chat" onClick={() => onMode("chat")}>or type a question</button>
        </div>
      )}
    </section>
  );
}

/** Fixed composer. The mic remains prominent while typed Hermes chat is the default.
 *  leads with voice. */
export function Composer({
  value,
  onChange,
  onSubmit,
  voice,
  onVoiceError,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  voice: ReturnType<typeof useVoiceSession>;
  onVoiceError: (m: string) => void;
}) {
  const active = voice.isActive;

  async function toggleVoice() {
    if (active) {
      voice.disconnect();
      return;
    }
    try {
      await voice.connect();
    } catch (e) {
      onVoiceError(
        e instanceof Error && e.name === "NotAllowedError"
          ? "Microphone access was denied. Enable it in your browser settings to use voice."
          : e instanceof Error
            ? e.message
            : String(e),
      );
    }
  }

  return (
    // Sits above the tab bar, which absorbs the bottom safe-area inset.
    <div className="fixed inset-x-0 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-10 border-t border-border bg-background/95 backdrop-blur">
      {active && (
        <div className="mx-auto flex w-full max-w-md items-center gap-3 px-5 pt-3">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              voice.status === "speaking" ? "bg-accent" : "animate-pulse bg-primary"
            }`}
          />
          <span className="text-xs text-muted-foreground">{VOICE_LABEL[voice.status]}</span>
          <div className="ml-auto flex h-4 items-end gap-0.5" aria-hidden>
            {[0, 1, 2, 3, 4].map((i) => (
              <span
                key={i}
                className="w-1 rounded-full bg-primary/70 transition-[height] duration-100"
                style={{
                  height: `${Math.max(3, Math.min(16, voice.micLevel * 40 * (1 + (i % 3) * 0.35)))}px`,
                }}
              />
            ))}
          </div>
        </div>
      )}
      <div className="mx-auto flex w-full max-w-md items-center gap-2 px-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] pt-4">
        <div className="flex flex-1 items-center rounded-full border border-input bg-card px-4 py-2.5">
          <input
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSubmit()}
            placeholder="Ask about a procedure…"
            aria-label="Ask about a procedure"
            className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
        </div>
        <button
          onClick={onSubmit}
          disabled={!value.trim()}
          aria-label="Ask"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity disabled:opacity-40"
        >
          <ArrowUp className="h-5 w-5" aria-hidden />
        </button>
        <button
          onClick={toggleVoice}
          disabled={voice.status === "connecting"}
          aria-label={active ? "Stop voice session" : "Start voice session"}
          aria-pressed={active}
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors disabled:opacity-50 ${
            active
              ? "bg-accent text-accent-foreground"
              : "border border-border bg-card text-foreground"
          }`}
        >
          {active ? (
            <Square className="h-4 w-4 fill-current" aria-hidden />
          ) : (
            <Mic className="h-5 w-5" aria-hidden />
          )}
        </button>
      </div>
    </div>
  );
}
