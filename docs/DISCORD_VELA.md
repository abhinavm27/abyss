# Discord VELA through NemoHermes

Discord is a channel around the same current Care Journey Agent used by chat
and voice. It is not a second journey engine.

```text
@Vela in an allowlisted channel
  -> services/discord_bot
  -> POST /api/discord/turn
  -> current care context + deterministic rules
  -> authenticated Hermes/Nemotron gateway for classification/explanation
  -> Discord reply
```

Outbound updates are separate. They use a Discord incoming webhook and contain
only a generic link. The user must enable the allowlisted destination, preview
the exact message, and approve that exact scope before the adapter sends it.

## Configuration

Set the values from `.env.example` in the GN100 process environment. Never
commit tokens, webhook URLs, or the shared bot secret.

- `DISCORD_BOT_TOKEN`: Discord application bot token.
- `DISCORD_BOT_SECRET`: random secret shared only by the bot and API.
- `DISCORD_ALLOWED_CHANNEL_IDS`: comma-separated channel IDs.
- `DISCORD_ALLOWED_GUILD_IDS`: optional comma-separated server IDs.
- `DISCORD_USER_MAP`: `discordUserId:velaUserId` pairs.
- `ABYSS_DISCORD_DEFAULT_USER_ID`: synthetic single-user demo fallback.

Install the optional dependency and start the worker:

```bash
python -m pip install -e '.[discord]'
./scripts/run-discord-vela.sh
```

The bot strips Discord mentions, rejects unmapped users and non-allowlisted
channels, and never receives the Hermes API credential.
