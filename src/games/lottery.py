# src/games/lottery.py
# Tickets are accrued from net-positive gambling winnings via "gamble_winnings" events.

import os
import math
import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, Tuple, Dict, List

import pytz
import discord
from discord.ext import commands, tasks
from discord import app_commands

from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager

# ---------- Timezone & schedule ----------
TZ = pytz.timezone("America/New_York")
DRAW_TIME_LOCAL = time(hour=18, minute=0)   # 6:00 PM ET (Friday)
DRAW_WEEKDAY = 4  # Friday (Mon=0)

# ---------- Currency / formatting ----------
TC_EMOJI = os.getenv('TC_EMOJI', '💰')

def fmt_tc(n: int) -> str:
    return f"{TC_EMOJI} {n:,}"

# ================== CONFIG (env) ==================
# Pot construction
WLOTTERY_BASE_POT = int(os.getenv("WLOTTERY_BASE_POT", "2000000"))              # base seed per week
WLOTTERY_PER_TICKET_ADD = int(os.getenv("WLOTTERY_PER_TICKET_ADD", "500000"))   # + per ticket

# Ticket rules (earned from net profit events)
WLOTTERY_EARN_PER_TICKET = int(os.getenv("WLOTTERY_EARN_PER_TICKET", "500000"))  # 1 ticket per 500k profit
WLOTTERY_MAX_TICKETS_PER_USER = int(os.getenv("WLOTTERY_MAX_TIX", "5"))

# Behavior
WLOTTERY_ROLLOVER_IF_NO_ENTRIES = True
WLOTTERY_CLAIM_WINDOW_HOURS = int(os.getenv("WLOTTERY_CLAIM_HOURS", "12"))
WLOTTERY_ANNOUNCE_CHANNEL_ENV = "WLOTTERY_ANNOUNCE_CHANNEL_ID"  # optional channel id

# Payout destination for CLAIMS: always cash 
# (kept here for clarity; if we ever want BANK instead, flip this)
WLOTTERY_PAY_TO_BANK = False
# ==================================================

# Fixed split 50/30/20
SPLIT = (0.50, 0.30, 0.20)

@dataclass
class WeekWindow:
    start: datetime  # inclusive (Saturday 00:00 ET)
    end: datetime    # exclusive (Friday 6:00 PM ET)

def _now() -> datetime:
    return datetime.now(TZ)

def start_of_week_for(dt: datetime) -> WeekWindow:
    """Weekly window: Saturday 00:00 through Friday 18:00 (ET)."""
    local = dt.astimezone(TZ)
    # Saturday index = 5 (Mon=0..Sun=6)
    days_since_sat = (local.weekday() - 5) % 7
    sat = (local - timedelta(days=days_since_sat)).replace(hour=0, minute=0, second=0, microsecond=0)
    fri_6pm = sat + timedelta(days=6)
    fri_6pm = fri_6pm.replace(hour=DRAW_TIME_LOCAL.hour, minute=DRAW_TIME_LOCAL.minute, second=0, microsecond=0)
    return WeekWindow(start=sat, end=fri_6pm)

