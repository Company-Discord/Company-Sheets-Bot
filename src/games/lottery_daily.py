# lottery_daily.py — Daily Lottery with House mechanic (ratio hidden from users) using custom currency system

import os
import math
import time
import random
import asyncio
from typing import Optional, Dict, List, Tuple
import pytz
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

# Import unified database and base cog
from src.database.database import Database
from src.bot.base_cog import BaseCog

# =================== Config (env) ===================

CURRENCY_ICON = os.getenv("TC_EMOJI", "💰")

DEFAULT_TICKET_PRICE = int(os.getenv("LOTTERY_TICKET_PRICE", "100000"))          # 100k
DEFAULT_BONUS_PER_TICKET = int(os.getenv("LOTTERY_BONUS_PER_TICKET", "50000"))   # +50k per ticket (to pot only)
DEFAULT_MIN_PARTICIPANTS = int(os.getenv("LOTTERY_MIN_PARTICIPANTS", "3"))
DEFAULT_SPLIT_FIRST_BPS = int(os.getenv("LOTTERY_SPLIT_FIRST_BPS", "7000"))      # 7000 = 70% to 1st

# House odds as "player:house" weights. Example: "4:1" (~20% house), "1:3" (~75% house; ~25% player day)
HOUSE_RATIO_STR = os.getenv("LOTTERY_HOUSE_RATIO", "4:1")

# Fixed daily schedule
DAILY_TZ = pytz.timezone("America/New_York")
DAILY_HOUR = 11
DAILY_MINUTE = 0


# =================== Import Custom Currency System ===================

# Import custom currency utilities
from src.utils.utils import is_admin_or_manager

# Custom lottery exceptions
class InsufficientFunds(Exception):
    pass



# =================== Lottery Schema (PostgreSQL) ===================

# Lottery tables are now part of the unified database schema
# The schema is defined in src/database/database.py


# =================== Helpers ===================

def now_i() -> int:
    """Get current timestamp in EST."""
    est = pytz.timezone('America/New_York')
    return int(datetime.now(est).timestamp())


def weighted_draw_two(entries: List[Tuple[int, int]]) -> Tuple[int, Optional[int]]:
    """Weighted without replacement."""
    total = sum(q for _, q in entries)
    rng = random.SystemRandom()

    # Winner 1
    r1 = rng.randrange(1, total + 1)
    cum = 0
    w1 = None
    for uid, qty in entries:
        cum += qty
        if r1 <= cum:
            w1 = uid
            break

    # Winner 2 (remove w1)
    entries2 = [(uid, qty) for uid, qty in entries if uid != w1]
    total2 = sum(q for _, q in entries2)
    if total2 <= 0:
        return (w1, None)

    r2 = rng.randrange(1, total2 + 1)
    cum = 0
    w2 = None
    for uid, qty in entries2:
        cum += qty
        if r2 <= cum:
            w2 = uid
            break

    return (w1, w2)


def _parse_house_ratio(s: str) -> tuple[int, int]:
    """Parse 'player:house' into integer weights; default to 4:1 if invalid."""
    try:
        p, h = s.split(":")
        p = max(1, int(p.strip()))
        h = max(0, int(h.strip()))
        return (p, h)
    except Exception:
        return (4, 1)


HOUSE_PLAYER_W, HOUSE_HOUSE_W = _parse_house_ratio(HOUSE_RATIO_STR)


def _house_tickets_for(qty: int) -> int:
    """Add floor(qty * (house/player)) house tickets."""
    if qty <= 0 or HOUSE_HOUSE_W <= 0:
        return 0
    return math.floor(qty * (HOUSE_HOUSE_W / HOUSE_PLAYER_W))


def next_11am_et(after_ts: Optional[int] = None) -> int:
    if after_ts is None:
        base = datetime.now(DAILY_TZ)
    else:
        base = datetime.fromtimestamp(after_ts, DAILY_TZ)
    candidate = base.replace(hour=DAILY_HOUR, minute=DAILY_MINUTE, second=0, microsecond=0)
    if base >= candidate:
        candidate = candidate + timedelta(days=1)
    return int(candidate.timestamp())


# =================== Cog ===================

