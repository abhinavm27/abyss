# VELA submission checklist

Submission deadline: **August 16 at 11:00 AM Pacific Time**

One submission is permitted per team. This tracker records repository readiness; it does not replace the official submission form.

## Required submission fields

| Requirement | Status | Current material | Remaining action |
| --- | --- | --- | --- |
| Team name | Ready | VELA | Enter `VELA` in the form |
| Project description | Ready | README opening paragraph | Copy the approved description exactly |
| Challenge selected | Ready | Do Track rationale in README | Select `Do` in the form |
| Demo video | Ready | [Public 3:32 VELA demo](https://www.youtube.com/watch?v=96vTfD5ZC2M), verified on August 16, 2026 | Enter the verified URL in the submission form |
| Repository link | Ready | `https://github.com/abhinavm27/abyss` on merged `main` | Enter the repository URL in the form |
| Deployed URL or working screen capture | Ready | `https://gn100-75f8.tailf05681.ts.net` (confirmed live via `/api/health` on August 16, 2026) | Verify the final deployed build immediately before submission |
| Team roster | Ready | All three names, roles, and contact details are in README | Copy the roster into the submission form |

## README requirements

| Requirement | Status | Location | Remaining action |
| --- | --- | --- | --- |
| Quick start commands | Ready | `README.md` | Reproduced from a clean checkout on August 15, 2026 |
| Tech stack and architecture diagram | Ready | `README.md`, `docs/ARCHITECTURE.md` | Add final UI or deployment components if they change |
| Demo reproduction, environment variables, API keys, sample environment | Ready | `README.md`, `.env.example`, `docs/DEMO_RUNBOOK.md`, `docs/HERMES_CONNECTION.md` | Judge-safe deterministic reproduction requires no private model credentials |
| Datasets and synthetic data provenance | Ready | `docs/DATA_PROVENANCE.md` | Add any new external source before submission |
| Known limitations and next steps | Ready | `README.md` | Reconcile after final integration |

## Do Track evidence

| Judging signal | Status | Existing evidence | Demo emphasis |
| --- | --- | --- | --- |
| Full workflow completeness | Ready | Tested vertical slice and team-confirmed demo reproduction from intake through sandbox booking | Show the same path in the final video |
| Branching and error recovery | Ready | Tests cover ambiguity, out-of-network rejection, missing consent, transition prerequisites, and idempotency | Surface the most compelling branch visibly |
| Technical depth | Ready | Fact ledger, deterministic engine, bounded agents, consent state machine, adapters, and audit ledger | Show the architecture and one live audit trace |
| NVIDIA ecosystem | Ready | Local Nemotron through NemoClaw and Hermes on NVIDIA GB10 | Capture local-inference proof and explain why local execution matters |
| Human value | Ready | Spoken request to cost-aware care path and sandbox appointment outcome | Keep the video centered on one understandable patient story |
| Usability | Ready | Complete VELA web and iPhone compositions, voice and chat journeys, neural care paths, camera/PDF intake, and functional workspace tabs | Use the final deployed composition |
| Performance | Ready | Local inference and deterministic calculation | Include measured latency or utilization when available |

## Engineering verification

| Check | Status | Current result | Final command or evidence |
| --- | --- | --- | --- |
| Domain and vertical-slice tests | Ready | Passing, 109 tests on August 16, 2026 at `6c86757` | `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v` |
| API service tests | Ready | Passing, 17 tests on August 16, 2026 at `6c86757` | `PYTHONPATH=src:services/api .venv/bin/python -m unittest discover -s services/api/tests -v` |
| Web application tests | Ready | Passing, 9 tests on August 16, 2026 at `6c86757` | `npm --prefix apps/web test -- --run` |
| Web typecheck | Ready | Passing on August 16, 2026 at `6c86757` | `npm --prefix apps/web run typecheck` |
| Web production build | Ready | Passing on August 16, 2026 at `6c86757` | `npm --prefix apps/web run build` |
| Expanded GitHub Actions | Ready | Passing on August 16, 2026 at `e66f6db` | Root, API, web test, typecheck, build, and dependency-audit steps passed |
| Secret and real data review | Ready | Focused tracked-file and changed-path scan passing on August 16, 2026 at `6c86757`; no private-key or common token patterns, runtime databases, raw uploads, or `.env` files found | Run the repository-history scanner again if one becomes available before merge |
| Clean install reproduction | Ready | Passing on August 15, 2026 | Re-run only if dependencies or setup instructions change |
| Live Hermes integration | Ready | Passing on August 16, 2026 — `python3 -m abyss.cli` returned exactly `ABYSS HERMES READY` via the authenticated gateway at `HERMES_BASE_URL` (127.0.0.1:8642); confirmed no code path calls vLLM's port 8000 directly | Use private tunnel and authenticated gateway only |
| Public interface smoke check | Ready | The deployed site accepted the synthetic MRI request, displayed three deterministic paths, and showed the seeded appointment | `View receipt` opens a modal labeled `Sandbox audit receipt` in `apps/web/src/vela/VelaTabs.tsx` |
| Demo reproduction | Ready | Team-confirmed on August 16, 2026 | `docs/DEMO_RUNBOOK.md` contains the seeded inputs, exact consent scopes, expected outcomes, and recovery cases |

## Repository polish verification

- Branch: `codex/repo_struct`
- Pull request: `#9` into `main`
- Validated source revision: `6c86757`
- Runtime impact: none; the branch changes repository documentation and CI coverage only
- GitHub About description, website, and recommended topics: updated August 16, 2026
- Public deployment: reachable at `https://vela-care-path.fsaguilar16.chatgpt.site/`
- Final demo-video link: verified and published at `https://www.youtube.com/watch?v=96vTfD5ZC2M`

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
