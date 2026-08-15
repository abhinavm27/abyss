import { ChevronUp } from "lucide-react";
import { VOICE_LABEL, type VoiceStatus } from "@/hooks/useVoiceSession";

/** "A call is in progress" — shown when a voice session is live and you have
 *  navigated away from Ask.
 *
 * The session itself survives because the Ask tab is never unmounted; this bar
 * exists so you can tell it is still running and get back to it. Without it,
 * checking your deductible mid-conversation feels like the app hung up on
 * you. */
export function VoiceBar({
  status,
  micLevel,
  onReturn,
}: {
  status: VoiceStatus;
  micLevel: number;
  onReturn: () => void;
}) {
  const speaking = status === "speaking";
  return (
    <button
      onClick={onReturn}
      aria-label="Return to your conversation"
      className="fixed inset-x-0 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-10 border-t border-border bg-secondary/80 backdrop-blur transition-colors hover:bg-secondary"
    >
      <span className="mx-auto flex w-full max-w-md items-center gap-3 px-5 py-2.5">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${
            speaking ? "bg-accent" : "animate-pulse bg-primary"
          }`}
        />
        <span className="text-sm text-secondary-foreground">{VOICE_LABEL[status]}</span>

        <span className="ml-auto flex h-4 items-end gap-0.5" aria-hidden>
          {[0, 1, 2, 3, 4].map((i) => (
            <span
              key={i}
              className="w-1 rounded-full bg-primary/70 transition-[height] duration-100"
              style={{
                height: `${Math.max(3, Math.min(16, micLevel * 40 * (1 + (i % 3) * 0.35)))}px`,
              }}
            />
          ))}
        </span>
        <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      </span>
    </button>
  );
}