class LotteryDaily(BaseCog):
    """Daily Lottery with rollover and House mechanic (ratio hidden) using custom currency system."""

    # Command group removed - all commands are now flat

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self._locks: Dict[int, asyncio.Lock] = {}
        # Configuration for prize payouts (bank vs cash)
        self.payout_to_bank = os.getenv("LOTTERY_PAYOUT_TO", "cash").lower() == "bank"

        self.sweeper.start()
        self.opener.start()

    def cog_unload(self):
        self.sweeper.cancel()
        self.opener.cancel()

    # ---------- Database Methods ----------
    # Database access is now handled by the unified database via self.db

    def _lock(self, guild_id: int) -> asyncio.Lock:
        L = self._locks.get(guild_id)
        if not L:
            L = asyncio.Lock()
            self._locks[guild_id] = L
        return L

    async def _credit_prize(self, guild_id: int, user_id: int, amount: int, reason: str):
        """Credit a lottery prize to user's account (bank or cash based on config)."""
        if self.payout_to_bank:
            # Use unified database for bank credits
            await self.db.update_user_balance(
                user_id, guild_id, 
                bank_delta=amount, 
                total_earned_delta=amount
            )
            await self.db.log_transaction(
                user_id, guild_id, amount, "lottery_prize", 
                success=True, reason=reason
            )
        else:
            # Use unified database for cash credits
            await self.db.update_user_balance(
                user_id, guild_id, 
                cash_delta=amount, 
                total_earned_delta=amount
            )
            await self.db.log_transaction(
                user_id, guild_id, amount, "lottery_prize", 
                success=True, reason=reason
            )

    async def _last_channel_or_none(self, guild_id: int) -> Optional[int]:
        async with self.db._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT announce_channel_id FROM lotteries WHERE guild_id=$1 ORDER BY id DESC LIMIT 1",
                guild_id
            )
            return row["announce_channel_id"] if row else None

    async def _current_open(self, guild_id: int) -> Optional[dict]:
        async with self.db._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM lotteries WHERE guild_id=$1 AND status='open' ORDER BY id DESC LIMIT 1",
                guild_id
            )
            return dict(row) if row else None

    async def _pot_components(self, lottery_id: int) -> Tuple[int, int, int]:
        """Return (tickets_qty, gross_paid, bonus_added)."""
        async with self.db._pool.acquire() as conn:
            lot = await conn.fetchrow("SELECT * FROM lotteries WHERE id=$1", lottery_id)
            if not lot:
                return (0, 0, 0)
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(tickets.quantity),0) q, COALESCE(SUM(tickets.amount_paid),0) p FROM tickets WHERE lottery_id=$1",
                lottery_id
            )
            qty = int(row["q"])
            paid = int(row["p"])
            bonus = qty * int(lot["bonus_per_ticket"])
            return (qty, paid, bonus)

    async def _bank_get(self, guild_id: int) -> int:
        async with self.db._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT rollover_bank.amount FROM rollover_bank WHERE rollover_bank.guild_id=$1", guild_id)
            return int(row["amount"]) if row else 0

    async def _bank_add(self, guild_id: int, amount: int):
        async with self.db._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO rollover_bank (guild_id, amount) VALUES ($1, $2) "
                "ON CONFLICT(guild_id) DO UPDATE SET amount = amount + EXCLUDED.amount",
                guild_id, int(max(0, amount))
            )

    async def _bank_clear(self, guild_id: int) -> int:
        amt = await self._bank_get(guild_id)
        async with self.db._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO rollover_bank (guild_id, amount) VALUES ($1, 0) "
                "ON CONFLICT(guild_id) DO UPDATE SET amount=0",
                guild_id
            )
        return amt

    # ---------- Background: close at end of window ----------
    @tasks.loop(seconds=60)
    async def sweeper(self):
        try:
            now = now_i()
            async with self.db._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, guild_id, announce_channel_id FROM lotteries WHERE status='open' AND close_ts <= $1",
                    now
                )
            
            if rows:
                print(f"lottery sweeper: processing {len(rows)} lotteries that need to close")
                for r in rows:
                    gid = int(r["guild_id"])
                    lottery_id = int(r["id"])
                    channel_id = int(r["announce_channel_id"])
                    ch = self.bot.get_channel(channel_id)
                    channel_name = ch.name if ch else f"<#{channel_id}>"
                    print(f"lottery sweeper: processing lottery {lottery_id} in guild {gid}, channel {channel_name}")
                    
                    async with self._lock(gid):
                        await self._close_and_settle_or_rollover_locked(gid, lottery_id, force_rollover=False)
        except Exception as e:
            print("lottery sweeper error:", e)

    @sweeper.before_loop
    async def before_sweeper(self):
        await self.bot.wait_until_ready()

    # ---------- Background: open at 11:00 ET ----------
    @tasks.loop(seconds=60)
    async def opener(self):
        try:
            for g in list(self.bot.guilds):
                gid = g.id
                async with self._lock(gid):
                    row = await self._current_open(gid)
                    now = now_i()
                    if row and now < int(row["close_ts"]):
                        continue
                    open_ts = next_11am_et(now - 3600)
                    if now < open_ts:
                        continue
                    close_ts = open_ts + 24 * 3600
                    # close_ts = open_ts + 2 * 60
                    ch_id = await self._last_channel_or_none(gid)
                    if ch_id is None:
                        continue
                    await self._open_new_round(gid, ch_id, open_ts, close_ts, auto=True)
        except Exception as e:
            print("lottery opener error:", e)

    @opener.before_loop
    async def before_opener(self):
        await self.bot.wait_until_ready()

    # ---------- Round ops ----------
    async def _open_new_round(self, guild_id: int, channel_id: int, open_ts: int, close_ts: int, auto: bool):
        seed = await self._bank_clear(guild_id)

        async with self.db._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO lotteries (guild_id, status, ticket_price, bonus_per_ticket, min_participants, split_first_bps, seed_amount, open_ts, close_ts, announce_channel_id) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                guild_id, "open",
                DEFAULT_TICKET_PRICE, DEFAULT_BONUS_PER_TICKET, DEFAULT_MIN_PARTICIPANTS,
                DEFAULT_SPLIT_FIRST_BPS, seed, open_ts, close_ts, channel_id
            )

        ch = self.bot.get_channel(channel_id)
        if isinstance(ch, discord.TextChannel):
            await ch.send(
                f"🎟️ **Daily Lottery is OPEN!** {'(auto)' if auto else ''}\n"
                f"• Ticket: {CURRENCY_ICON} **{DEFAULT_TICKET_PRICE:,}**  • Bonus: +{CURRENCY_ICON} **{DEFAULT_BONUS_PER_TICKET:,}** / ticket\n"
                f"• Seed (rollover): {CURRENCY_ICON} **{seed:,}**\n"
                f"• Payouts on player day: 🥇 {DEFAULT_SPLIT_FIRST_BPS/100:.2f}% / 🥈 {100 - DEFAULT_SPLIT_FIRST_BPS/100:.2f}%\n"
                f"• Closes: <t:{close_ts}:R>  (resets daily at **11:00 AM ET**)\n\n"
                f"Buy with `/lottery buy quantity:<n>` • Check `/lottery-status`"
            )

    async def _close_and_settle_or_rollover_locked(self, guild_id: int, lottery_id: int, force_rollover: bool):
        async with self.db._pool.acquire() as conn:
            lot = await conn.fetchrow("SELECT * FROM lotteries WHERE id=$1", lottery_id)
            if not lot or lot["status"] != "open":
                print(f"lottery {lottery_id}: not found or not open (status: {lot['status'] if lot else 'not found'})")
                return

            print(f"lottery {lottery_id}: closing lottery in channel {lot['announce_channel_id']}")
            await conn.execute("UPDATE lotteries SET status='drawing' WHERE id=$1", lottery_id)

            ch = self.bot.get_channel(int(lot["announce_channel_id"]))
            if not ch:
                print(f"lottery {lottery_id}: channel {lot['announce_channel_id']} not found!")
                return

            qty, gross_paid, bonus = await self._pot_components(lottery_id)
            seed = int(lot["seed_amount"])
            total_pot = seed + gross_paid + bonus

            # Unique participants check
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS u FROM tickets WHERE lottery_id=$1 AND tickets.quantity>0",
                lottery_id
            )
            unique_participants = int(row["u"])
            min_p = int(lot["min_participants"])

            do_rollover = force_rollover or (unique_participants < min_p)

            # House check (hidden from users)
            if not do_rollover and qty > 0:
                house_tickets = _house_tickets_for(qty)
                total_for_house_draw = qty + house_tickets
                if house_tickets > 0 and total_for_house_draw > 0:
                    r = random.SystemRandom().randrange(1, total_for_house_draw + 1)
                    if r <= house_tickets:
                        do_rollover = True  # House wins

            if do_rollover:
                await self._bank_add(guild_id, total_pot)
                await conn.execute("UPDATE lotteries SET status='rolled' WHERE id=$1", lottery_id)

                if isinstance(ch, discord.TextChannel):
                    if force_rollover:
                        reason_txt = "forced no-winner"
                    elif unique_participants < min_p:
                        reason_txt = f"need ≥ {min_p} participants"
                    else:
                        reason_txt = "💀 The House devoured the pot!"
                    await ch.send(
                        f"🔁 **Daily Lottery rolled over** — {reason_txt}.\n"
                        f"→ {CURRENCY_ICON} **{total_pot:,}** carried to tomorrow's 11:00 AM ET round."
                    )
                return

            # Player day — draw winners & pay out
            entries = [(int(r["user_id"]), int(r["quantity"])) for r in await conn.fetch(
                "SELECT user_id, tickets.quantity FROM tickets WHERE lottery_id=$1 AND tickets.quantity>0",
                lottery_id
            )]

            w1, w2 = weighted_draw_two(entries)
            split_first = int(lot["split_first_bps"]) / 10000.0
            first_amt = int(math.floor(total_pot * split_first))
            second_amt = total_pot - first_amt
            draw_ts = now_i()

            try:
                await self._credit_prize(guild_id, w1, first_amt, "Daily Lottery prize (1st)")
                await conn.execute(
                    "INSERT INTO winners (lottery_id, place, user_id, prize_amount, draw_ts) VALUES ($1,$2,$3,$4,$5)",
                    lottery_id, 1, w1, first_amt, draw_ts
                )
                if w2 is not None:
                    await self._credit_prize(guild_id, w2, second_amt, "Daily Lottery prize (2nd)")
                    await conn.execute(
                        "INSERT INTO winners (lottery_id, place, user_id, prize_amount, draw_ts) VALUES ($1,$2,$3,$4,$5)",
                        lottery_id, 2, w2, second_amt, draw_ts
                    )
                else:
                    # Only one unique entrant—give them second share too
                    await self._credit_prize(guild_id, w1, second_amt, "Daily Lottery prize (only participant bonus)")
                    await conn.execute(
                        "INSERT INTO winners (lottery_id, place, user_id, prize_amount, draw_ts) VALUES ($1,$2,$3,$4,$5)",
                        lottery_id, 2, w1, second_amt, draw_ts
                    )
            except Exception as e:
                print("payout error:", e)

            await conn.execute("UPDATE lotteries SET status='settled' WHERE id=$1", lottery_id)

        if isinstance(ch, discord.TextChannel):
            await ch.send(
                f"🏁 **Daily Lottery finished!**\n"
                f"• Tickets: **{qty:,}** • Seed: {CURRENCY_ICON} **{seed:,}**\n"
                f"• Gross (tickets): {CURRENCY_ICON} **{gross_paid:,}** • Bonus: {CURRENCY_ICON} **{bonus:,}**\n"
                f"• **Total pot:** {CURRENCY_ICON} **{total_pot:,}**\n"
                f"🥇 1st: <@{w1}> — {CURRENCY_ICON} **{first_amt:,}**\n"
                f"🥈 2nd: <@{w2 if w2 is not None else w1}> — {CURRENCY_ICON} **{second_amt:,}**"
            )

    # =================== Slash Commands ===================

    @app_commands.command(name="lottery-open", description="(Admin) Set the daily channel and open the current 24h round.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(announce_channel="Channel to announce & run daily rounds")
    async def open_cmd(self, inter: discord.Interaction, announce_channel: Optional[discord.TextChannel] = None):
        await inter.response.defer(ephemeral=True)
        ch = announce_channel or inter.channel

        now = datetime.now(DAILY_TZ)
        today_open = now.replace(hour=DAILY_HOUR, minute=DAILY_MINUTE, second=0, microsecond=0)
        open_ts = int(today_open.timestamp())
        close_ts = int((today_open + timedelta(days=1)).timestamp())  # TODO: revert this for production
        # close_ts = open_ts + 2 * 60  # 2 minutes for testing

        async with self._lock(inter.guild_id):
            # Check if there's already an open lottery in this channel
            async with self.db._pool.acquire() as conn:
                existing = await conn.fetchrow(
                    "SELECT id FROM lotteries WHERE guild_id=$1 AND status='open' AND announce_channel_id=$2",
                    inter.guild_id, ch.id
                )
                
                if existing:
                    return await inter.followup.send(
                        f"❌ There's already an open lottery in {ch.mention}. Use `/lottery-status` to check current lotteries.",
                        ephemeral=True
                    )
                
                await self._open_new_round(inter.guild_id, ch.id, open_ts, close_ts, auto=False)

        await inter.followup.send(f"✅ Daily lottery channel set to {ch.mention}. Round opened.", ephemeral=True)

    @app_commands.command(name="lottery-buy", description="Buy N tickets for the current (daily) lottery.")
    @is_admin_or_manager()
    @app_commands.describe(quantity="How many tickets to buy")
    @app_commands.describe(lottery_id="Specific lottery ID to buy into (optional)")
    async def buy_cmd(self, inter: discord.Interaction, quantity: app_commands.Range[int, 1, 1000], lottery_id: Optional[int] = None):
        await inter.response.defer(ephemeral=True)
        L = self._lock(inter.guild_id)
        async with L:
            # If specific lottery ID provided, use that
            if lottery_id:
                async with self.db._pool.acquire() as conn:
                    lot = await conn.fetchrow(
                        "SELECT * FROM lotteries WHERE id=$1 AND guild_id=$2 AND status='open'",
                        lottery_id, inter.guild_id
                    )
                    if not lot:
                        return await inter.followup.send(f"❌ Lottery #{lottery_id} not found or not open.", ephemeral=True)
            else:
                # First, try to find a lottery in the current channel
                async with self.db._pool.acquire() as conn:
                    lot = await conn.fetchrow(
                        "SELECT * FROM lotteries WHERE guild_id=$1 AND status='open' AND announce_channel_id=$2 ORDER BY id DESC LIMIT 1",
                        inter.guild_id, inter.channel.id
                    )
                    
                    # If no lottery in current channel, fall back to any open lottery
                    if not lot:
                        lot = await self._current_open(inter.guild_id)
                        if lot:
                            ch = self.bot.get_channel(int(lot["announce_channel_id"]))
                            channel_name = ch.name if ch else f"<#{lot['announce_channel_id']}>"
                            return await inter.followup.send(
                                f"❌ No lottery open in this channel.",
                                ephemeral=True
                            )
            
            if not lot or now_i() >= int(lot["close_ts"]):
                return await inter.followup.send("No open daily lottery to buy into.", ephemeral=True)

            q = int(quantity)
            price = int(lot["ticket_price"])
            cost = q * price

            try:
                # Check if user has sufficient balance
                # if not await self.db.check_balance(inter.user.id, inter.guild_id, cost):
                    # user_balance = await self.db.get_user_balance(inter.user.id, inter.guild_id)
                    # return await inter.followup.send(
                    #     f"❌ Not enough {CURRENCY_ICON}. You have **{user_balance.cash:,}**, need **{cost:,}** "
                    #     f"for **{q}** ticket(s) (price **{price:,}** each).",
                    #     ephemeral=True
                    # )
                
                # Deduct the cost from user's cash
                success = await self.db.deduct_cash(
                    inter.user.id, inter.guild_id, cost, 
                    reason=f"Daily Lottery tickets x{q}"
                )
                
                if not success:
                    user_balance = await self.db.get_user_balance(inter.user.id, inter.guild_id)
                    return await inter.followup.send(
                        f"❌ Not enough {CURRENCY_ICON}. You have **{user_balance.cash:,}**, need **{cost:,}** "
                        f"for **{q}** ticket(s) (price **{price:,}** each).",
                        ephemeral=True
                    )
                    
            except Exception as e:
                return await inter.followup.send(f"Payment error: {e}", ephemeral=True)

            async with self.db._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO tickets (lottery_id, user_id, quantity, amount_paid) VALUES ($1,$2,$3,$4) "
                    "ON CONFLICT(lottery_id, user_id) DO UPDATE SET "
                    "quantity = tickets.quantity + EXCLUDED.quantity, "
                    "amount_paid = tickets.amount_paid + EXCLUDED.amount_paid",
                    int(lot["id"]), inter.user.id, q, cost
                )

                bonus_per_ticket = int(lot["bonus_per_ticket"])
                pot_delta = q * (price + bonus_per_ticket)

                row = await conn.fetchrow(
                    "SELECT tickets.quantity FROM tickets WHERE lottery_id=$1 AND user_id=$2",
                    int(lot["id"]), inter.user.id
                )
                user_qty = int(row["quantity"]) if row else q

        ch = self.bot.get_channel(int(lot["announce_channel_id"]))
        channel_name = ch.name if ch else f"<#{lot['announce_channel_id']}>"
        
        await inter.followup.send(
            f"✅ Bought **{q}** ticket(s) for Lottery #{lot['id']} in #{channel_name}.\n"
            f"Your total: **{user_qty:,}** tickets.\n"
            f"Pot increased by {CURRENCY_ICON} **{pot_delta:,}** "
            f"(includes +{CURRENCY_ICON} {bonus_per_ticket:,} / ticket).",
            ephemeral=True
        )

    @app_commands.command(name="lottery-status", description="Show current daily lottery-status.")
    @is_admin_or_manager()
    async def status_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        
        # First, try to find a lottery in the current channel
        async with self.db._pool.acquire() as conn:
            lot = await conn.fetchrow(
                "SELECT * FROM lotteries WHERE guild_id=$1 AND status='open' AND announce_channel_id=$2 ORDER BY id DESC LIMIT 1",
                inter.guild_id, inter.channel.id
            )
            
            # If no lottery in current channel, show any open lottery
            if not lot:
                lot = await self._current_open(inter.guild_id)
                if not lot:
                    bank = await self._bank_get(inter.guild_id)
                    return await inter.followup.send(
                        f"🎟️ Daily Lottery is **idle**. Next round auto-opens at **11:00 AM ET**.\n"
                        f"Rollover bank: {CURRENCY_ICON} **{bank:,}**",
                        ephemeral=True
                    )
                else:
                    # Show lottery from different channel
                    ch = self.bot.get_channel(int(lot["announce_channel_id"]))
                    channel_name = ch.name if ch else f"<#{lot['announce_channel_id']}>"
                    return await inter.followup.send(
                        f"🎟️ **No lottery in this channel.**\n"
                        f"There's a lottery open in #{channel_name}.",
                        ephemeral=True
                    )

            qty, gross_paid, bonus = await self._pot_components(int(lot["id"]))
            seed = int(lot["seed_amount"])
            total_pot = seed + gross_paid + bonus

            row = await conn.fetchrow(
                "SELECT COUNT(*) u FROM tickets WHERE lottery_id=$1 AND tickets.quantity>0",
                int(lot["id"])
            )
            participants = int(row["u"])

        await inter.followup.send(
            f"🎟️ **Daily Lottery OPEN**\n"
            f"• Ticket: {CURRENCY_ICON} **{int(lot['ticket_price']):,}**  • Bonus: {CURRENCY_ICON} **{int(lot['bonus_per_ticket']):,}** / ticket\n"
            f"• Seed: {CURRENCY_ICON} **{seed:,}**  • Participants: **{participants}**  • Tickets: **{qty:,}**\n"
            f"• Gross: {CURRENCY_ICON} **{gross_paid:,}**  • Bonus: {CURRENCY_ICON} **{bonus:,}**\n"
            f"• **Total pot:** {CURRENCY_ICON} **{total_pot:,}**\n"
            f"• Closes: <t:{int(lot['close_ts'])}:R> (<t:{int(lot['close_ts'])}:f>)",
            ephemeral=True
        )

    @app_commands.command(name="lottery-list", description="List all currently open lotteries.")
    @is_admin_or_manager()
    async def list_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        
        # Get all open lotteries for this guild
        async with self.db._pool.acquire() as conn:
            lots = await conn.fetch(
                "SELECT id, announce_channel_id, open_ts, close_ts FROM lotteries WHERE guild_id=$1 AND status='open' ORDER BY id ASC",
                inter.guild_id
            )
        
        if not lots:
            bank = await self._bank_get(inter.guild_id)
            return await inter.followup.send(
                f"🎟️ **No open lotteries** in this server.\n"
                f"Rollover bank: {CURRENCY_ICON} **{bank:,}**",
                ephemeral=True
            )
        
        lines = []
        for lot in lots:
            ch = self.bot.get_channel(int(lot["announce_channel_id"]))
            channel_name = ch.name if ch else f"<#{lot['announce_channel_id']}>"
            
            qty, gross_paid, bonus = await self._pot_components(int(lot["id"]))
            seed = await self._bank_get(inter.guild_id) if int(lot["id"]) == lots[0]["id"] else 0  # Only show seed for first lottery
            total_pot = seed + gross_paid + bonus
            
            async with self.db._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) u FROM tickets WHERE lottery_id=$1 AND tickets.quantity>0",
                    int(lot["id"])
                )
            participants = int(row["u"])
        
            lines.append(
                f"**Lottery #{lot['id']}** in #{channel_name}\n"
                f"• Participants: **{participants}** • Tickets: **{qty:,}**\n"
                f"• Pot: {CURRENCY_ICON} **{total_pot:,}** • Closes: <t:{int(lot['close_ts'])}:R>"
            )
        
        await inter.followup.send(
            f"🎟️ **Open Lotteries ({len(lots)}):**\n\n" + "\n\n".join(lines),
            ephemeral=True
        )

    @app_commands.command(name="lottery-draw", description="(Admin) Force close now.")
    @app_commands.default_permissions(administrator=True)
    async def draw_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        async with self._lock(inter.guild_id):
            # First, try to find a lottery in the current channel
            async with self.db._pool.acquire() as conn:
                lot = await conn.fetchrow(
                    "SELECT * FROM lotteries WHERE guild_id=$1 AND status='open' AND announce_channel_id=$2 ORDER BY id DESC LIMIT 1",
                    inter.guild_id, inter.channel.id
                )
                
                # If no lottery in current channel, fall back to any open lottery
                if not lot:
                    lot = await self._current_open(inter.guild_id)
                    if not lot:
                        return await inter.followup.send("No open daily lottery to draw.", ephemeral=True)
                    else:
                        ch = self.bot.get_channel(int(lot["announce_channel_id"]))
                        channel_name = ch.name if ch else f"<#{lot['announce_channel_id']}>"
                        return await inter.followup.send(
                            f"❌ No lottery open in this channel.",
                            ephemeral=True
                        )
                
                await self._close_and_settle_or_rollover_locked(inter.guild_id, int(lot["id"]), force_rollover=False)
        await inter.followup.send("Processing end of round…", ephemeral=True)

    @app_commands.command(name="lottery-cancel", description="(Admin) Cancel and REFUND everyone (no rollover).")
    @app_commands.default_permissions(administrator=True)
    async def cancel_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        async with self._lock(inter.guild_id):
            # First, try to find a lottery in the current channel
            async with self.db._pool.acquire() as conn:
                lot = await conn.fetchrow(
                    "SELECT * FROM lotteries WHERE guild_id=$1 AND status='open' AND announce_channel_id=$2 ORDER BY id DESC LIMIT 1",
                    inter.guild_id, inter.channel.id
                )
                
                # If no lottery in current channel, fall back to any open lottery
                if not lot:
                    lot = await self._current_open(inter.guild_id)
                    if not lot:
                        return await inter.followup.send("No open daily lottery to cancel.", ephemeral=True)
                    else:
                        ch = self.bot.get_channel(int(lot["announce_channel_id"]))
                        channel_name = ch.name if ch else f"<#{lot['announce_channel_id']}>"
                        return await inter.followup.send(
                            f"❌ No lottery open in this channel.",
                            ephemeral=True
                        )

                await conn.execute("UPDATE lotteries SET status='drawing' WHERE id=$1", int(lot["id"]))

                # Refund all
                tickets = await conn.fetch("SELECT user_id, tickets.amount_paid FROM tickets WHERE lottery_id=$1", int(lot["id"]))
                for r in tickets:
                    uid = int(r["user_id"])
                    amt = int(r["amount_paid"])
                    if amt > 0:
                        try:
                            # Refunds go to cash (where tickets were purchased from)
                            await self.db.add_cash(
                                uid, inter.guild_id, amt, 
                                reason="Daily Lottery cancelled (admin)"
                            )
                        except Exception as e:
                            print(f"refund error uid={uid}: {e}")

                await conn.execute("UPDATE lotteries SET status='cancelled' WHERE id=$1", int(lot["id"]))

        await inter.followup.send("✅ Cancelled and refunded.", ephemeral=True)

    @app_commands.command(name="lottery-rollover", description="(Admin) Force no-winner and roll the pot to tomorrow.")
    @app_commands.default_permissions(administrator=True)
    async def rollover_nowinner_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        async with self._lock(inter.guild_id):
            # First, try to find a lottery in the current channel
            async with self.db._pool.acquire() as conn:
                lot = await conn.fetchrow(
                    "SELECT * FROM lotteries WHERE guild_id=$1 AND status='open' AND announce_channel_id=$2 ORDER BY id DESC LIMIT 1",
                    inter.guild_id, inter.channel.id
                )
                
                # If no lottery in current channel, fall back to any open lottery
                if not lot:
                    lot = await self._current_open(inter.guild_id)
                    if not lot:
                        return await inter.followup.send("No open daily lottery to rollover.", ephemeral=True)
                    else:
                        ch = self.bot.get_channel(int(lot["announce_channel_id"]))
                        channel_name = ch.name if ch else f"<#{lot['announce_channel_id']}>"
                        return await inter.followup.send(
                            f"❌ No lottery open in this channel.",
                            ephemeral=True
                        )
                
                await self._close_and_settle_or_rollover_locked(inter.guild_id, int(lot["id"]), force_rollover=True)
        await inter.followup.send("✅ Rolled over. Pot carried to tomorrow's 11:00 AM ET round.", ephemeral=True)

    @app_commands.command(name="lottery-history", description="Show recent daily results.")
    @is_admin_or_manager()
    async def history_cmd(self, inter: discord.Interaction, limit: app_commands.Range[int, 1, 10] = 5):
        await inter.response.defer(ephemeral=True)
        async with self.db._pool.acquire() as conn:
            lots = await conn.fetch(
                "SELECT id, status, seed_amount, open_ts, close_ts "
                "FROM lotteries WHERE guild_id=$1 AND status IN ('settled','rolled','cancelled') "
                "ORDER BY id DESC LIMIT $2",
                inter.guild_id, int(limit)
            )

        if not lots:
            return await inter.followup.send("No past daily rounds yet.", ephemeral=True)

        lines = []
        for lot in lots:
            lot_id = int(lot["id"])
            qty, gross_paid, bonus = await self._pot_components(lot_id)
            total_pot = int(lot["seed_amount"]) + gross_paid + bonus

            winners = await conn.fetch(
                "SELECT place, user_id, prize_amount FROM winners WHERE lottery_id=$1 ORDER BY place ASC",
                lot_id
            )

            if winners and lot["status"] == "settled":
                wt = " • ".join(
                    f"#{int(w['place'])}: <@{int(w['user_id'])}> ({CURRENCY_ICON} {int(w['prize_amount']):,})"
                    for w in winners
                )
            else:
                wt = "No winner (rolled or cancelled)"

            lines.append(
                f"**#{lot_id}** [{lot['status']}]: Pot {CURRENCY_ICON} **{total_pot:,}** • Tickets **{qty:,}**\n"
                f"Open <t:{int(lot['open_ts'])}:f> → Close <t:{int(lot['close_ts'])}:f>\n→ {wt}"
            )

        await inter.followup.send("\n\n".join(lines)[:1995], ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(LotteryDaily(bot))
