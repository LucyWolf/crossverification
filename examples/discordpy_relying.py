"""The relying side in a discord.py bot: grant a role when a partner vouches for somebody.

The interesting part is not the asking — that is one line — it is what happens around it:

* ask when they join, and again on a schedule, because a verification can be taken away
  and this protocol has no way to push that (SPEC.md §7);
* grant on a clear yes, and on a clear **no** take the role away again, but ONLY on a clear
  no — an unreachable partner must never cost somebody their role;
* tell an admin when the pairing itself is broken, instead of asking forever.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord                                  # noqa: E402
from discord.ext import commands, tasks         # noqa: E402

from crossverification import Outcome, ask_partner   # noqa: E402

# ── TODO: yours ───────────────────────────────────────────────────────────────
PARTNER_URL = "https://partner.example.com"
PARTNER_KEY = "the-key-they-gave-you"
GRANT_ROLE_ID = 111222333444555666
ADMIN_CHANNEL_ID = 0            # 0 = say nothing

bot = commands.Bot(command_prefix="!", intents=discord.Intents(members=True, guilds=True))


async def warn_admins(bot_, guild, text):
    channel = guild.get_channel(ADMIN_CHANNEL_ID) if ADMIN_CHANNEL_ID else None
    if channel:
        await channel.send(f"⚠️ CrossVerification: {text}")
    else:
        print(f"[crossverification] {text}")


async def sync_member(member: discord.Member) -> None:
    role = member.guild.get_role(GRANT_ROLE_ID)
    if role is None:
        return
    result = await ask_partner(PARTNER_URL, PARTNER_KEY, member.id)

    if result.outcome is Outcome.VERIFIED:
        if role not in member.roles:
            await member.add_roles(role, reason="Verified by partner (CrossVerification)")
        return

    if result.outcome is Outcome.NOT_VERIFIED:
        # The only branch that takes something away, and only because the partner said so
        # in as many words. Everything below this point is "we don't know right now".
        if role in member.roles:
            await member.remove_roles(
                role, reason="Partner no longer vouches (CrossVerification)")
        return

    if result.pairing_broken:
        await warn_admins(bot, member.guild,
                          f"the pairing is not working ({result.outcome.value}: "
                          f"{result.detail}). Nothing was changed.")
    # Unreachable, rate-limited, nonsense answer: leave everything as it is and try again
    # on the next run. Removing a role because a request timed out would be the worst
    # possible reading of a failure.


@bot.event
async def on_member_join(member: discord.Member):
    await sync_member(member)


@tasks.loop(hours=6)
async def resync():
    """Catch what joining cannot: somebody losing their verification over there."""
    for guild in bot.guilds:
        for member in guild.members:
            if not member.bot:
                await sync_member(member)


@resync.before_loop
async def _wait():
    await bot.wait_until_ready()


if __name__ == "__main__":
    resync.start()
    bot.run("YOUR-BOT-TOKEN")
