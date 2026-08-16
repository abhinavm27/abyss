"""Discord @Vela bot that delegates every turn to the authenticated API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger("vela.discord")


def call_turn(question: str, user_id: str, channel_id: str, guild_id: str | None) -> str:
    secret = os.getenv("DISCORD_BOT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("DISCORD_BOT_SECRET is not set")
    base = os.getenv("ABYSS_API_BASE_URL", "http://127.0.0.1:8011").rstrip("/")
    request = Request(
        f"{base}/api/discord/turn",
        data=json.dumps({
            "question": question,
            "discord_user_id": user_id,
            "discord_channel_id": channel_id,
            "discord_guild_id": guild_id,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Abyss-Discord-Secret": secret},
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"VELA API rejected the turn with HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("cannot reach the VELA API") from exc
    reply = payload.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise RuntimeError("VELA returned an empty reply")
    return reply.strip()[:1800]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        log.error("DISCORD_BOT_TOKEN is not set")
        return 1
    try:
        import discord
    except ImportError:
        log.error("install the discord optional dependency")
        return 1

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        log.info("VELA Discord bot ready as %s", client.user)

    @client.event
    async def on_message(message) -> None:
        if message.author.bot or client.user is None:
            return
        referenced = getattr(getattr(message, "reference", None), "resolved", None)
        if client.user not in message.mentions and getattr(referenced, "author", None) != client.user:
            return
        try:
            async with message.channel.typing():
                reply = await asyncio.to_thread(
                    call_turn,
                    message.content or "",
                    str(message.author.id),
                    str(message.channel.id),
                    str(message.guild.id) if message.guild else None,
                )
            await message.reply(reply, mention_author=False)
        except Exception:
            log.exception("Discord turn failed")
            await message.reply("I couldn't reach VELA just now. Please try again.", mention_author=False)

    client.run(token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
