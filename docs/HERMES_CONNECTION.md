# Connect to Hermes on the GN100

## Prerequisites

Each collaborator needs:

1. Tailscale installed and authorized to reach `gn100-75f8`.
2. Their own SSH access to the GN100. Tailscale access alone does not grant an OS login.
3. Python 3.11 or newer for the repository client.

Do not share the GN100 password, another person’s SSH key, or the Hermes bearer token.

## Open the private tunnel

Copy `.env.example` to `.env`, adjust the SSH user/host if necessary, then run:

```bash
./scripts/tunnel-hermes.sh
```

The foreground process intentionally remains open. It forwards only loopback ports:

- `http://127.0.0.1:8642/v1` → authenticated Hermes API
- `http://127.0.0.1:18791/` → Hermes dashboard

Press Ctrl-C to close the tunnel.

## Load the API token without printing it

In a trusted shell, retrieve the token over SSH into an environment variable:

```bash
export HERMES_API_KEY="$(ssh "${GN100_SSH_USER}@${GN100_SSH_HOST}" \
  'nemohermes hermes gateway-token --quiet')"
```

The command contains no secret literal. Do not echo the variable or save it in shell history.

## Verify

```bash
PYTHONPATH=src python3 -m abyss.cli
```

Expected response includes `ABYSS HERMES READY`.

## Troubleshooting

- `Connection refused`: verify the tunnel is open and `nemohermes hermes status` is Ready.
- `401 Unauthorized`: retrieve a current gateway token again.
- hostname failure: use the GN100 Tailscale IP or enable MagicDNS.
- SSH denied: the tailnet is reachable, but the user still needs an authorized SSH key.
- model timeout after reboot: vLLM may need several minutes to load the 35B model.

