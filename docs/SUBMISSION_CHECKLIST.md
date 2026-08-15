# VELA submission checklist

Submission deadline: **August 16 at 11:00 AM Pacific Time**

One submission is permitted per team. This tracker records repository readiness; it does not replace the official submission form.

## Required submission fields

| Requirement | Status | Current material | Remaining action |
| --- | --- | --- | --- |
| Team name | Ready | VELA | Enter `VELA` in the form |
| Project description | Ready | README opening paragraph | Copy the approved description exactly |
| Challenge selected | Ready | Do Track rationale in README | Select `Do` in the form |
| Demo video | Not started | Runbook and core loop are defined | Finalize story, record a 3 to 5 minute live walkthrough, upload unlisted |
| Repository link | Ready after publish | `https://github.com/abhinavm27/abyss` | Publish the verified submission branch or merge it to the submitted default branch |
| Deployed URL or working screen capture | Pending | Local web application exists | Deploy the final safe demo or provide a current working capture |
| Team roster | Partially ready | All three names are in README | Confirm roles and contact information |

## README requirements

| Requirement | Status | Location | Remaining action |
| --- | --- | --- | --- |
| Quick start commands | Ready | `README.md` | Verify once more from a clean environment |
| Tech stack and architecture diagram | Ready | `README.md`, `docs/ARCHITECTURE.md` | Add final UI or deployment components if they change |
| Demo reproduction, environment variables, API keys, sample environment | Ready with private infrastructure caveat | `README.md`, `.env.example`, `docs/DEMO_RUNBOOK.md`, `docs/HERMES_CONNECTION.md` | Verify judge safe mode without private credentials |
| Datasets and synthetic data provenance | Ready | `docs/DATA_PROVENANCE.md` | Add any new external source before submission |
| Known limitations and next steps | Ready | `README.md` | Reconcile after final integration |

## Do Track evidence

| Judging signal | Existing evidence | Remaining work |
| --- | --- | --- |
| Full workflow completeness | Tested vertical slice from intake through sandbox booking | Demonstrate the same path in the final UI without a crash |
| Branching and error recovery | Tests cover ambiguity, out of network rejection, missing consent, transition prerequisites, and idempotency | Surface the most compelling branch visibly in the demo |
| Technical depth | Fact ledger, deterministic engine, bounded agents, consent state machine, adapters, and audit ledger | Show the architecture and one live audit trace in the video |
| NVIDIA ecosystem | Local Nemotron through NemoClaw and Hermes on DGX Spark | Capture proof of local inference and explain why local execution matters |
| Human value | Spoken request to cost aware care path and appointment outcome | Keep the demo centered on one understandable patient story |
| Usability | React and Capacitor application, camera and PDF ingestion paths | Replace the former ABYSS visual experience with the approved VELA identity |
| Performance | Local inference and deterministic calculation | Record real latency and, if available, memory or utilization evidence |

## Engineering verification

| Check | Current result | Final command |
| --- | --- | --- |
| Python deterministic and vertical slice tests | Passing, 31 tests | `PYTHONPATH=src python3 -m unittest discover -s tests -v` |
| Web typecheck | Passing at audit baseline | `cd apps/web && npm run typecheck` |
| Web production build | Passing at audit baseline | `cd apps/web && npm run build` |
| Secret and real data scan | Pending final pass | Review tracked files and repository history before submission |
| Clean install reproduction | Pending final pass | Execute README from a fresh clone |
| Live Hermes integration | Pending final pass | Use private tunnel and authenticated gateway only |
| Full UI journey | Pending | Complete the final VELA interface and run the golden path |

## Final submission sequence

1. Freeze features and reset the synthetic scenario.
2. Run the full test, typecheck, build, and secret scan.
3. Complete three clean end to end rehearsals.
4. Record and validate the 3 to 5 minute video.
5. Upload the video as unlisted and test it in a signed out browser.
6. Confirm the submitted repository branch contains the current README and no secrets.
7. Confirm the deployed URL or capture matches the recorded build.
8. Enter the team name, project description, Do Track, repository, video, deployment, and roster.
9. Have a second teammate review every link and claim.
10. Submit before 11:00 AM Pacific Time and save the confirmation receipt.
