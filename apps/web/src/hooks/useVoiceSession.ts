import { useCallback, useEffect, useRef, useState } from "react";
import { getToken } from "@/lib/api";
import { VOICE_WS_URL } from "@/lib/voiceConfig";

/**
 * Voice session against the ABYSS NVIDIA speech bridge.
 *
 * The audio path is temporarily kept as-is because
 * every part of it is there for a reason that cost real debugging: the worklet
 * resamples to 16 kHz because iOS Safari ignores a sampleRate constraint, the
 * VAD has hysteresis so the gate doesn't chatter on pauses, the pre-roll buffer
 * stops word onsets being clipped, playback is scheduled rather than started at
 * currentTime so chunks don't stomp each other, and the mic is muted while the
 * assistant speaks because a separate AudioContext defeats echo cancellation
 * and the model otherwise hears itself and interrupts.
 */

export type VoiceStatus =
  | "idle"
  | "connecting"
  | "ready"
  | "listening"
  | "transcribing"
  | "reasoning"
  | "speaking"
  | "error";

/** What each state is called in the interface. Lives here rather than in a
 *  screen because two places now show it: the composer inside Ask, and the
 *  return bar shown when you have navigated away. */
export const VOICE_LABEL: Record<VoiceStatus, string> = {
  idle: "Start talking",
  connecting: "Connecting…",
  // Distinct from "listening": the socket is up but the mic isn't capturing yet.
  ready: "Microphone ready",
  listening: "Listening — pause when you're done",
  transcribing: "Transcribing your request…",
  reasoning: "Care Journey Agent is working…",
  speaking: "VELA is responding…",
  error: "Voice unavailable",
};

export interface TranscriptTurn {
  role: "user" | "assistant";
  text: string;
  at: number;
}

interface Options {
  onUiEvent?: (target: string, payload: unknown) => void;
  onError?: (message: string) => void;
  activeJourneyId?: string | null;
}

