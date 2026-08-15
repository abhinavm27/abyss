import { useState } from "react";
import { VelaExperience } from "@/vela/VelaExperience";
import { api, getToken } from "@/lib/api";
import "@/vela/vela.css";

export default function App() {
  const liveConfigured = import.meta.env.VITE_LIVE_MODE === "true";
  const [authenticated, setAuthenticated] = useState(() => Boolean(getToken()));
  if (!liveConfigured || authenticated) return <VelaExperience />;
  return <VelaAuth onAuthenticated={() => setAuthenticated(true)} />;
}

function VelaAuth({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [create, setCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    setBusy(true); setError("");
    try { if (create) await api.signup(email, password); else await api.login(email, password); onAuthenticated(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "VELA could not sign you in."); }
    finally { setBusy(false); }
  };
  return <main className="vela-auth"><section><span className="vela-logo">VELA</span><p>Your clearest path to care.</p><h1>{create ? "Create your secure account." : "Welcome back."}</h1><form onSubmit={(event) => { event.preventDefault(); void submit(); }}><label>Email<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>Password<input type="password" autoComplete={create ? "new-password" : "current-password"} minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <div role="alert">{error}</div>}<button disabled={busy}>{busy ? "Connecting…" : create ? "Create account" : "Continue securely"}</button></form><button className="vela-auth-switch" onClick={() => setCreate((value) => !value)}>{create ? "I already have an account" : "Create an account"}</button><small>Your health information stays private and every consequential action still requires explicit approval.</small></section></main>;
}
