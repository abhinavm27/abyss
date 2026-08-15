// Voice WebSocket configuration.
// Same-origin in dev — Vite proxies /ws to the backend. Capacitor serves the
// app from capacitor://localhost, so VITE_WS_URL points at the backend there.

const isSecure = typeof window !== "undefined" && window.location.protocol === "https:";
const wsProtocol = isSecure ? "wss:" : "ws:";
const host = typeof window !== "undefined" ? window.location.host : "localhost:8010";

export const VOICE_WS_URL = import.meta.env.VITE_WS_URL || `${wsProtocol}//${host}/ws`;

// Must match the backend: it sends audio/pcm;rate=16000 upstream and Gemini
// Live returns 24 kHz. The output rate is also announced in the `ready` frame.
export const AUDIO_INPUT_SAMPLE_RATE = 16000;
export const AUDIO_OUTPUT_SAMPLE_RATE = 24000;
export const AUDIO_CHANNELS = 1;
