import { ArrowRight, Building2, FileUp, ShoppingBag } from "lucide-react";
import { useState } from "react";
import { PlanPicker } from "@/components/PlanPicker";
import { SbcUpload } from "@/components/SbcUpload";
import { api, money, type PlanBody, type QhpPlan } from "@/lib/api";

/** Plan setup, one question per card.
 *
 * Profile-first onboarding: build the profile once, then
 * judge everything against it. Here that means every price ABYSS shows is
 * answered *for you* rather than in the abstract.
 *
 * Two paths. Linking a real marketplace plan pulls in the deductible, the
 * out-of-pocket max and — the part that matters — the per-service cost sharing,
 * so an MRI is priced by the plan's imaging rule rather than a blended average.
 * Everyone else types their benefits in. That is not a lesser fallback: most
 * people are on employer coverage, which is never published anywhere. */

type Mode = "choose" | "picker" | "sbc" | "manual" | "met";

interface Step {
  key: keyof PlanBody;
  question: string;
  hint: string;
  prefix?: string;
  suffix?: string;
  scale?: number; // display value -> stored value
  placeholder: string;
}

const MANUAL_STEPS: Step[] = [
  {
    key: "deductible",
    question: "What's your annual deductible?",
    hint: "The amount you pay yourself before your plan starts sharing costs. It's on your insurance card or member portal.",
    prefix: "$",
    placeholder: "2000",
  },
  {
    key: "deductible_met",
    question: "How much of it have you met this year?",
    hint: "Your member portal calls this 'deductible applied' or 'year-to-date'. A rough figure is fine.",
    prefix: "$",
    placeholder: "500",
  },
  {
    key: "coinsurance_pct",
    question: "What's your coinsurance?",
    hint: "The share you pay after the deductible is met — commonly 10, 20 or 30 percent.",
    suffix: "%",
    scale: 0.01,
    placeholder: "20",
  },
  {
    key: "oop_max",
    question: "What's your out-of-pocket maximum?",
    hint: "Once you hit this, your plan pays everything else for the year.",
    prefix: "$",
    placeholder: "8000",
  },
  {
    key: "oop_met",
    question: "How much have you paid out of pocket so far?",
    hint: "Counts toward that maximum. Leave it at zero if you're not sure.",
    prefix: "$",
    placeholder: "0",
  },
];

