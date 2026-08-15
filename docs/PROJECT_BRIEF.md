# Project brief

## Product promise

From “I need care” to “your appointment is booked” through one understandable,
permissioned workflow.

ABYSS evaluates current insurance, compares eligible alternatives, identifies the
lowest-total-cost path to care, and—with explicit consent—coordinates sandboxed
coverage enrollment, provider verification, and appointment booking.

## Controlled demo scenario

- User recently lost employer-sponsored coverage and is within a Special Enrollment Period.
- Care need is a referred, non-emergency MRI.
- Compare continuation coverage and two eligible Washington alternatives.
- Compare three imaging facilities with different network, cost, distance, and timing.
- Optimize expected annual cost while retaining a required medication and preferred physician.
- Enrollment, coverage transition, and booking are visibly sandboxed.

## Decision objective

```text
expected annual cost
  = annual premiums
  + expected out-of-pocket care
  + medication costs
  + remaining deductible exposure
```

The cheapest MRI price is not necessarily the cheapest complete healthcare path.

## Required weekend capabilities

- Insurance-card and referral extraction
- Persistent Personal Care Twin
- Three-plan deterministic comparison
- One validated Special Enrollment eligibility gate
- Consent ledger
- Provider verification call or controlled live endpoint
- Sandbox appointment booking
- Clearly labeled sandbox coverage enrollment and transition

## Out of scope

- Medical diagnosis or treatment recommendations
- Production enrollment or nationwide plan ingestion
- Unsupported price guarantees
- Cancellation before replacement coverage is effective
- More than one polished care journey

## Checkpoints

- Friday: scenario, owners, contracts, model stack, and demo script frozen
- Saturday noon: full path visible with mocked seams; DGX inference established
- Saturday night: intelligence, consent, voice, and booking integrated
- Sunday morning: feature freeze; reliability and visual clarity only
- Judging: three clean rehearsals and an identical fallback recording