/** Merge transcription fragments without duplicating an already-rendered turn. */
export function mergeTranscriptFragment(prevText: string, nextText: string): string {
  const a = prevText.trim();
  const b = nextText.trim();
  if (!b) return a;
  if (!a) return b;
  if (a.endsWith(b)) return a;
  if (a.startsWith(b)) return a;
  if (b.startsWith(a)) return b;

  // A streaming transcription and its corrected final differ only in a small
  // middle, sharing a long prefix AND suffix. When the shared ends cover most
  // of the utterance, keep the longer one instead of concatenating near-dupes.
  const limit = Math.min(a.length, b.length);
  let prefix = 0;
  while (prefix < limit && a[prefix] === b[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < limit - prefix && a[a.length - 1 - suffix] === b[b.length - 1 - suffix]) {
    suffix += 1;
  }
  if (prefix + suffix >= limit * 0.75) {
    return a.length >= b.length ? a : b;
  }

  for (let k = limit; k > 0; k -= 1) {
    if (a.slice(-k) === b.slice(0, k)) return a + b.slice(k);
  }
  return a + (a.endsWith(" ") || b.startsWith(" ") ? "" : " ") + b;
}

const WORKLET_CODE = `
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._inputRate = sampleRate;
    this._outputRate = 16000;
    this._ratio = this._inputRate / this._outputRate;
    this._phase = 0;
    this._prev = 0;
    this._out = [];
    this._TARGET = 2048;
    this._VOICE_RMS = 0.015;
    this._SILENCE_RMS = 0.008;
    // Eight 128 ms chunks gives the speaker roughly one second to pause
    // naturally before the turn is finalized.
    this._HANGOVER_FRAMES = 8;
    this._PREBUFFER_FRAMES = 2;
    this._voiceActive = false;
    this._silenceFrames = 0;
    this._prebuffer = [];
  }
  _postChunk(chunk) { this.port.postMessage(chunk.buffer, [chunk.buffer]); }
  _postEvent(type) { this.port.postMessage({ type }); }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const curr = ch[i];
      while (this._phase < 1) {
        this._out.push(this._prev + (curr - this._prev) * this._phase);
        this._phase += this._ratio;
      }
      this._phase -= 1;
      this._prev = curr;
    }
    while (this._out.length >= this._TARGET) {
      const chunk = this._out.splice(0, this._TARGET);
      let sumSq = 0;
      for (let i = 0; i < this._TARGET; i++) sumSq += chunk[i] * chunk[i];
      const rms = Math.sqrt(sumSq / this._TARGET);
      if (this._voiceActive) {
        if (rms < this._SILENCE_RMS) {
          this._silenceFrames += 1;
          if (this._silenceFrames >= this._HANGOVER_FRAMES) {
            this._voiceActive = false;
            this._silenceFrames = 0;
            this._postEvent('speech_end');
          }
        } else { this._silenceFrames = 0; }
      } else if (rms >= this._VOICE_RMS) {
        this._voiceActive = true;
        this._silenceFrames = 0;
        this._postEvent('speech_start');
      }
      const int16 = new Int16Array(this._TARGET);
      for (let i = 0; i < this._TARGET; i++) {
        const s = chunk[i] < -1 ? -1 : chunk[i] > 1 ? 1 : chunk[i];
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      if (this._voiceActive) {
        while (this._prebuffer.length > 0) this._postChunk(this._prebuffer.shift());
        this._postChunk(int16);
      } else {
        this._prebuffer.push(int16);
        while (this._prebuffer.length > this._PREBUFFER_FRAMES) this._prebuffer.shift();
      }
    }
    return true;
  }
}
registerProcessor('pcm-processor', PCMProcessor);
`;

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

export function useVoiceSession({ onUiEvent, onError, activeJourneyId }: Options = {}) {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [transcript, setTranscript] = useState<TranscriptTurn[]>([]);
  const [micLevel, setMicLevel] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const playCtxRef = useRef<AudioContext | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  const nextPlayRef = useRef(0);
  const sourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const outRateRef = useRef(22050);
  // While the assistant speaks, drop captured frames instead of sending them.
  const mutedRef = useRef(false);
  const turnInFlightRef = useRef(false);
  const unmuteTimerRef = useRef<number | null>(null);

  const append = useCallback((role: "user" | "assistant", text: string) => {
    setTranscript((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === role) {
        const merged = mergeTranscriptFragment(last.text, text);
        if (merged === last.text) return prev;
        return [...prev.slice(0, -1), { ...last, text: merged }];
      }
      return [...prev, { role, text: text.trim(), at: Date.now() }];
    });
  }, []);

  const play = useCallback((b64: string) => {
    if (!b64 || b64.length < 4) return;
    const cleaned = b64.replace(/\s/g, "").replace(/-/g, "+").replace(/_/g, "/");
    if (!/^[A-Za-z0-9+/=]{4,}$/.test(cleaned)) return;

    let binary: string;
    try {
      binary = atob(cleaned);
    } catch {
      return;
    }
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const rate = outRateRef.current;
    if (!playCtxRef.current || playCtxRef.current.state === "closed") {
      playCtxRef.current = new AudioContext({ sampleRate: rate });
      nextPlayRef.current = 0;
      gainRef.current = null;
    }
    const ctx = playCtxRef.current;
    if (ctx.state === "suspended") void ctx.resume().catch(() => {});
    if (!gainRef.current || gainRef.current.context !== ctx) {
      const g = ctx.createGain();
      g.gain.value = 1.75;
      g.connect(ctx.destination);
      gainRef.current = g;
    }

    const sampleCount = Math.floor(bytes.byteLength / 2);
    if (sampleCount < 1) return;
    const int16 = new Int16Array(bytes.buffer, bytes.byteOffset, sampleCount);
    const buffer = ctx.createBuffer(1, int16.length, rate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < int16.length; i++) channel[i] = int16[i] / 32768;

    // Schedule after the previous chunk. Starting every chunk at currentTime
    // makes them overlap and the reply comes out garbled.
    const startAt = Math.max(ctx.currentTime, nextPlayRef.current);
    nextPlayRef.current = startAt + buffer.duration;

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(gainRef.current);
    sourcesRef.current.push(source);
    source.onended = () => {
      sourcesRef.current = sourcesRef.current.filter((s) => s !== source);
    };
    source.start(startAt);

    mutedRef.current = true;
    setStatus("speaking");
    if (unmuteTimerRef.current) window.clearTimeout(unmuteTimerRef.current);
    const msUntilDone = Math.max(0, (nextPlayRef.current - ctx.currentTime) * 1000) + 250;
    unmuteTimerRef.current = window.setTimeout(() => {
      mutedRef.current = false;
      turnInFlightRef.current = false;
      setStatus((s) => (s === "speaking" ? "listening" : s));
    }, msUntilDone);
  }, []);

  const stopPlayback = useCallback(() => {
    sourcesRef.current.forEach((s) => {
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    });
    sourcesRef.current = [];
    nextPlayRef.current = 0;
  }, []);

  const disconnect = useCallback(() => {
    if (unmuteTimerRef.current) window.clearTimeout(unmuteTimerRef.current);
    stopPlayback();
    workletRef.current?.disconnect();
    workletRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void micCtxRef.current?.close().catch(() => {});
    micCtxRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    mutedRef.current = false;
    turnInFlightRef.current = false;
    setMicLevel(0);
    setStatus("idle");
  }, [stopPlayback]);

  const connect = useCallback(async () => {
    if (wsRef.current) return;
    setStatus("connecting");

    const ws = new WebSocket(VOICE_WS_URL);
    wsRef.current = ws;

    ws.onmessage = (evt) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(evt.data as string);
      } catch {
        return;
      }
      switch (msg.type) {
        case "ready":
          if (typeof msg.output_sample_rate === "number") {
            outRateRef.current = msg.output_sample_rate;
          }
          setStatus("ready");
          break;
        case "listening":
          if (!turnInFlightRef.current) setStatus("listening");
          break;
        case "processing":
          if (msg.stage === "transcribing") setStatus("transcribing");
          else if (msg.stage === "reasoning") setStatus("reasoning");
          else if (msg.stage === "speaking") setStatus("speaking");
          break;
        case "transcript":
          append(msg.role as "user" | "assistant", String(msg.text ?? ""));
          break;
        case "audio":
          play(String(msg.data ?? ""));
          break;
        case "ui":
          onUiEvent?.(String(msg.target ?? ""), msg.payload);
          break;
        case "interrupted":
          stopPlayback();
          mutedRef.current = false;
          turnInFlightRef.current = false;
          setStatus("listening");
          break;
        case "turn_complete":
          // Magpie audio chunks are scheduled ahead of currentTime. Playback's
          // completion timer reopens the microphone when audio exists; a
          // text-only response can reopen it immediately.
          if (sourcesRef.current.length === 0) {
            mutedRef.current = false;
            turnInFlightRef.current = false;
            setStatus("listening");
          }
          break;
        case "turn_error":
          // The server rejected one utterance safely (for example, malformed
          // model JSON). Keep the authenticated voice session open so the user
          // can repeat or clarify instead of starting over.
          mutedRef.current = false;
          turnInFlightRef.current = false;
          setMicLevel(0);
          setStatus("listening");
          onError?.(String(msg.message ?? "That turn could not be processed. Please try again."));
          break;
        case "error":
          setStatus("error");
          onError?.(String(msg.message ?? "voice session failed"));
          break;
      }
    };

    ws.onerror = () => {
      setStatus("error");
      onError?.("Could not reach the voice service.");
    };
    ws.onclose = () => {
      if (wsRef.current === ws) disconnect();
    };

    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      window.setTimeout(() => reject(new Error("voice connect timed out")), 10_000);
    });

    // The session token goes in the first frame rather than the URL: a token in
    // a query string is written to server access logs and browser history, and
    // a WebSocket handshake cannot carry an Authorization header.
    ws.send(JSON.stringify({
      type: "auth",
      token: getToken(),
      active_journey_id: activeJourneyId ?? undefined,
    }));

    // If the microphone is unavailable the whole session is torn down. Leaving
    // the socket open would leave the UI saying "Listening" when nothing is
    // being captured — worse than a clean failure.
    try {
      // No sampleRate hint — iOS Safari and most mobile Chromes silently ignore
      // it. The worklet resamples to 16 kHz instead.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;

      const ctx = new AudioContext();
      micCtxRef.current = ctx;
      if (ctx.state === "suspended") await ctx.resume();

      const blob = new Blob([WORKLET_CODE], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      await ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);

      const node = new AudioWorkletNode(ctx, "pcm-processor");
      workletRef.current = node;
      node.port.onmessage = (e: MessageEvent<ArrayBuffer | { type: string }>) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        if (!(e.data instanceof ArrayBuffer)) {
          if (e.data.type === "speech_start" && !turnInFlightRef.current) {
            ws.send(JSON.stringify({ type: "speech_start" }));
            setStatus("listening");
          } else if (e.data.type === "speech_end" && !turnInFlightRef.current) {
            ws.send(JSON.stringify({ type: "speech_end" }));
            // Finalize this turn immediately. The worklet may continue running,
            // but no more microphone frames leave the browser until the
            // backend response has completed.
            turnInFlightRef.current = true;
            mutedRef.current = true;
            setMicLevel(0);
            setStatus("transcribing");
          }
          return;
        }
        if (mutedRef.current || turnInFlightRef.current) return;
        const pcm = new Int16Array(e.data);
        let peak = 0;
        for (let i = 0; i < pcm.length; i += 32) {
          const v = Math.abs(pcm[i]) / 32768;
          if (v > peak) peak = v;
        }
        setMicLevel(peak);
        ws.send(JSON.stringify({ type: "audio", data: toBase64(e.data) }));
      };

      ctx.createMediaStreamSource(stream).connect(node);
      // The worklet posts frames rather than producing output, but Chrome stops
      // pulling from a node that isn't connected to anything downstream.
      const silent = ctx.createGain();
      silent.gain.value = 0;
      node.connect(silent).connect(ctx.destination);

      setStatus("listening");
    } catch (err) {
      disconnect();
      setStatus("error");
      throw err;
    }
  }, [activeJourneyId, append, disconnect, onError, onUiEvent, play, stopPlayback]);

  const sendText = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "text", text }));
      append("user", text);
    }
  }, [append]);

  useEffect(() => () => disconnect(), [disconnect]);

  return {
    status,
    transcript,
    micLevel,
    connect,
    disconnect,
    sendText,
    isActive: status !== "idle" && status !== "error",
    isListening: status === "listening",
    isProcessing: status === "transcribing" || status === "reasoning" || status === "speaking",
  };
}
