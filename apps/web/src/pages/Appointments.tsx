import { ArrowLeft, CalendarCheck, Loader2, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, money, publishedOn, type Appointment } from "@/lib/api";

/** Appointments the member booked themselves.
 *
 * ABYSS has no scheduling integration. An earlier version generated placeholder
 * times labelled "sample availability", which was the one place in the app that
 * pretended — it was removed rather than dressed up.
 *
 * What is honestly useful is the other half of the problem: you call the
 * hospital, you agree a date, and the estimate you were looking at disappears.
 * This keeps it, attached to the appointment. */
export function Appointments({
  dataVersion,
  onBack,
  onChanged,
}: {
  dataVersion: number;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<Appointment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ description: "", booked_for: "", estimated_cost: "" });

  async function refresh() {
    const r = await api.appointments();
    setItems(r.appointments);
  }

  useEffect(() => {
    void refresh().catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataVersion]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!form.description.trim()) return;
    try {
      await api.addAppointment({
        description: form.description.trim(),
        booked_for: form.booked_for || null,
        estimated_cost: form.estimated_cost ? parseFloat(form.estimated_cost) : null,
      });
      setForm({ description: "", booked_for: "", estimated_cost: "" });
      setAdding(false);
      await refresh();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function remove(id: number) {
    await api.removeAppointment(id).catch(() => {});
    await refresh();
    onChanged();
  }

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

      <h1 className="font-display text-2xl font-semibold text-foreground">Appointments</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        ABYSS can't book for you — hospitals don't offer a way to. What it can do is hold on to
        what you arranged and what it should cost, so the estimate doesn't vanish after the call.
      </p>

      {error && (
        <p className="mt-4 rounded-[var(--radius-sm)] border border-destructive/30 bg-destructive/10 p-3 text-sm text-foreground">
          {error}
        </p>
      )}

      {!items && !error && (
        <div className="flex items-center gap-3 py-10 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
          <span className="text-sm">Loading…</span>
        </div>
      )}

      {items && items.length === 0 && !adding && (
        <div className="mt-6 rounded-[var(--radius-lg)] border border-border bg-card p-5 text-center">
          <CalendarCheck className="mx-auto h-8 w-8 text-primary" aria-hidden />
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            Nothing recorded yet. After you price something, "I booked this" on the estimate
            keeps it here.
          </p>
        </div>
      )}

      {items && items.length > 0 && (
        <ul className="mt-5 space-y-2">
          {items.map((a) => (
            <li
              key={a.id}
              className="flex items-start gap-3 rounded-[var(--radius-sm)] border border-border bg-card p-3"
            >
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium leading-snug text-foreground">
                  {a.description || a.code}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                  {[
                    a.hospital,
                    a.booked_for ? publishedOn(a.booked_for) : "no date yet",
                    a.estimated_cost != null ? `about ${money(a.estimated_cost)}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                {a.note && (
                  <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                    {a.note}
                  </span>
                )}
              </span>
              <button
                onClick={() => void remove(a.id)}
                aria-label={`Remove ${a.description || "appointment"}`}
                className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <form onSubmit={add} className="mt-5 rounded-[var(--radius-sm)] border border-border p-4">
          <label className="block">
            <span className="text-xs text-muted-foreground">What is it?</span>
            <input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Knee MRI at Mass General"
              required
              className="mt-1 w-full rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs text-muted-foreground">Date</span>
              <input
                type="date"
                value={form.booked_for}
                onChange={(e) => setForm({ ...form, booked_for: e.target.value })}
                className="mt-1 w-full rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
            <label className="block">
              <span className="text-xs text-muted-foreground">Expected cost</span>
              <input
                type="number"
                inputMode="decimal"
                value={form.estimated_cost}
                onChange={(e) => setForm({ ...form, estimated_cost: e.target.value })}
                className="mt-1 w-full rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              type="submit"
              className="flex-1 rounded-[var(--radius-sm)] bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="rounded-[var(--radius-sm)] border border-border px-4 py-2.5 text-sm text-foreground"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        items && (
          <button
            onClick={() => setAdding(true)}
            className="mt-5 w-full rounded-[var(--radius-sm)] border border-border bg-card px-4 py-3 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
          >
            Record an appointment
          </button>
        )
      )}
    </main>
  );
}