// A linked plan supplies everything except how much of it you have already used.
const MET_STEPS: Step[] = [MANUAL_STEPS[1], MANUAL_STEPS[4]];

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<Mode>("choose");
  const [linked, setLinked] = useState<QhpPlan | null>(null);
  const [step, setStep] = useState(0);
  const [values, setValues] = useState<Record<string, number>>({});
  const [raw, setRaw] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const steps = mode === "met" ? MET_STEPS : MANUAL_STEPS;
  const current = steps[step];
  const isLast = step === steps.length - 1;

  async function save(merged: Record<string, number>) {
    setSaving(true);
    setError(null);
    try {
      await api.putPlan({
        label: linked ? linked.marketing_name : "My plan",
        payer_name: linked?.issuer_name ?? null,
        qhp_plan_id: linked?.plan_id ?? null,
        deductible: linked ? linked.deductible : (merged.deductible ?? 0),
        deductible_met: merged.deductible_met ?? 0,
        coinsurance_pct: merged.coinsurance_pct ?? 0,
        oop_max: linked ? linked.oop_max : (merged.oop_max ?? 0),
        oop_met: merged.oop_met ?? 0,
      });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  }

  async function next(e?: React.FormEvent) {
    e?.preventDefault();
    const entered = parseFloat(raw);
    const display = Number.isFinite(entered) ? entered : 0;
    const stored = current.scale ? display * current.scale : display;
    const merged = { ...values, [current.key]: stored };
    setValues(merged);
    setRaw("");

    if (!isLast) {
      setStep((s) => s + 1);
      return;
    }
    await save(merged);
  }

  const shell = (children: React.ReactNode) => (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-5 pb-[calc(env(safe-area-inset-bottom)+2.5rem)] pt-[calc(env(safe-area-inset-top)+2.5rem)]">
      {children}
      <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
        Stored only on this device. ABYSS is informational and is not insurance advice or a
        guarantee of coverage.
      </p>
    </main>
  );

  if (mode === "choose") {
    return shell(
      <div className="rounded-[var(--radius-lg)] border border-border bg-card p-6 shadow-sm">
        <h1 className="font-display text-2xl font-semibold leading-snug text-foreground">
          How do you get your health insurance?
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          If you bought it on the marketplace, ABYSS can look up exactly what your plan charges for
          each kind of care.
        </p>

        <button
          onClick={() => setMode("picker")}
          className="mt-6 flex w-full items-start gap-3 rounded-[var(--radius-sm)] border border-border bg-background p-4 text-left transition-colors hover:bg-secondary"
        >
          <ShoppingBag className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
          <span>
            <span className="block text-sm font-medium text-foreground">
              I bought it on the marketplace
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              healthcare.gov — most accurate estimates
            </span>
          </span>
        </button>

        <button
          onClick={() => setMode("sbc")}
          className="mt-3 flex w-full items-start gap-3 rounded-[var(--radius-sm)] border border-border bg-background p-4 text-left transition-colors hover:bg-secondary"
        >
          <FileUp className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
          <span>
            <span className="block text-sm font-medium text-foreground">
              Through my employer — I have the documents
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Upload your Summary of Benefits and Coverage PDF
            </span>
          </span>
        </button>

        <button
          onClick={() => setMode("manual")}
          className="mt-3 flex w-full items-start gap-3 rounded-[var(--radius-sm)] border border-border bg-background p-4 text-left transition-colors hover:bg-secondary"
        >
          <Building2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
          <span>
            <span className="block text-sm font-medium text-foreground">
              I'll type in my benefits
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Deductible and coinsurance from your insurance card
            </span>
          </span>
        </button>
      </div>,
    );
  }

  if (mode === "sbc") {
    return shell(<SbcUpload onBack={() => setMode("choose")} onDone={onDone} />);
  }

  if (mode === "picker") {
    return shell(
      <PlanPicker
        onBack={() => setMode("choose")}
        onSelect={(plan) => {
          setLinked(plan);
          setMode("met");
          setStep(0);
          setValues({});
          setRaw("");
        }}
      />,
    );
  }

  return shell(
    <>
      <div className="mb-6">
        <div
          className="flex gap-1.5"
          role="progressbar"
          aria-valuenow={step + 1}
          aria-valuemax={steps.length}
        >
          {steps.map((s, i) => (
            <span
              key={s.key}
              className={`h-1 flex-1 rounded-full transition-colors ${
                i <= step ? "bg-primary" : "bg-border"
              }`}
            />
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Step {step + 1} of {steps.length}
        </p>
      </div>

      {linked && (
        <div className="mb-4 rounded-[var(--radius-sm)] border border-border bg-secondary/50 p-3">
          <p className="text-sm font-medium text-foreground">{linked.marketing_name}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {money(linked.deductible)} deductible · {money(linked.oop_max)} out-of-pocket max ·
            per-service costs loaded
          </p>
        </div>
      )}

      {/* A real form, so Enter on a desktop keyboard and "Go" on the iOS
          keyboard both advance the step without a keydown handler. */}
      <form
        onSubmit={next}
        className="rounded-[var(--radius-lg)] border border-border bg-card p-6 shadow-sm"
      >
        <h1 className="font-display text-2xl font-semibold leading-snug text-foreground">
          {current.question}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{current.hint}</p>

        <div className="mt-6 flex items-center gap-2 rounded-[var(--radius-sm)] border border-input bg-background px-4 py-3 focus-within:ring-2 focus-within:ring-ring">
          {current.prefix && <span className="text-lg text-muted-foreground">{current.prefix}</span>}
          <input
            autoFocus
            type="number"
            inputMode="decimal"
            value={raw}
            placeholder={current.placeholder}
            onChange={(e) => setRaw(e.target.value)}
            className="w-full bg-transparent font-display text-2xl text-foreground outline-none placeholder:text-muted-foreground/50"
            aria-label={current.question}
          />
          {current.suffix && <span className="text-lg text-muted-foreground">{current.suffix}</span>}
        </div>

        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

        <button
          type="submit"
          disabled={saving}
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] bg-primary px-4 py-3 font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {saving ? "Saving..." : isLast ? "Finish" : "Continue"}
          {!saving && <ArrowRight className="h-4 w-4" aria-hidden />}
        </button>

        <button
          type="button"
          onClick={() => next()}
          className="mt-2 w-full py-2 text-sm text-muted-foreground underline underline-offset-2"
        >
          Skip — I don't know this one
        </button>
      </form>
    </>,
  );
}
