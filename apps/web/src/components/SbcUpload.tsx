import { AlertTriangle, ArrowLeft, Check, FileUp, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import {
  api,
  CATEGORY_LABELS,
  type SbcResult,
} from "@/lib/api";

/** Upload a Summary of Benefits and Coverage PDF.
 *
 * Every plan must publish one, which makes this the only route that works for
 * employer coverage and for states that run their own marketplace — the two
 * cases the federal plan files do not cover.
 *
 * The parsed result is always shown for review before it is saved. Carrier
 * layouts vary enough that a figure can land on the wrong row, and a plan the
 * member never checked would quietly skew every estimate afterwards. */
export function SbcUpload({
  onDone,
  onBack,
}: {
  onDone: () => void;
  onBack: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [parsing, setParsing] = useState(false);
  const [result, setResult] = useState<SbcResult | null>(null);
  const [deductible, setDeductible] = useState("");
  const [oopMax, setOopMax] = useState("");
  const [deductibleMet, setDeductibleMet] = useState("");
  const [oopMet, setOopMet] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setParsing(true);
    setError(null);
    try {
      const r = await api.parseSbc(file);
      setResult(r);
      setDeductible(r.deductible != null ? String(r.deductible) : "");
      setOopMax(r.oop_max != null ? String(r.oop_max) : "");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setParsing(false);
    }
  }

  async function save() {
    if (!result) return;
    setSaving(true);
    setError(null);
    try {
      await api.applySbc({
        label: result.plan_name || result.filename,
        deductible: parseFloat(deductible) || 0,
        deductible_met: parseFloat(deductibleMet) || 0,
        oop_max: parseFloat(oopMax) || 0,
        oop_met: parseFloat(oopMet) || 0,
        benefits: Object.entries(result.benefits).map(([category, b]) => ({
          category,
          kind: b.kind,
          amount: b.amount,
          after_deductible: b.after_deductible,
        })),
      });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  }

  const describe = (b: SbcResult["benefits"][string]) =>
    b.kind === "not_covered"
      ? "Not covered"
      : b.kind === "no_charge"
        ? "Covered in full"
        : b.kind === "copay"
          ? `$${b.amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`
          : `${Math.round(b.amount * 100)}%`;

  if (!result) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-border bg-card p-6 shadow-sm">
        <button
          onClick={onBack}
          className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back
        </button>

        <h1 className="font-display text-2xl font-semibold leading-snug text-foreground">
          Upload your plan document
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Every plan publishes a <strong className="text-foreground">Summary of Benefits and
          Coverage</strong> — a standard document, usually 6 to 8 pages. Your employer or insurer
          provides it, and it's often called the "SBC".
        </p>

        <button
          onClick={() => fileRef.current?.click()}
          disabled={parsing}
          className="mt-6 flex w-full flex-col items-center gap-2 rounded-[var(--radius-sm)] border border-dashed border-input bg-background px-4 py-8 text-center transition-colors hover:bg-secondary disabled:opacity-60"
        >
          {parsing ? (
            <>
              <Loader2 className="h-6 w-6 animate-spin text-primary" aria-hidden />
              <span className="text-sm text-muted-foreground">Reading your plan…</span>
            </>
          ) : (
            <>
              <FileUp className="h-6 w-6 text-primary" aria-hidden />
              <span className="text-sm font-medium text-foreground">Choose a PDF</span>
              <span className="text-xs text-muted-foreground">Nothing leaves your machine</span>
            </>
          )}
        </button>

        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
          }}
        />

        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      </div>
    );
  }

  const benefits = Object.entries(result.benefits).filter(([c]) => CATEGORY_LABELS[c]);

  return (
    <div className="rounded-[var(--radius-lg)] border border-border bg-card p-6 shadow-sm">
      <button
        onClick={() => setResult(null)}
        className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden /> Upload a different file
      </button>

      <h1 className="font-display text-xl font-semibold leading-snug text-foreground">
        Does this look right?
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {result.plan_name || result.filename}
        {result.plan_type ? ` · ${result.plan_type}` : ""}
        {result.coverage_period ? ` · ${result.coverage_period}` : ""}
      </p>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        Plan documents are laid out differently by every insurer, so please check these against
        your own copy before continuing.
      </p>

      {result.warnings.length > 0 && (
        <div className="mt-4 flex gap-2.5 rounded-[var(--radius-sm)] border border-warning/30 bg-warning/10 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
          <ul className="space-y-1 text-xs leading-relaxed text-foreground">
            {result.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-5 grid grid-cols-2 gap-3">
        {[
          { label: "Deductible", value: deductible, set: setDeductible },
          { label: "Out-of-pocket max", value: oopMax, set: setOopMax },
          { label: "Deductible met so far", value: deductibleMet, set: setDeductibleMet },
          { label: "Paid out of pocket so far", value: oopMet, set: setOopMet },
        ].map((f) => (
          <label key={f.label} className="block">
            <span className="text-xs text-muted-foreground">{f.label}</span>
            <span className="mt-1 flex items-center gap-1 rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2 focus-within:ring-2 focus-within:ring-ring">
              <span className="text-muted-foreground">$</span>
              <input
                type="number"
                inputMode="decimal"
                value={f.value}
                placeholder="0"
                onChange={(e) => f.set(e.target.value)}
                aria-label={f.label}
                className="w-full bg-transparent font-display text-lg text-foreground outline-none"
              />
            </span>
          </label>
        ))}
      </div>

      <p className="mt-5 text-sm font-medium text-foreground">
        What this plan charges ({benefits.length} services read)
      </p>
      <ul className="mt-2 max-h-56 space-y-2 overflow-y-auto pr-1">
        {benefits.map(([category, b]) => (
          <li key={category} className="border-b border-border/60 pb-1.5 last:border-0">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="text-muted-foreground">{CATEGORY_LABELS[category]}</span>
              <span
                className={`shrink-0 font-medium ${
                  b.kind === "not_covered" ? "text-destructive" : "text-foreground"
                }`}
              >
                {describe(b)}
                {b.after_deductible && b.kind !== "not_covered" && (
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    after deductible
                  </span>
                )}
              </span>
            </div>
            {b.source_text && (
              <p className="mt-0.5 text-xs italic text-muted-foreground/80">“{b.source_text}”</p>
            )}
          </li>
        ))}
      </ul>

      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

      <button
        onClick={save}
        disabled={saving}
        className="mt-5 flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] bg-primary px-4 py-3 font-medium text-primary-foreground disabled:opacity-60"
      >
        {saving ? "Saving…" : <><Check className="h-4 w-4" aria-hidden /> This is right — use it</>}
      </button>
    </div>
  );
}
