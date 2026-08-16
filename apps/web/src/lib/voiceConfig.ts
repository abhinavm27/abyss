// Voice WebSocket configuration.
// Same-origin in dev — Vite proxies /ws to the backend. Capacitor serves the
// app from capacitor://localhost, so VITE_WS_URL points at the backend there.

const isSecure = typeof window !== "undefined" && window.location.protocol === "https:";
const wsProtocol = isSecure ? "wss:" : "ws:";
const host = typeof window !== "undefined" ? window.location.host : "localhost:8010";

export const VOICE_WS_URL = import.meta.env.VITE_WS_URL || `${wsProtocol}//${host}/ws`;
export const SECURE_APP_URL = import.meta.env.VITE_SECURE_APP_URL || "";

// Parakeet receives 16 kHz input. Magpie's output rate is announced in the
// `ready` frame, so the initial value is only a safe pre-handshake default.
export const AUDIO_INPUT_SAMPLE_RATE = 16000;
export const AUDIO_OUTPUT_SAMPLE_RATE = 22050;
export const AUDIO_CHANNELS = 1;
