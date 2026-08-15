# Security and data handling

## Repository policy

Never commit:

- passwords, bearer tokens, API keys, SSH private keys, or login URLs
- real insurance cards, referrals, health records, or identifiers
- model-server caches, NemoClaw runtime state, or private audit exports
- `.env`, `data/private/`, or `data/uploads/`

Use synthetic fixtures with obviously fictional identities.

## Infrastructure policy

- Access the GN100 through Tailscale.
- Forward dashboard and API ports to `127.0.0.1` only.
- Do not expose ports 8000, 8642, or 18791 through a public tunnel or router.
- Use the Hermes gateway on port 8642; do not call vLLM port 8000 from applications.
- Retrieve the Hermes token at runtime and keep it out of shell history and logs.
- Give each teammate an individual Tailscale identity and SSH key; do not share accounts.
- Revoke access when the event ends.

## Product policy

- Minimize data disclosed to providers.
- Keep enrollment approval separate from transition approval.
- Record who approved what and when.
- Mark simulated actions and seeded data visibly.
- Surface missing/conflicting facts; never manufacture certainty.
- Maintain an identical recorded fallback for the provider call.

