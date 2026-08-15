import { AlertTriangle, ArrowLeft, Check, Info, Loader2, Receipt } from "lucide-react";
import { useEffect, useState } from "react";
import { api, money, type AmountKind, type BillCheck, type Hospital } from "@/lib/api";

/** Check a bill you have already been sent.
 *
 * The rest of ABYSS answers "what will this cost?" — a question people ask
 * calmly, in advance, and rarely. This answers "was I charged the right
 * amount?", which is asked with a statement in hand, and which the published
 * rate files can actually settle.
 *
 * The screen is built around one question the member must answer first: which
 * figure they are holding. A hospital's gross charge runs several times its
 * negotiated rate, so the same number is unremarkable as one and alarming as the
 * other. Asking is the only way to be right. */
const KINDS: { id: AmountKind; label: string; hint: string }[] = [
  {
    id: "allowed",
    label: "Allowed amount",
    hint: "From your insurer's explanation of benefits — what they agreed the service costs.",
  },
  {
    id: "charged",
    label: "Total charges",
    hint: "The hospital's list price, before any insurance discount.",
  },
  {
    id: "paid",
    label: "What I owe",
    hint: "Your share after the plan paid — depends on your benefits, not just the price.",
  },
];

export function Bill({ onBack }: { onBack: () => void }) {
  const [query, setQuery] = useState("");
  const [amount, setAmount] = useState("");
  const [kind, setKind] = useState<AmountKind>("allowed");
  const [hospitalId, setHospitalId] = useState<string>("");
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BillCheck | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .hospitals()
      .then((h) => setHospitals([...h].sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => {});
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || !amount) return;
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api.checkBill({
          query: query.trim(),
          amount: parseFloat(amount),
          amount_kind: kind,
          hospital_id: hospitalId ? Number(hospitalId) : null,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const v = result?.verdict;
  const tone =
    v?.status === "above"
      ? { border: "border-warning/40", bg: "bg-warning/10", Icon: AlertTriangle, fg: "text-warning" }
      : v?.status === "below"
        ? { border: "border-border", bg: "bg-card", Icon: Info, fg: "text-muted-foreground" }
        : { border: "border-primary/40", bg: "bg-primary/5", Icon: Check, fg: "text-primary" };

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

      <h1 className="font-display text-2xl font-semibold text-foreground">Check a bill</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        Already been charged? Compare one line against what the hospital published for that same
        code.
      </p>

      <form onSubmit={submit} className="mt-6">
        <label className="block">
          <span className="text-xs text-muted-foreground">Service or billing code</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="73721, or MRI of my knee"
            required
            className="mt-1 w-full rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
          />
        </label>

        <fieldset className="mt-4">
          <legend className="text-xs text-muted-foreground">Which figure is this?</legend>
          <div className="mt-1.5 grid gap-1.5">
            {KINDS.map((k) => (
              <label
                key={k.id}
                className={`flex cursor-pointer gap-2.5 rounded-[var(--radius-sm)] border p-2.5 transition-colors ${
                  kind === k.id ? "border-primary/50 bg-primary/5" : "border-border bg-card"
                }`}
              >
                <input
                  type="radio"
                  name="kind"
                  checked={kind === k.id}
                  onChange={() => setKind(k.id)}
                  className="mt-0.5 accent-[var(--primary)]"
                />
                <span>
                  <span className="block text-sm font-medium text-foreground">{k.label}</span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                    {k.hint}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs text-muted-foreground">Amount</span>
            <span className="mt-1 flex items-center gap-1 rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2.5 focus-within:ring-2 focus-within:ring-ring">
              <span className="text-muted-foreground">$</span>
              <input
                type="number"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                required
                aria-label="Amount"
                className="w-full bg-transparent text-sm text-foreground outline-none"
              />
            </span>
          </label>
          <label className="block">
            <span className="text-xs text-muted-foreground">Hospital</span>
            <select
              value={hospitalId}
              onChange={(e) => setHospitalId(e.target.value)}
              className="mt-1 w-full rounded-[var(--radius-sm)] border border-input bg-background px-2 py-2.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Any</option>
              {hospitals.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          type="submit"
          disabled={busy}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] bg-primary px-4 py-3 font-medium text-primary-foreground disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Receipt className="h-4 w-4" aria-hidden />}
          Check it
        </button>
      </form>

      {error && (
        <p className="mt-4 rounded-[var(--radius-sm)] border border-destructive/30 bg-destructive/10 p-3 text-sm text-foreground">
          {error}
        </p>
      )}

      {result?.message && !v && (
        <p className="mt-5 rounded-[var(--radius-sm)] border border-border bg-card p-4 text-sm leading-relaxed text-muted-foreground">
          {result.message}
        </p>
      )}

      {v && result && (
        <section className={`mt-5 rounded-[var(--radius-lg)] border p-5 ${tone.border} ${tone.bg}`}>
          <div className="flex items-start gap-2.5">
            <tone.Icon className={`mt-0.5 h-5 w-5 shrink-0 ${tone.fg}`} aria-hidden />
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground">{v.headline}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{v.detail}</p>
              {v.percentile != null && (
                <p className="mt-1.5 text-xs text-foreground">
                  Higher than <span className="font-medium">{v.percentile}%</span> of published
                  rates for this code.
                </p>
              )}
            </div>
          </div>

          {result.scope_warning && (
            <p className="mt-3 rounded-[var(--radius-sm)] bg-secondary/60 p-3 text-xs leading-relaxed text-secondary-foreground">
              {result.scope_warning}
            </p>
          )}

          {result.reference && (
            <div className="mt-4 border-t border-border pt-3">
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="text-muted-foreground">You were charged</span>
                <span className="font-display text-lg text-foreground">
                  {money(result.amount ?? 0)}
                </span>
              </div>
              <div className="mt-1.5 flex items-baseline justify-between gap-3 text-sm">
                <span className="min-w-0 text-muted-foreground">
                  {result.hospital ?? "Published"} range
                </span>
                <span className="shrink-0 text-foreground">
                  {money(result.reference.low)} – {money(result.reference.high)}
                </span>
              </div>
              {v.over_by != null && (
                <p className="mt-2 text-sm font-medium text-warning">
                  {money(v.over_by)} above the highest published rate
                </p>
              )}
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                Compared against {result.reference.basis}
                {result.reference.count ? ` · ${result.reference.count} published rates` : ""}
                {result.resolved?.description ? ` · ${result.resolved.description}` : ""}
              </p>
            </div>
          )}

          {result.cash_price && (
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              This hospital's cash price for the same code is{" "}
              {result.cash_price.low === result.cash_price.high
                ? money(result.cash_price.low)
                : `${money(result.cash_price.low)} – ${money(result.cash_price.high)}`}
              .
            </p>
          )}

          {/* The honest limit of the whole feature. */}
          <p className="mt-3 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
            Negotiated rates differ legitimately between insurers, so a figure above the range is
            a reason to ask which rate was applied — not proof of a mistake.
          </p>
        </section>
      )}
    </main>
  );
}
