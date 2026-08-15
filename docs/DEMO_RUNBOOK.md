# VELA judged demo runbook

## Purpose

This runbook reproduces one truthful end to end demonstration of VELA. It is designed for the Do Track judging criteria: a working multistep system, branching and recovery, meaningful local NVIDIA usage, a valuable human outcome, and visible proof that each sandbox action completed.

## Golden journey

A fictional Washington resident recently lost employer coverage and needs a nonemergency knee MRI. The user wants to retain a required medication and preferred physician while minimizing expected annual cost. VELA compares continuation coverage with two eligible alternatives, explains the feasible paths, requests exact approval for each consequential action, and completes a sandbox appointment workflow.

## Preconditions

- Python 3.11 or newer
- Node.js 20 or newer
- Repository dependencies installed
- The deterministic test suite passing
- Synthetic card, SBC, and referral assets ready for the demonstration
- Optional private Hermes tunnel open for the local Nemotron explanation
- No real health or insurance data on screen or in the repository

## Start the system

Terminal one:

```bash
python3 -m venv .venv
.venv/bin/pip install -e . -e 'services/api[dev]'
PYTHONPATH=src:services/api .venv/bin/uvicorn app.api:app --port 8010
```

Terminal two:

```bash
cd apps/web
npm ci
npm run dev
```

Open `http://localhost:5173`.

For local Nemotron explanations, open the private connection first as documented in [HERMES_CONNECTION.md](HERMES_CONNECTION.md). Do not expose the GN100 ports publicly and do not display the bearer token.

## Core demonstration sequence

| Step | User or system action | Evidence the judge should see |
| --- | --- | --- |
| 1 | User says they need a knee MRI and recently lost employer coverage | Voice input becomes a structured journey request |
| 2 | VELA asks for permission to process documents | Exact document processing consent is visible |
| 3 | User scans a synthetic insurance card or uploads it | Extracted card facts show source and verification state |
| 4 | User uploads a synthetic SBC and referral PDF | Benefits and procedure facts remain traceable to their documents |
| 5 | VELA detects whether the MRI description is ambiguous | Clarification appears rather than a guessed procedure code |
| 6 | The engine compares three plan and provider paths | Annual cost components, eligibility, and hard constraints are visible |
| 7 | VELA presents the recommended feasible path | Recommendation includes reasons, rejected alternatives, sources, and caveats |
| 8 | Nemotron explains the engine result | Explanation is clearly grounded in deterministic evidence |
| 9 | User approves sandbox enrollment | Exact action and scope are visible before execution |
| 10 | Enrollment adapter returns a receipt | Receipt shows sandbox status, timestamp, consent, and idempotency key |
| 11 | VELA confirms replacement effective date and first premium | Old coverage remains unchanged until both prerequisites exist |
| 12 | User separately approves coverage transition | Transition uses a distinct consent record and receipt |
| 13 | User approves the minimum provider disclosure | Controlled verification returns success or a truthful blocked state |
| 14 | User approves the proposed appointment | Sandbox booking returns a receipt |
| 15 | VELA shows the final journey summary | Savings, sources, caveats, approvals, receipts, and audit events are visible |

## Required success conditions

- The full path finishes without a crash.
- Only feasible care paths can be recommended.
- The selected result exposes its annual cost components.
- Rejected paths retain specific rejection reasons.
- No consequential adapter runs before exact consent.
- Transition does not run before replacement effective date and first premium confirmation.
- Every sandbox action produces an auditable receipt.
- The interface never claims that sandbox enrollment or booking changed a real external system.

## Recovery cases to demonstrate or mention

### Ambiguous procedure

Input: `I need a knee MRI.`

Expected behavior: VELA asks whether the study is with or without contrast. It does not silently assign a procedure code.

### Ineligible or out of network path

Expected behavior: The engine excludes the path from recommendation and shows the hard failure. Nemotron may explain the failure but cannot override it.

### Missing action consent

Expected behavior: The adapter call is rejected and the workflow remains at the current stage.

### Duplicate action request

Expected behavior: The idempotency key returns the existing sandbox receipt rather than performing the action twice.

### Hermes unavailable

Expected behavior: Deterministic comparison remains available. VELA labels the explanation as unavailable, retries within a bound, or moves to operator review. It does not call a hosted model as a hidden fallback.

## Fallback policy

A prerecorded provider verification or full journey may be used only when a live external seam is unavailable. The presenter must label the recording clearly. Deterministic results, consent checks, state transitions, receipts, and audit history should still be demonstrated from the running system.

## Claims to avoid

- Do not say VELA enrolled a person in real insurance.
- Do not say VELA canceled or changed real coverage.
- Do not say VELA reserved a real clinical appointment.
- Do not call an estimate a guaranteed price.
- Do not describe VELA as medical advice, a diagnostic system, or a licensed broker.
- Do not imply that model generated language is the source of the deterministic result.

## Final rehearsal checklist

- Run the Python test suite.
- Run the web typecheck and production build.
- Confirm only synthetic data is visible.
- Confirm the Hermes token and infrastructure credentials are hidden.
- Reset the seeded journey before each rehearsal.
- Verify every required consent screen and receipt.
- Rehearse the live path three times.
- Verify the fallback recording matches the current interface and behavior.
