export type VoiceEnvironment = {
  isSecureContext: boolean;
  hasGetUserMedia: boolean;
  secureAppUrl?: string;
};

function errorName(error: unknown): string {
  return typeof error === "object" && error !== null && "name" in error
    ? String((error as { name?: unknown }).name ?? "")
    : "";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message.trim() : "";
}

/** Turn browser/device failures into an actionable message without confusing
 * a voice-gateway failure with a missing microphone. */
export function voiceStartErrorMessage(error: unknown, environment: VoiceEnvironment): string {
  if (!environment.isSecureContext) {
    const destination = environment.secureAppUrl?.trim();
    return destination
      ? `Your browser blocks microphone access on this HTTP address. Open the secure VELA URL: ${destination}`
      : "Your browser blocks microphone access on this HTTP address. Open VELA over HTTPS or localhost.";
  }
  if (!environment.hasGetUserMedia) {
    return "This browser does not expose microphone capture. Try Chrome or Safari and allow microphone access for VELA.";
  }

  const name = errorName(error);
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
    return "Microphone access is blocked. Allow microphone access for this site in the browser address bar, then try Voice again.";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "No microphone was found. Connect or enable a microphone, then try Voice again.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "The microphone is being used by another app or could not be opened. Close the other audio app, then try again.";
  }
  if (name === "OverconstrainedError") {
    return "The selected microphone cannot provide a compatible audio stream. Choose another input device and try again.";
  }

  const message = errorMessage(error);
  if (/voice|websocket|connect|gateway|timed out/i.test(message)) {
    return `The microphone is available, but VELA could not connect to the voice service${message ? `: ${message}` : "."}`;
  }
  return message
    ? `Voice could not start: ${message}`
    : "Voice could not start in this browser. You can continue by chat while checking the microphone settings.";
}
