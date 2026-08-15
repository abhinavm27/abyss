# Architecture

## Components

| Component | Weekend responsibility |
| --- | --- |
| Multimodal intake | Extract seeded card/referral fields with provenance |
| Healthcare data model | Represent plans, benefits, providers, rules, and time |
| Personal Care Twin | Persist facts, preferences, eligibility, and approvals |
| Cost engine | Deterministically rank annual-cost paths |
| Eligibility engine | Implement one validated Special Enrollment gate |
| Agent orchestrator | Coordinate retrieval, calculation, consent, and execution |
| Voice adapter | Controlled provider verification with recorded fallback |
| Enrollment adapter | Explicitly sandboxed submission and transition |
| Audit ledger | Record evidence, verification, and consent events |

## Trust boundaries

```text
Developer machine
  └─ local client / coding agent
       └─ SSH loopback tunnel over Tailscale
            └─ GN100 host
                 ├─ NemoClaw/OpenShell policy boundary
                 │    └─ Hermes sandbox
                 │         └─ https://inference.local
                 └─ vLLM model server on GB10
```

- Tailscale authenticates private network membership.
- SSH authenticates host access and protects port forwarding.
- The Hermes bearer token authenticates API clients.
- NemoClaw restricts filesystem, process, and network access.
- The ABYSS workflow enforces domain consent and action rules.

No single layer replaces another.

## Agent/model responsibility split

Use Hermes for extraction assistance, ambiguity detection, explanation, tool
selection, and workflow coordination. Use deterministic application code for:

- arithmetic and ranking
- eligibility rules
- state transitions
- consent enforcement
- schema validation
- audit records

