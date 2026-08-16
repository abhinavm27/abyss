# VELA demo truth and fallback rules

## Working with controlled inputs

- Seeded insurance-card and referral processing
- Personal Care Twin state
- Three-plan cost comparison
- Special Enrollment eligibility gate
- Consent ledger

## Controlled or sandboxed external actions

- Provider verification through a controlled endpoint, supervised call, or clearly labeled recording
- Plan enrollment submission
- Existing-coverage transition
- Appointment booking

A sandbox receipt proves that the VELA workflow and adapter executed. It does
not prove that an insurer or provider changed a real external record.

## Never imply

- that sandbox enrollment changed real insurance
- that a sandbox booking reserved a real clinical appointment
- that an estimate is a guaranteed patient price
- that VELA made a diagnosis or recommended treatment

## Final demo state

New sandbox coverage selected, MRI sandbox booking completed, expected annual
savings quantified, and each material action visibly approved and sourced.
