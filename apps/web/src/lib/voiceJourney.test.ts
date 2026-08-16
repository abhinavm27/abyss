import { describe, expect, it } from "vitest";
import type { CareContextJourney } from "./api";
import { latestUnfinishedJourney } from "./voiceJourney";

const journey = (
  journeyId: string,
  status: string,
  stage: string,
  updatedAt: string,
): CareContextJourney => ({
  journey_id: journeyId,
  title: `${journeyId} care request`,
  status,
  stage,
  selected_care_path: null,
  pending_fields: [],
  pending_questions: [],
  intake_facts: {},
  updated_at: updatedAt,
});

describe("latestUnfinishedJourney", () => {
  it("offers the most recently updated unfinished journey", () => {
    expect(latestUnfinishedJourney([
      journey("older", "active", "intake", "2026-08-14T12:00:00Z"),
      journey("complete", "complete", "complete", "2026-08-16T12:00:00Z"),
      journey("newer", "active", "verify", "2026-08-15T12:00:00Z"),
    ])?.journey_id).toBe("newer");
  });

  it("returns null when every journey is complete", () => {
    expect(latestUnfinishedJourney([
      journey("complete", "complete", "complete", "2026-08-16T12:00:00Z"),
    ])).toBeNull();
  });
});
