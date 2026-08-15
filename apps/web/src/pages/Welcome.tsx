import { ArrowRight, FileText, Lock, User } from "lucide-react";

/** The first thing anyone sees.
 *
 * Before this existed, a new user's opening screen was the question "How do you
 * get your health insurance?" — a form about the most stressful topic in their
 * life, with no idea yet what this app is or why its numbers should be trusted.
 *
 * The three points below are deliberately facts rather than promises. In a
 * product whose entire claim is that it doesn't guess, the welcome screen is the
 * first place that claim has to hold. */

const REASSURANCES = [
  {
    icon: FileText,
    title: "Real published prices",
    body: "Hospitals are required by law to publish what they charge. ABYSS reads those files directly.",
  },
  {
    icon: User,
    title: "Your plan, your number",
    body: "Answers account for your deductible and what your plan covers — not a national average.",
  },
  {
    icon: Lock,
    // This said "stays on your device — nothing is uploaded" while ABYSS was
    // single-user with a local database. Accounts made that untrue, and a
    // privacy claim that quietly stops holding is worse than never making it.
    title: "Yours, and only yours",
    body: "Your plan and your questions are kept to your account. Never shared or sold.",
  },
];

export function Welcome({ onStart }: { onStart: () => void }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col px-5 pb-[calc(env(safe-area-inset-bottom)+1.5rem)] pt-[calc(env(safe-area-inset-top)+1.5rem)]">
      <div className="flex flex-1 flex-col justify-center">
        <div className="welcome-ocean" aria-hidden>
          <div className="welcome-ocean__sun" />
          <div className="welcome-ocean__abyss" />
          <div className="welcome-ocean__wave welcome-ocean__wave--one" />
          <div className="welcome-ocean__wave welcome-ocean__wave--two" />
        </div>

        <p className="mt-6 text-center text-xs font-bold uppercase tracking-[0.2em] text-primary">Voice-first price transparency</p>
        <h1 className="mt-2 text-center font-display text-4xl font-semibold leading-[0.98] text-foreground">
          Dive for answers.
        </h1>
        <p className="mx-auto mt-3 max-w-xs text-center text-sm leading-relaxed text-muted-foreground">
          ABYSS dives into hospital prices and your insurance details, then brings a clear answer back to the surface.
        </p>

        <ul className="mt-8 space-y-4">
          {REASSURANCES.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex gap-3">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary">
                <Icon className="h-4 w-4 text-primary" aria-hidden />
              </span>
              <div>
                <p className="text-sm font-medium text-foreground">{title}</p>
                <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">{body}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-8">
        <button
          onClick={onStart}
          className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] bg-primary px-4 py-3.5 font-medium text-primary-foreground transition-opacity hover:opacity-90"
        >
          Get started
          <ArrowRight className="h-4 w-4" aria-hidden />
        </button>
        <p className="mt-4 text-center text-xs leading-relaxed text-muted-foreground">
          ABYSS is informational and is not insurance advice or a guarantee of coverage.
        </p>
      </div>
    </main>
  );
}
