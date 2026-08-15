# Project Memory

Project-specific decisions, constraints, style rules, and lessons.

## Project Identity

- Title: ABYSS Care Journey Demo
- Audience: judges and engineering team
- Promise: show a real permissioned journey reaching completion
- Target duration: 64 seconds
- Platform: MP4 walkthrough

## Style Decisions

- Visual language: authentic UI captures on mist background
- Voice identity: calm technical narrator
- Animation principles: movement only to reveal state progression
- Code display rules: no code; product behavior is the evidence

## Current Decisions

- Use synthetic demo data only.
- Keep deterministic decisions visually distinct from model explanations.
- Use API port 8011 to avoid the separately managed service on port 8010.
- Deliver a silent walkthrough now; narration can be added after HeyGen reauthentication.

## Rejected Ideas

- No simulated production enrollment or real patient data.
