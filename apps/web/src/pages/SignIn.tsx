import { ArrowRight, Loader2 } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";

/** Sign in, or create an account.
 *
 * One screen with a mode toggle rather than two: the fields are identical, and
 * the commonest reason someone lands here is that they already have an account
 * and the app simply forgot them.
 *
 * A real <form> with a submit button, not a div and a click handler — that is
 * what gives the iOS keyboard its "Go" key and what makes password managers
 * offer to fill and then save the credentials. */
export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const creating = mode === "up";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (creating ? api.signup(email, password) : api.login(email, password));
      onSignedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-5 pb-[calc(env(safe-area-inset-bottom)+1.5rem)] pt-[calc(env(safe-area-inset-top)+1.5rem)]">
      <h1 className="font-display text-3xl font-semibold leading-tight text-foreground">
        {creating ? "Create your account" : "Welcome back"}
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        {creating
          ? "Your plan and the questions you ask are kept to your account."
          : "Sign in to pick up where you left off."}
      </p>

      <form onSubmit={submit} className="mt-7">
        <label className="block">
          <span className="text-xs text-muted-foreground">Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            className="mt-1 w-full rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2.5 text-foreground outline-none focus:ring-2 focus:ring-ring"
          />
        </label>

        <label className="mt-4 block">
          <span className="text-xs text-muted-foreground">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            // Tells a password manager to offer a new strong password when
            // creating, and the saved one when signing in.
            autoComplete={creating ? "new-password" : "current-password"}
            required
            minLength={creating ? 8 : undefined}
            className="mt-1 w-full rounded-[var(--radius-sm)] border border-input bg-background px-3 py-2.5 text-foreground outline-none focus:ring-2 focus:ring-ring"
          />
          {creating && (
            <span className="mt-1 block text-xs text-muted-foreground">
              At least 8 characters.
            </span>
          )}
        </label>

        {error && (
          <p
            role="alert"
            className="mt-4 rounded-[var(--radius-sm)] border border-destructive/30 bg-destructive/10 p-3 text-sm text-foreground"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] bg-primary px-4 py-3 font-medium text-primary-foreground disabled:opacity-60"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <>
              {creating ? "Create account" : "Sign in"}
              <ArrowRight className="h-4 w-4" aria-hidden />
            </>
          )}
        </button>
      </form>

      <button
        onClick={() => {
          setMode(creating ? "in" : "up");
          setError(null);
        }}
        className="mt-5 text-center text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        {creating ? (
          <>
            Already have an account? <span className="font-medium text-primary">Sign in</span>
          </>
        ) : (
          <>
            New to ABYSS? <span className="font-medium text-primary">Create an account</span>
          </>
        )}
      </button>
    </main>
  );
}
