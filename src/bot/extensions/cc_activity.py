"""
CC Activity Earnings — VC salary and message salary paid in Engauge CC.

VC salary:   user earns CC_VC_SALARY CC when they disconnect from a VC they were
             in for >= CC_VC_MINUTES continuous minutes alongside >= 1 other non-bot.

Message salary: user earns CC_MSG_SALARY CC the first time they hit CC_MSG_THRESHOLD
                messages in a day (resets 11AM EST, same cadence as /tc collect).
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord.ext import commands
import pytz

from src.bot.base_cog import BaseCog
from src.api.engauge_adapter import EngaugeAdapter

TC_EMOJI        = os.getenv("CURRENCY_EMOJI", "💰")
CC_VC_SALARY    = int(os.getenv("CC_VC_SALARY", "500"))
CC_VC_MINUTES   = int(os.getenv("CC_VC_MINUTES", "30"))
# Exponent for the VC payout curve: 0.5 = square root (diminishing returns),
# 1.0 = linear, >1.0 = accelerating. Default 0.5.
CC_VC_EXPONENT  = float(os.getenv("CC_VC_EXPONENT", "2.0"))
CC_MSG_SALARY   = int(os.getenv("CC_MSG_SALARY", "200"))
CC_MSG_THRESHOLD = int(os.getenv("CC_MSG_THRESHOLD", "50"))

# Optional channel to announce payouts. Set CC_ACTIVITY_CHANNEL_ID in env to enable.
_raw_ch = os.getenv("CC_ACTIVITY_CHANNEL_ID", "").strip()
CC_ACTIVITY_CHANNEL_ID: Optional[int] = int(_raw_ch) if _raw_ch.isdigit() else None

EST = pytz.timezone("America/New_York")


class CcActivity(BaseCog):
    """Passive CC earning via voice chat and server messages."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        # user_id -> (accumulated_seconds: float, segment_start: datetime|None, guild_id: int)
        # accumulated_seconds counts only time spent in a 2+ person channel.
        # segment_start is set when actively in a qualifying channel, None when paused (solo).
        self.vc_sessions: dict[int, tuple[float, datetime | None, int]] = {}

    # ------------------------------------------------------------------ helpers

    def _get_next_reset(self) -> datetime:
        now_est = datetime.now(EST)
        reset = now_est.replace(hour=11, minute=0, second=0, microsecond=0)
        if now_est >= reset:
            reset += timedelta(days=1)
        return reset

    def _already_paid_today(self, last_payout: Optional[datetime]) -> bool:
        if last_payout is None:
            return False
        now_est = datetime.now(EST)
        today_reset = now_est.replace(hour=11, minute=0, second=0, microsecond=0)
        if now_est < today_reset:
            today_reset -= timedelta(days=1)
        if last_payout.tzinfo is None:
            last_payout = pytz.UTC.localize(last_payout)
        return last_payout.astimezone(EST) >= today_reset

    async def _notify(self, guild: discord.Guild, message: str):
        if CC_ACTIVITY_CHANNEL_ID is None:
            return
        ch = guild.get_channel(CC_ACTIVITY_CHANNEL_ID)
        if ch:
            try:
                await ch.send(message)
            except Exception:
                pass

    # ------------------------------------------------------------------ VC salary

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        now = datetime.now(pytz.UTC)
        user_id = member.id
        guild_id = member.guild.id

        dbg_lines: list[str] = []

        def dbg(msg: str):
            ts = now.strftime("%H:%M:%S.%f")[:-3]
            line = f"[{ts}] {msg}"
            print(f"[cc_activity] {line}", flush=True)
            dbg_lines.append(line)

        async def flush_debug():
            if not dbg_lines or CC_ACTIVITY_CHANNEL_ID is None:
                return
            ch = member.guild.get_channel(CC_ACTIVITY_CHANNEL_ID)
            if ch is None:
                return
            # Chunk into <= 1900 char messages (leaving room for code-block fences)
            chunks: list[str] = []
            buf = ""
            for line in dbg_lines:
                if len(buf) + len(line) + 1 > 1900:
                    chunks.append(buf)
                    buf = line
                else:
                    buf = f"{buf}\n{line}" if buf else line
            if buf:
                chunks.append(buf)
            for c in chunks:
                try:
                    await ch.send(f"```\n{c}\n```")
                except Exception as e:
                    print(f"[cc_activity] debug send failed: {e}", flush=True)

        def session_repr(uid: int) -> str:
            if uid not in self.vc_sessions:
                return "no-session"
            acc, seg, _ = self.vc_sessions[uid]
            acc_m = acc / 60
            if seg is None:
                return f"PAUSED acc={acc_m:.2f}m"
            seg_age = (now - seg).total_seconds() / 60
            return f"ACTIVE acc={acc_m:.2f}m seg_age={seg_age:.2f}m"

        def dump_channel(channel: discord.VoiceChannel, label: str):
            if channel is None:
                dbg(f"  {label}: <None>")
                return
            members = [(m.id, m.display_name, m.bot) for m in channel.members]
            dbg(f"  {label}: #{channel.name} ({channel.id}) members={members}")
            for m in channel.members:
                if not m.bot:
                    dbg(f"    session[{m.display_name} {m.id}]: {session_repr(m.id)}")

        # Event header
        before_ch = f"#{before.channel.name}" if before.channel else "None"
        after_ch = f"#{after.channel.name}" if after.channel else "None"
        dbg(f"EVENT user={member.display_name} ({user_id}) {before_ch} -> {after_ch}")
        dbg(f"  caller-session-before: {session_repr(user_id)}")
        dump_channel(before.channel, "before.channel")
        dump_channel(after.channel, "after.channel")

        def non_bot_count(channel: discord.VoiceChannel) -> int:
            return sum(1 for m in channel.members if not m.bot)

        def flush_segment(uid: int) -> float:
            """Freeze the active segment for a user and return total accumulated seconds."""
            if uid not in self.vc_sessions:
                dbg(f"  flush_segment({uid}): no session, return 0")
                return 0.0
            accumulated, seg_start, gid = self.vc_sessions[uid]
            if seg_start is not None:
                added = (now - seg_start).total_seconds()
                accumulated += added
                self.vc_sessions[uid] = (accumulated, None, gid)
                dbg(f"  flush_segment({uid}): added {added/60:.2f}m, total {accumulated/60:.2f}m")
            else:
                dbg(f"  flush_segment({uid}): already paused, total {accumulated/60:.2f}m")
            return accumulated

        def pause_session(uid: int):
            """Freeze active segment without removing the session (user is now solo)."""
            dbg(f"  pause_session({uid})")
            flush_segment(uid)
            if uid in self.vc_sessions:
                accumulated, _, gid = self.vc_sessions[uid]
                self.vc_sessions[uid] = (accumulated, None, gid)

        def resume_session(uid: int):
            """Start a new qualifying segment from now."""
            if uid in self.vc_sessions:
                accumulated, prev_seg, gid = self.vc_sessions[uid]
                if prev_seg is not None:
                    dbg(f"  resume_session({uid}): WARN already active (seg_age={(now-prev_seg).total_seconds()/60:.2f}m), restarting segment")
                else:
                    dbg(f"  resume_session({uid}): resuming from paused, acc={accumulated/60:.2f}m")
                self.vc_sessions[uid] = (accumulated, now, gid)
            else:
                dbg(f"  resume_session({uid}): NEW session from 0")
                self.vc_sessions[uid] = (0.0, now, guild_id)

        try:
            # --- user disconnected entirely ---
            if after.channel is None and before.channel is not None:
                dbg(f"BRANCH: disconnect")
                total_seconds = flush_segment(user_id)
                self.vc_sessions.pop(user_id, None)
                elapsed_minutes = total_seconds / 60
                dbg(f"  payout-check: total={total_seconds/60:.2f}m threshold={CC_VC_MINUTES}m")
                mins = int(elapsed_minutes)
                secs = int(total_seconds % 60)
                if elapsed_minutes >= CC_VC_MINUTES:
                    payout = int(CC_VC_SALARY * (elapsed_minutes / CC_VC_MINUTES) ** CC_VC_EXPONENT)
                    try:
                        engauge = EngaugeAdapter(guild_id)
                        await engauge.credit(user_id, payout)
                        await self._notify(
                            member.guild,
                            f"🎙️ {member.mention} earned **{payout:,} {TC_EMOJI}** for "
                            f"{mins}m {secs}s of qualifying VC time.",
                        )
                    except Exception as e:
                        print(f"[cc_activity] VC payout failed for {user_id}: {e}")
                else:
                    await self._notify(
                        member.guild,
                        f"🔇 {member.mention} disconnected after {mins}m {secs}s "
                        f"(needed {CC_VC_MINUTES}m — no {TC_EMOJI} earned).",
                    )

                # If before.channel is now solo, pause remaining members' sessions
                remaining = non_bot_count(before.channel)
                dbg(f"  before.channel non_bot_count after disconnect: {remaining}")
                if remaining < 2:
                    dbg(f"  -> pausing remaining members in before.channel")
                    for m in before.channel.members:
                        if not m.bot:
                            pause_session(m.id)
                return

            # --- user joined or moved to a new channel ---
            if after.channel is not None:
                # Mute/deafen/server-deafen with no channel change — nothing to do
                if before.channel == after.channel:
                    dbg(f"BRANCH: same-channel state change (mute/deafen), ignore")
                    return

                # Moving from one channel to another: freeze old segment but carry accumulated time
                if before.channel is not None:
                    dbg(f"BRANCH: channel move")
                    flush_segment(user_id)
                    # Do NOT pop — accumulated time persists into the new channel session
                    # Check if the channel they left is now solo
                    remaining = non_bot_count(before.channel)
                    dbg(f"  before.channel non_bot_count after move: {remaining}")
                    if remaining < 2:
                        dbg(f"  -> pausing remaining members in before.channel")
                        for m in before.channel.members:
                            if not m.bot:
                                pause_session(m.id)
                else:
                    dbg(f"BRANCH: fresh join")

                # Fresh join or channel move: start session if new channel is qualifying
                after_count = non_bot_count(after.channel)
                dbg(f"  after.channel non_bot_count: {after_count}")
                if after_count >= 2:
                    dbg(f"  -> qualifying, resuming caller and any paused members")
                    resume_session(user_id)
                    # Resume paused sessions, or start fresh for members who joined solo
                    for m in after.channel.members:
                        if not m.bot and m.id != user_id:
                            if m.id not in self.vc_sessions or self.vc_sessions[m.id][1] is None:
                                resume_session(m.id)
                else:
                    dbg(f"  -> not qualifying (solo), no session started")
                return
        finally:
            await flush_debug()


    # ------------------------------------------------------------------ message salary

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        user_id = message.author.id
        guild_id = message.guild.id

        new_count = await self.db.increment_message_count(user_id, guild_id)
        if new_count < CC_MSG_THRESHOLD:
            return

        # Threshold reached — check daily cap
        user = await self.get_user_balance(user_id, guild_id)
        if self._already_paid_today(user.last_msg_payout):
            # Daily cap hit; just reset counter so it doesn't keep firing
            await self.db.reset_message_count(user_id, guild_id, user.last_msg_payout)
            return

        # Pay out and reset
        now_est = datetime.now(EST)
        await self.db.reset_message_count(user_id, guild_id, now_est)
        try:
            engauge = EngaugeAdapter(guild_id)
            await engauge.credit(user_id, CC_MSG_SALARY)
            await self._notify(
                message.guild,
                f"💬 {message.author.mention} earned **{CC_MSG_SALARY:,} {TC_EMOJI}** for sending "
                f"{CC_MSG_THRESHOLD} messages today!",
            )
        except Exception as e:
            print(f"[cc_activity] Message payout failed for {user_id}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(CcActivity(bot))