def human_time(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%a %b %d, %I:%M %p %Z").replace(" 0", " ")

def _weighted_draw_k(entries: List[Tuple[int, int]], k: int) -> List[int]:
    """
    Draw up to k UNIQUE user_ids weighted by ticket counts, without replacement.
    entries: list of (user_id, tickets)
    Returns: [winner1, winner2, ...] up to k, unique
    """
    pool = [(uid, int(t)) for uid, t in entries if int(t) > 0]
    winners: List[int] = []
    rng = os.urandom  # source of entropy (we'll wrap randint via SystemRandom)
    sysrand = __import__("random").SystemRandom()

    while pool and len(winners) < k:
        total = sum(t for _, t in pool)
        r = sysrand.randrange(1, total + 1)
        cum = 0
        pick_idx = None
        for i, (uid, t) in enumerate(pool):
            cum += t
            if r <= cum:
                pick_idx = i
                break
        if pick_idx is None:
            break
        winners.append(pool[pick_idx][0])
        # remove the winner from pool
        pool.pop(pick_idx)
    return winners

class WeeklyLottery(BaseCog):
    """
    Weekly Lottery — 3 winners (50/30/20), manual claim within 12h, expired → rollover.
    Tickets are earned from net-positive gambling winnings (via 'gamble_winnings' events).
    """

    # Command group removed - all commands are now flat

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self._locks: Dict[int, asyncio.Lock] = {}
        self._weekly_draw_loop.start()
        self._claim_sweeper.start()

    def cog_unload(self):
        self._weekly_draw_loop.cancel()
        self._claim_sweeper.cancel()
        # if not self._init_task.done():
        #     self._init_task.cancel()

    # -------------------- Ticket accrual (events) --------------------
    @commands.Cog.listener()
    async def on_gamble_winnings(self, guild_id: int, user_id: int, amount: int, source: str):
        """
        Games dispatch this ONLY when they credit net-positive winnings.
        Examples:
            Blackjack: profit = payout - bet (if > 0)
            High/Low:  profit = bet (even-money)
            Push/loss: do not dispatch
        """
        if amount <= 0: 
            return
        try:
            wid, _, _ = await self._current_week(guild_id)
            async with self.db._pool.acquire() as conn:
                # ensure row
                await conn.execute(
                    "INSERT INTO wlottery_entries (week_id, guild_id, user_id, earned_sum, tickets) "
                    "VALUES ($1,$2,$3,0,0) "
                    "ON CONFLICT (week_id, guild_id, user_id) DO NOTHING",
                    wid, guild_id, user_id
                )
                # update earned
                await conn.execute(
                    "UPDATE wlottery_entries SET earned_sum = earned_sum + $1 WHERE week_id=$2 AND guild_id=$3 AND user_id=$4",
                    int(amount), wid, guild_id, user_id
                )
                # recompute tickets with cap
                await conn.execute(
                    "UPDATE wlottery_entries "
                    "SET tickets = LEAST($1, earned_sum / $2) "
                    "WHERE week_id=$3 AND guild_id=$4 AND user_id=$5",
                    WLOTTERY_MAX_TICKETS_PER_USER, WLOTTERY_EARN_PER_TICKET, wid, guild_id, user_id
                )
        except Exception as e:
            print(f"[BaseCog] on_gamble_winnings failed: {e!r}")

    def _lock(self, guild_id: int) -> asyncio.Lock:
        L = self._locks.get(guild_id)
        if not L:
            L = asyncio.Lock()
            self._locks[guild_id] = L
        return L

    # -------------------- Week helpers --------------------

    async def _ensure_current_week(self, guild_id: int) -> int:
        now = _now()
        window = start_of_week_for(now)
        st, en = int(window.start.timestamp()), int(window.end.timestamp())

        async with self.db._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM wlottery_weeks WHERE guild_id=$1 AND start_ts=$2 AND end_ts=$3",
                guild_id, st, en
            )
            if row:
                return int(row["id"])

            # compute base: base pot + (rolled over from previous week if no entries) + rollover bank seed
            base = WLOTTERY_BASE_POT
            rolled = False

            # (1) roll previous base if previous week had 0 entries
            if WLOTTERY_ROLLOVER_IF_NO_ENTRIES:
                prev = start_of_week_for(window.start - timedelta(seconds=1))
                pst, pen = int(prev.start.timestamp()), int(prev.end.timestamp())
                prow = await conn.fetchrow(
                    "SELECT id, base_pot FROM wlottery_weeks WHERE guild_id=$1 AND start_ts=$2 AND end_ts=$3",
                    guild_id, pst, pen
                )
                if prow:
                    prev_id, prev_base = int(prow["id"]), int(prow["base_pot"])
                    tix_row = await conn.fetchrow(
                        "SELECT COALESCE(SUM(tickets),0) AS t FROM wlottery_entries WHERE week_id=$1",
                        prev_id
                    )
                    total_prev_tix = int(tix_row["t"] or 0)
                    if total_prev_tix == 0:
                        base += prev_base
                        rolled = True

            # (2) add rollover bank (from expired claims, admin actions, etc.)
            seed_row = await conn.fetchrow("SELECT amount FROM wlottery_rollover_bank WHERE guild_id=$1", guild_id)
            seed = int(seed_row["amount"]) if seed_row else 0
            if seed > 0:
                base += seed
                # clear the bank
                await conn.execute(
                    "INSERT INTO wlottery_rollover_bank (guild_id, amount) VALUES ($1, 0) "
                    "ON CONFLICT(guild_id) DO UPDATE SET amount=0",
                    guild_id
                )

            row2 = await conn.fetchrow(
                "INSERT INTO wlottery_weeks (guild_id, start_ts, end_ts, base_pot, rolled_over_from) "
                "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                guild_id, st, en, base, rolled
            )
            return int(row2["id"])

    async def _current_week(self, guild_id: int) -> Tuple[int, WeekWindow, int]:
        window = start_of_week_for(_now())
        st, en = int(window.start.timestamp()), int(window.end.timestamp())

        async with self.db._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, base_pot FROM wlottery_weeks WHERE guild_id=$1 AND start_ts=$2 AND end_ts=$3",
                guild_id, st, en
            )
        if row:
            return int(row["id"]), window, int(row["base_pot"])
        wid = await self._ensure_current_week(guild_id)
        return wid, window, WLOTTERY_BASE_POT

    async def _rollover_add(self, guild_id: int, amount: int):
        if amount <= 0: return
        async with self.db._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO wlottery_rollover_bank (guild_id, amount) VALUES ($1,$2) "
                "ON CONFLICT(guild_id) DO UPDATE SET amount = wlottery_rollover_bank.amount + EXCLUDED.amount",
                guild_id, int(amount)
            )

    async def _compute_pot(self, week_id: int) -> int:
        async with self.db._pool.acquire() as conn:
            base = await conn.fetchval("SELECT base_pot FROM wlottery_weeks WHERE id=$1", week_id)
            base = int(base or 0)
            tix = await conn.fetchval("SELECT COALESCE(SUM(tickets),0) FROM wlottery_entries WHERE week_id=$1", week_id)
            tix = int(tix or 0)
        return base + (tix * WLOTTERY_PER_TICKET_ADD)



    # -------------------- Draw loop & sweeper --------------------

    @tasks.loop(time=DRAW_TIME_LOCAL)
    async def _weekly_draw_loop(self):
        now_local = _now()
        if now_local.weekday() != DRAW_WEEKDAY:
            return
        for g in list(self.bot.guilds):
            async with self._lock(g.id):
                try:
                    await self._run_draw_for_guild(g.id, announce_channel=None)
                except Exception as e:
                    print(f"[WeeklyLottery] draw error (guild {g.id}): {e!r}")

    @_weekly_draw_loop.before_loop
    async def _before_weekly_loop(self):
        await self.bot.wait_until_ready()
        # Initialize current week for all guilds
        for g in list(self.bot.guilds):
            try:
                await self._ensure_current_week(g.id)
            except Exception as e:
                print(f"[WeeklyLottery] init error (guild {g.id}): {e!r}")

    # Expire unclaimed winners; move to rollover
    @tasks.loop(minutes=5)
    async def _claim_sweeper(self):
        try:
            now_ts = int(_now().timestamp())
            async with self.db._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, guild_id, pot_awarded FROM wlottery_winners "
                    "WHERE status='pending' AND claim_deadline_ts < $1",
                    now_ts
                )
                for r in rows:
                    wid_id = int(r["id"]); gid = int(r["guild_id"]); amt = int(r["pot_awarded"])
                    # mark expired
                    await conn.execute(
                        "UPDATE wlottery_winners SET status='expired' WHERE id=$1 AND status='pending'",
                        wid_id
                    )
                    # add to rollover bank
                    await self._rollover_add(gid, amt)
        except Exception as e:
            print("[WeeklyLottery] claim sweeper error:", e)

    @_claim_sweeper.before_loop
    async def _before_claim_sweeper(self):
        await self.bot.wait_until_ready()

    async def _run_draw_for_guild(self, guild_id: int, announce_channel: Optional[discord.TextChannel]):
        wid, window, _ = await self._current_week(guild_id)

        # Pot and entries
        async with self.db._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, tickets FROM wlottery_entries WHERE week_id=$1 AND tickets>0",
                wid
            )
        entries = [(int(r["user_id"]), int(r["tickets"])) for r in rows if int(r["tickets"]) > 0]
        total_tickets = sum(t for _, t in entries)
        pot = await self._compute_pot(wid)

        # Announce channel (optional)
        chan = announce_channel
        if chan is None:
            chan_id = os.getenv(WLOTTERY_ANNOUNCE_CHANNEL_ENV)
            if chan_id:
                c = self.bot.get_channel(int(chan_id))
                if isinstance(c, discord.TextChannel):
                    chan = c

        # No entries → (optional) rollover base; create next week
        if total_tickets <= 0:
            if WLOTTERY_ROLLOVER_IF_NO_ENTRIES:
                await self._rollover_add(guild_id, pot)
            if chan:
                try:
                    await chan.send(
                        f"🎟️ **Weekly Lottery** ending {human_time(window.end)} had no entries. "
                        f"Pot {fmt_tc(pot)} {'rolls over' if WLOTTERY_ROLLOVER_IF_NO_ENTRIES else 'resets'}."
                    )
                except Exception:
                    pass
            await self._ensure_current_week(guild_id)
            return

        # Draw up to 3 unique winners
        winners = _weighted_draw_k(entries, 3)
        # If fewer than 3 unique participants, leftover shares go to rollover bank.
        splits = [int(math.floor(pot * SPLIT[i])) for i in range(3)]
        # adjust rounding so total equals pot
        delta = pot - sum(splits)
        if delta != 0:
            splits[0] += delta  # fix rounding error on 1st

        draw_ts = int(_now().timestamp())
        deadline_ts = draw_ts + WLOTTERY_CLAIM_WINDOW_HOURS * 3600

        # Insert winners (pending) and handle missing spots
        async with self.db._pool.acquire() as conn:
            awarded_total = 0
            for i in range(3):
                share = splits[i]
                if i < len(winners):
                    uid = winners[i]
                    await conn.execute(
                        "INSERT INTO wlottery_winners "
                        "(week_id, guild_id, user_id, place, pot_awarded, drawn_ts, claim_deadline_ts, status) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,'pending')",
                        wid, guild_id, uid, i+1, share, draw_ts, deadline_ts
                    )
                    awarded_total += share
                else:
                    # Not enough unique entrants — put this share into rollover immediately
                    await self._rollover_add(guild_id, share)
            
            # Clear all tickets for this week after winners have been picked
            await conn.execute(
                "UPDATE wlottery_entries SET tickets = 0 WHERE week_id = $1",
                wid
            )

        # Announce results (no auto-pay)
        if chan:
            try:
                def mention(uid: Optional[int]) -> str:
                    return f"<@{uid}>" if uid else "—"
                w1 = winners[0] if len(winners) > 0 else None
                w2 = winners[1] if len(winners) > 1 else None
                w3 = winners[2] if len(winners) > 2 else None
                # Build results message with conditional amounts
                results_lines = [
                    f"🎉 **Weekly Lottery Results** ({human_time(window.start)} → {human_time(window.end)})",
                    f"• Pot: **{fmt_tc(pot)}** • Tickets: **{total_tickets:,}**",
                    f"🥇 1st {mention(w1)} — {fmt_tc(splits[0])}"
                ]
                
                if w2 is not None:
                    results_lines.append(f"🥈 2nd {mention(w2)} — {fmt_tc(splits[1])}")
                else:
                    results_lines.append(f"🥈 2nd {mention(w2)}")
                    
                if w3 is not None:
                    results_lines.append(f"🥉 3rd {mention(w3)} — {fmt_tc(splits[2])}")
                else:
                    results_lines.append(f"🥉 3rd {mention(w3)}")
                
                results_lines.extend([
                    "",
                    f"**Winners have {WLOTTERY_CLAIM_WINDOW_HOURS} hours** to claim with `/wlottery claim`.",
                    "Unclaimed prizes **expire** and **roll over** to next week."
                ])
                
                await chan.send("\n".join(results_lines))
            except Exception:
                pass

        # Prepare next week row (so rollover bank gets picked up at start)
        await self._ensure_current_week(guild_id)

    # -------------------- Slash Commands --------------------

    @app_commands.command(name="wlottery-info", description="Show this week's pot, draw time, and total tickets.")
    async def info(self, inter: discord.Interaction):
        wid, window, _ = await self._current_week(inter.guild_id)
        pot = await self._compute_pot(wid)
        async with self.db._pool.acquire() as conn:
            total_tix = await conn.fetchval(
                "SELECT COALESCE(SUM(tickets),0) FROM wlottery_entries WHERE week_id=$1", wid
            )
        total_tix = int(total_tix or 0)

        now = _now()
        remaining = window.end - now
        if remaining.total_seconds() < 0:
            remaining_str = "drawing soon…"
        else:
            hrs = int(remaining.total_seconds() // 3600)
            mins = int((remaining.total_seconds() % 3600) // 60)
            remaining_str = f"{hrs}h {mins}m"

        emb = discord.Embed(title="🎟️ Weekly Lottery", color=discord.Color.blurple())
        emb.add_field(name="Current Pot", value=fmt_tc(pot), inline=True)
        emb.add_field(name="Total Tickets", value=f"{total_tix:,}", inline=True)
        emb.add_field(name="Draws At", value=human_time(window.end), inline=False)
        emb.add_field(name="Time Remaining", value=remaining_str, inline=True)
        emb.set_footer(text=f"Tickets: 1 per {fmt_tc(WLOTTERY_EARN_PER_TICKET)} (max {WLOTTERY_MAX_TICKETS_PER_USER})")
        await inter.response.send_message(embed=emb, ephemeral=True)

    @app_commands.command(name="wlottery-mytickets", description="See your tickets and progress toward the next ticket.")
    async def mytickets(self, inter: discord.Interaction):
        wid, _, _ = await self._current_week(inter.guild_id)
        async with self.db._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT earned_sum, tickets FROM wlottery_entries WHERE week_id=$1 AND guild_id=$2 AND user_id=$3",
                wid, inter.guild_id, inter.user.id
            )
        earned = int(row["earned_sum"]) if row else 0
        tix = int(row["tickets"]) if row else 0

        if tix >= WLOTTERY_MAX_TICKETS_PER_USER:
            progress = f"Maxed at {WLOTTERY_MAX_TICKETS_PER_USER} tickets."
        else:
            needed = max(0, (tix + 1) * WLOTTERY_EARN_PER_TICKET - earned)
            progress = f"{fmt_tc(needed)} more to reach ticket #{tix+1}."

        await inter.response.send_message(
            f"🎫 You have **{tix}** ticket(s) this week.\n"
            f"Total qualifying earnings: **{fmt_tc(earned)}**\n"
            f"{progress}",
            ephemeral=True
        )

    @app_commands.command(name="wlottery-claim", description="Claim your pending weekly lottery prize (if any).")
    async def claim(self, inter: discord.Interaction):
        now_ts = int(_now().timestamp())
        async with self.db._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, pot_awarded, claim_deadline_ts "
                "FROM wlottery_winners "
                "WHERE guild_id=$1 AND user_id=$2 AND status='pending' AND claim_deadline_ts >= $3 "
                "ORDER BY id ASC",
                inter.guild_id, inter.user.id, now_ts
            )

        if not rows:
            return await inter.response.send_message(
                "You have no pending weekly lottery prize to claim (or it expired).",
                ephemeral=True
            )

        # Claim ALL current pending prizes for this user (usually only one)
        total = sum(int(r["pot_awarded"]) for r in rows)
        # Credit CASH so employees can /deposit themselves
        try:
            await self.db.update_user_balance(
                inter.user.id, inter.guild_id,
                cash_delta=total, total_earned_delta=total
            )
            await self.db.log_transaction(
                inter.user.id, inter.guild_id, total, "weekly_lottery_claim",
                success=True, reason="Weekly Lottery manual claim"
            )
        except Exception as e:
            return await inter.response.send_message(f"⚠️ Claim failed: {e}", ephemeral=True)

        ids = [int(r["id"]) for r in rows]
        async with self.db._pool.acquire() as conn:
            await conn.execute(
                "UPDATE wlottery_winners "
                "SET status='claimed', claimed_at_ts=$1 "
                f"WHERE id = ANY($2::BIGINT[]) AND status='pending'",
                now_ts, ids
            )

        pretty = fmt_tc(total)
        await inter.response.send_message(
            f"✅ Claimed your weekly lottery prize: **{pretty}** to cash.\n"
            f"Use your `/deposit` command if you’d like to move it to bank."
        )

    @app_commands.command(name="wlottery-winners", description="Show the latest winners & claim deadlines.")
    async def winners_cmd(self, inter: discord.Interaction):
        wid, window, _ = await self._current_week(inter.guild_id)
        # show winners from the most recent completed week (might be the current week if just drawn)
        async with self.db._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT place, user_id, pot_awarded, status, claim_deadline_ts "
                "FROM wlottery_winners "
                "WHERE guild_id=$1 AND week_id=$2 "
                "ORDER BY place ASC",
                inter.guild_id, wid
            )

        if not rows:
            return await inter.response.send_message("No winners recorded for this week yet.", ephemeral=True)

        lines = []
        for r in rows:
            place = int(r["place"]); uid = int(r["user_id"])
            amt = int(r["pot_awarded"]); status = str(r["status"])
            deadline = int(r["claim_deadline_ts"])
            place_emoji = "🥇" if place == 1 else ("🥈" if place == 2 else "🥉")
            status_txt = {
                "pending": f"pending • expires <t:{deadline}:R>",
                "claimed": "claimed ✅",
                "expired": "expired ⌛"
            }.get(status, status)
            lines.append(f"{place_emoji} <@{uid}> — {fmt_tc(amt)} • {status_txt}")

        await inter.response.send_message(
            f"**Weekly Lottery Winners** ({human_time(window.start)} → {human_time(window.end)})\n" +
            "\n".join(lines),
            ephemeral=True
        )

    @app_commands.command(name="wlottery-force-draw", description="(Admin) Force this week's draw now (creates claimable prizes).")
    @app_commands.default_permissions(administrator=True)
    async def force_draw(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        async with self._lock(inter.guild_id):
            await self._run_draw_for_guild(inter.guild_id, announce_channel=inter.channel)
        await inter.followup.send("Forced weekly draw executed.", ephemeral=True)

    @app_commands.command(name="wlottery-storage", description="(Admin) Show weekly lottery storage stats.")
    @app_commands.default_permissions(administrator=True)
    async def storage(self, inter: discord.Interaction):
        wid, _, _ = await self._current_week(inter.guild_id)
        async with self.db._pool.acquire() as conn:
            wcnt = await conn.fetchval("SELECT COUNT(*) FROM wlottery_weeks WHERE guild_id=$1", inter.guild_id)
            ecnt = await conn.fetchval("SELECT COUNT(*) FROM wlottery_entries WHERE week_id=$1", wid)
            wincnt = await conn.fetchval("SELECT COUNT(*) FROM wlottery_winners WHERE week_id=$1", wid)
            bank = await conn.fetchval("SELECT amount FROM wlottery_rollover_bank WHERE guild_id=$1", inter.guild_id) or 0
        await inter.response.send_message(
            f"Rows — weeks: **{int(wcnt)}**, entries (this week): **{int(ecnt)}**, winners (this week): **{int(wincnt)}**\n"
            f"Rollover bank: {fmt_tc(int(bank))}",
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(WeeklyLottery(bot))
