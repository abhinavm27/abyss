import type { CareContextJourney } from "@/lib/api";

export function latestUnfinishedJourney(
  journeys: CareContextJourney[],
): CareContextJourney | null {
  return [...journeys]
    .filter((journey) => journey.status !== "complete" && journey.stage !== "complete")
    .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))[0] ?? null;
}
