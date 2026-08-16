# VELA submission checklist

Submission deadline: **August 16 at 11:00 AM Pacific Time**

One submission is permitted per team. This tracker records repository readiness; it does not replace the official submission form.

## Required submission fields

| Requirement | Status | Current material | Remaining action |
| --- | --- | --- | --- |
| Team name | Ready | VELA | Enter `VELA` in the form |
| Project description | Ready | README opening paragraph | Copy the approved description exactly |
| Challenge selected | Ready | Do Track rationale in README | Select `Do` in the form |
| Demo video | Pending | Runbook, core loop, and deployed interface are ready | Record a 3 to 5 minute walkthrough, upload unlisted, and verify the link signed out |
| Repository link | Ready | `https://github.com/abhinavm27/abyss` on merged `main` | Enter the repository URL in the form |
| Deployed URL or working screen capture | Ready | `https://gn100-75f8.tailf05681.ts.net` (confirmed live via `/api/health` on August 16, 2026) | Verify the final deployed build immediately before submission |
| Team roster | Ready | All three names, roles, and contact details are in README | Copy the roster into the submission form |

## README requirements

| Requirement | Status | Location | Remaining action |
| --- | --- | --- | --- |
| Quick start commands | Ready | `README.md` | Reproduced from a clean checkout on August 15, 2026 |
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
| Usability | Complete VELA web and iPhone compositions, voice and chat journeys, neural care paths, camera/PDF intake, and functional workspace tabs | Rehearse the judged journey on the final deployment |
| Performance | Local inference and deterministic calculation | Record real latency and, if available, memory or utilization evidence |

## Engineering verification

| Check | Current result | Final command |
| --- | --- | --- |
| Domain and vertical-slice tests | Passing, 109 tests on August 16, 2026 | `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v` |
| API service tests | Passing, 17 tests on August 16, 2026 | `PYTHONPATH=src:services/api .venv/bin/python -m unittest discover -s services/api/tests -v` |
| Web application tests | Passing, 9 tests on August 16, 2026 | `npm --prefix apps/web test -- --run` |
| Web typecheck | Passing on merged `main` | `npm --prefix apps/web run typecheck` |
| Web production build | Passing on merged `main` | `npm --prefix apps/web run build` |
| Secret and real data scan | Passing on August 15, 2026 | Review tracked files and repository history again after any last minute change |
| Clean install reproduction | Passing on August 15, 2026 | Re-run only if dependencies or setup instructions change |
| Live Hermes integration | Passing on August 16, 2026 — `python3 -m abyss.cli` returned exactly `ABYSS HERMES READY` via the authenticated gateway at `HERMES_BASE_URL` (127.0.0.1:8642); confirmed no code path calls vLLM's port 8000 directly | Use private tunnel and authenticated gateway only |
| Full UI journey | Implemented | Run the golden path three times on the final deployment before recording |

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
