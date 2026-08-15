# Bounded Script

## Script Rules

- Target duration: 64 seconds
- Target words: 135
- Voice: calm technical product narrator
- Caption style: concise, sentence case

## Scenes

### S01 - Request

Duration: 8 seconds
Words: 16
Narration: We start with a simple request: I want an MRI scan for my knee.

Visual intent: Show sign-in and the initial request entering the live GN100 UI.

### S02 - Clarification

Duration: 11 seconds
Words: 27
Narration: The Onboarding Agent extracts the request, while the Knowledge Agent identifies ambiguity and asks for service date, coverage end, and contrast.

Visual intent: Hold on the three clarification questions.

### S03 - Persistent facts

Duration: 10 seconds
Words: 24
Narration: We answer: August thirtieth, coverage ends September thirtieth, and MRI with contrast. Those facts persist in the journey ledger.

Visual intent: Reveal consent only after missing facts clear.

### S04 - Matching

Duration: 12 seconds
Words: 29
Narration: Deterministic matching ranks Washington Plan B at sixty-three hundred dollars, continuation at eighty-nine hundred, and rejects cheaper Plan A for the provider constraint.

Visual intent: Show the three ranked paths and hard failure.

### S05 - Explanation and consent

Duration: 12 seconds
Words: 27
Narration: Nemotron explains those authoritative results. Then separate consent gates protect enrollment, coverage transition, provider verification, and booking.

Visual intent: Move from explanation to accumulating receipts.

### S06 - Complete

Duration: 11 seconds
Words: 22
Narration: The sandbox journey finishes with four audit receipts. Agents assist; deterministic rules remain in control.

Visual intent: End on complete stage and four receipts.
