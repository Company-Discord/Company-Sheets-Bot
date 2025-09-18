# lottery_daily.py — Daily Lottery (UnbelievaBoat) with House mechanic (ratio hidden from users)
# Requires: discord.py 2.x, aiohttp, aiosqlite, Python 3.10+ (for zoneinfo)

import os
import math
import time
import random
import asyncio
from typing import Optional, Dict, List, Tuple
import pytz
from datetime import datetime, timedelta

import aiosqlite
import discord
from discord.ext import commands, tasks
from discord import app_commands

# =================== Config (env) ===================

UNB_ICON = os.getenv("CURRENCY_EMOTE", "💵")

DB_PATH = os.getenv("LOTTERY_DB_PATH", "/data/lottery.db")

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


# =================== Import External APIs ===================

# Import UnbelievaBoat utilities
from utils import (
    get_unb_client, credit_user, debit_user, get_user_balance
)
from unbelievaboat_api import UnbelievaBoatError

# Custom lottery exceptions
class InsufficientFunds(UnbelievaBoatError):
    pass



# =================== DB Schema ===================

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS lotteries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id INTEGER NOT NULL,
  status TEXT NOT NULL,                  -- 'open' | 'drawing' | 'settled' | 'cancelled' | 'rolled'
  ticket_price INTEGER NOT NULL,
  bonus_per_ticket INTEGER NOT NULL,
  min_participants INTEGER NOT NULL,
  split_first_bps INTEGER NOT NULL,
  seed_amount INTEGER NOT NULL,
  open_ts INTEGER NOT NULL,
  close_ts INTEGER NOT NULL,
  announce_channel_id INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lotteries_open ON lotteries(guild_id, status);

CREATE TABLE IF NOT EXISTS tickets (
  lottery_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  quantity INTEGER NOT NULL,
  amount_paid INTEGER NOT NULL,
  PRIMARY KEY (lottery_id, user_id)
);

CREATE TABLE IF NOT EXISTS winners (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lottery_id INTEGER NOT NULL,
  place INTEGER NOT NULL,                -- 1 or 2
  user_id INTEGER NOT NULL,
  prize_amount INTEGER NOT NULL,
  draw_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rollover_bank (
  guild_id INTEGER PRIMARY KEY,
  amount INTEGER NOT NULL
);
"""


# =================== Helpers ===================

def now_i() -> int:
    return int(time.time())


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

class LotteryDaily(commands.Cog):
    """Daily UnbelievaBoat Lottery with rollover and House mechanic (ratio hidden)."""

    group = app_commands.Group(name="lottery", description="Daily UnbelievaBoat Lottery")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: Optional[aiosqlite.Connection] = None
        self._locks: Dict[int, asyncio.Lock] = {}
        # Configuration for prize payouts (bank vs cash)
        self.payout_to_bank = os.getenv("LOTTERY_PAYOUT_TO", "bank").lower() == "bank"

        self.sweeper.start()
        self.opener.start()

    def cog_unload(self):
        self.sweeper.cancel()
        self.opener.cancel()

    # ---------- DB ----------
    async def _get_db(self) -> aiosqlite.Connection:
        if not self.db:
            try:
                os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
            except Exception:
                pass
            self.db = await aiosqlite.connect(DB_PATH)
            self.db.row_factory = aiosqlite.Row
            await self.db.executescript(SCHEMA)
            await self.db.commit()
        return self.db

    def _lock(self, guild_id: int) -> asyncio.Lock:
        L = self._locks.get(guild_id)
        if not L:
            L = asyncio.Lock()
            self._locks[guild_id] = L
        return L

    async def _credit_prize(self, guild_id: int, user_id: int, amount: int, reason: str):
        """Credit a lottery prize to user's account (bank or cash based on config)."""
        if self.payout_to_bank:
            # Use the unbelievaboat_api client directly for bank credits
            unb_client = get_unb_client()
            await unb_client.update_user_balance(guild_id, user_id, bank=amount, reason=reason)
        else:
            # Use utils for cash credits
            await credit_user(guild_id, user_id, amount, reason)

    async def _last_channel_or_none(self, guild_id: int) -> Optional[int]:
        db = await self._get_db()
        row = await (await db.execute(
            "SELECT announce_channel_id FROM lotteries WHERE guild_id=? ORDER BY id DESC LIMIT 1",
            (guild_id,)
        )).fetchone()
        return int(row["announce_channel_id"]) if row else None

    async def _current_open(self, guild_id: int) -> Optional[aiosqlite.Row]:
        db = await self._get_db()
        return await (await db.execute(
            "SELECT * FROM lotteries WHERE guild_id=? AND status='open' ORDER BY id DESC LIMIT 1",
            (guild_id,)
        )).fetchone()

    async def _pot_components(self, lottery_id: int) -> Tuple[int, int, int]:
        """Return (tickets_qty, gross_paid, bonus_added)."""
        db = await self._get_db()
        lot = await (await db.execute("SELECT * FROM lotteries WHERE id=?", (lottery_id,))).fetchone()
        if not lot:
            return (0, 0, 0)
        row = await (await db.execute(
            "SELECT COALESCE(SUM(quantity),0) q, COALESCE(SUM(amount_paid),0) p FROM tickets WHERE lottery_id=?",
            (lottery_id,)
        )).fetchone()
        qty = int(row["q"])
        paid = int(row["p"])
        bonus = qty * int(lot["bonus_per_ticket"])
        return (qty, paid, bonus)

    async def _bank_get(self, guild_id: int) -> int:
        db = await self._get_db()
        row = await (await db.execute("SELECT amount FROM rollover_bank WHERE guild_id=?", (guild_id,))).fetchone()
        return int(row["amount"]) if row else 0

    async def _bank_add(self, guild_id: int, amount: int):
        db = await self._get_db()
        await db.execute(
            "INSERT INTO rollover_bank (guild_id, amount) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET amount = amount + EXCLUDED.amount",
            (guild_id, int(max(0, amount)))
        )
        await db.commit()

    async def _bank_clear(self, guild_id: int) -> int:
        db = await self._get_db()
        amt = await self._bank_get(guild_id)
        await db.execute(
            "INSERT INTO rollover_bank (guild_id, amount) VALUES (?, 0) "
            "ON CONFLICT(guild_id) DO UPDATE SET amount=0",
            (guild_id,)
        )
        await db.commit()
        return amt

    # ---------- Background: close at end of window ----------
    @tasks.loop(seconds=60)
    async def sweeper(self):
        try:
            db = await self._get_db()
            now = now_i()
            async with db.execute(
                "SELECT id, guild_id FROM lotteries WHERE status='open' AND close_ts <= ?",
                (now,)
            ) as cur:
                rows = await cur.fetchall()
            for r in rows:
                gid = int(r["guild_id"])
                async with self._lock(gid):
                    await self._close_and_settle_or_rollover_locked(gid, int(r["id"]), force_rollover=False)
        except Exception as e:
            print("lottery sweeper error:", e)

    @sweeper.before_loop
    async def before_sweeper(self):
        await self.bot.wait_until_ready()

    # ---------- Background: open at 11:00 ET ----------
    @tasks.loop(seconds=60)
    async def opener(self):
        try:
            await self._get_db()
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
        db = await self._get_db()
        seed = await self._bank_clear(guild_id)

        await db.execute(
            "INSERT INTO lotteries (guild_id, status, ticket_price, bonus_per_ticket, min_participants, split_first_bps, seed_amount, open_ts, close_ts, announce_channel_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                guild_id, "open",
                DEFAULT_TICKET_PRICE, DEFAULT_BONUS_PER_TICKET, DEFAULT_MIN_PARTICIPANTS,
                DEFAULT_SPLIT_FIRST_BPS, seed, open_ts, close_ts, channel_id
            )
        )
        await db.commit()

        ch = self.bot.get_channel(channel_id)
        if isinstance(ch, discord.TextChannel):
            await ch.send(
                f"🎟️ **Daily Lottery is OPEN!** {'(auto)' if auto else ''}\n"
                f"• Ticket: {UNB_ICON} **{DEFAULT_TICKET_PRICE:,}**  • Bonus: +{UNB_ICON} **{DEFAULT_BONUS_PER_TICKET:,}** / ticket\n"
                f"• Seed (rollover): {UNB_ICON} **{seed:,}**\n"
                f"• Payouts on player day: 🥇 {DEFAULT_SPLIT_FIRST_BPS/100:.2f}% / 🥈 {100 - DEFAULT_SPLIT_FIRST_BPS/100:.2f}%\n"
                f"• Closes: <t:{close_ts}:R>  (resets daily at **11:00 AM ET**)\n\n"
                f"Buy with `/lottery buy quantity:<n>` • Check `/lottery status`"
            )

    async def _close_and_settle_or_rollover_locked(self, guild_id: int, lottery_id: int, force_rollover: bool):
        db = await self._get_db()
        lot = await (await db.execute("SELECT * FROM lotteries WHERE id=?", (lottery_id,))).fetchone()
        if not lot or lot["status"] != "open":
            return

        await db.execute("UPDATE lotteries SET status='drawing' WHERE id=?", (lottery_id,))
        await db.commit()

        ch = self.bot.get_channel(int(lot["announce_channel_id"]))

        qty, gross_paid, bonus = await self._pot_components(lottery_id)
        seed = int(lot["seed_amount"])
        total_pot = seed + gross_paid + bonus

        # Unique participants check
        row = await (await db.execute(
            "SELECT COUNT(*) AS u FROM tickets WHERE lottery_id=? AND quantity>0",
            (lottery_id,)
        )).fetchone()
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
            await db.execute("UPDATE lotteries SET status='rolled' WHERE id=?", (lottery_id,))
            await db.commit()

            if isinstance(ch, discord.TextChannel):
                if force_rollover:
                    reason_txt = "forced no-winner"
                elif unique_participants < min_p:
                    reason_txt = f"need ≥ {min_p} participants"
                else:
                    reason_txt = "💀 The House devoured the pot!"
                await ch.send(
                    f"🔁 **Daily Lottery rolled over** — {reason_txt}.\n"
                    f"→ {UNB_ICON} **{total_pot:,}** carried to tomorrow’s 11:00 AM ET round."
                )
            return

        # Player day — draw winners & pay out
        entries = [(int(r["user_id"]), int(r["quantity"])) for r in await (await db.execute(
            "SELECT user_id, quantity FROM tickets WHERE lottery_id=? AND quantity>0",
            (lottery_id,)
        )).fetchall()]

        w1, w2 = weighted_draw_two(entries)
        split_first = int(lot["split_first_bps"]) / 10000.0
        first_amt = int(math.floor(total_pot * split_first))
        second_amt = total_pot - first_amt
        draw_ts = now_i()

        try:
            await self._credit_prize(guild_id, w1, first_amt, "Daily Lottery prize (1st)")
            await db.execute(
                "INSERT INTO winners (lottery_id, place, user_id, prize_amount, draw_ts) VALUES (?,?,?,?,?)",
                (lottery_id, 1, w1, first_amt, draw_ts)
            )
            if w2 is not None:
                await self._credit_prize(guild_id, w2, second_amt, "Daily Lottery prize (2nd)")
                await db.execute(
                    "INSERT INTO winners (lottery_id, place, user_id, prize_amount, draw_ts) VALUES (?,?,?,?,?)",
                    (lottery_id, 2, w2, second_amt, draw_ts)
                )
            else:
                # Only one unique entrant—give them second share too
                await self._credit_prize(guild_id, w1, second_amt, "Daily Lottery prize (only participant bonus)")
                await db.execute(
                    "INSERT INTO winners (lottery_id, place, user_id, prize_amount, draw_ts) VALUES (?,?,?,?,?)",
                    (lottery_id, 2, w1, second_amt, draw_ts)
                )
        except Exception as e:
            print("payout error:", e)

        await db.execute("UPDATE lotteries SET status='settled' WHERE id=?", (lottery_id,))
        await db.commit()

        if isinstance(ch, discord.TextChannel):
            await ch.send(
                f"🏁 **Daily Lottery finished!**\n"
                f"• Tickets: **{qty:,}** • Seed: {UNB_ICON} **{seed:,}**\n"
                f"• Gross (tickets): {UNB_ICON} **{gross_paid:,}** • Bonus: {UNB_ICON} **{bonus:,}**\n"
                f"• **Total pot:** {UNB_ICON} **{total_pot:,}**\n"
                f"🥇 1st: <@{w1}> — {UNB_ICON} **{first_amt:,}**\n"
                f"🥈 2nd: <@{w2 if w2 is not None else w1}> — {UNB_ICON} **{second_amt:,}**"
            )

    # =================== Slash Commands ===================

    @group.command(name="open", description="(Admin) Set the daily channel and open the current 24h round.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(announce_channel="Channel to announce & run daily rounds")
    async def open_cmd(self, inter: discord.Interaction, announce_channel: Optional[discord.TextChannel] = None):
        await inter.response.defer(ephemeral=True)
        ch = announce_channel or inter.channel

        now = datetime.now(DAILY_TZ)
        today_open = now.replace(hour=DAILY_HOUR, minute=DAILY_MINUTE, second=0, microsecond=0)
        open_ts = int(today_open.timestamp())
        close_ts = int((today_open + timedelta(days=1)).timestamp())

        async with self._lock(inter.guild_id):
            await self._open_new_round(inter.guild_id, ch.id, open_ts, close_ts, auto=False)

        await inter.followup.send(f"✅ Daily lottery channel set to {ch.mention}. Round opened.", ephemeral=True)

    @group.command(name="buy", description="Buy N tickets for the current (daily) lottery.")
    @app_commands.describe(quantity="How many tickets to buy")
    async def buy_cmd(self, inter: discord.Interaction, quantity: app_commands.Range[int, 1, 1000]):
        await inter.response.defer(ephemeral=True)
        L = self._lock(inter.guild_id)
        async with L:
            db = await self._get_db()
            lot = await self._current_open(inter.guild_id)
            if not lot or now_i() >= int(lot["close_ts"]):
                return await inter.followup.send("No open daily lottery to buy into.", ephemeral=True)

            q = int(quantity)
            price = int(lot["ticket_price"])
            cost = q * price

            try:
                await debit_user(inter.guild_id, inter.user.id, cost, reason=f"Daily Lottery tickets x{q}")
            except (InsufficientFunds, UnbelievaBoatError) as e:
                if "insufficient" in str(e).lower():
                    bal = await get_user_balance(inter.guild_id, inter.user.id)
                    return await inter.followup.send(
                        f"❌ Not enough {UNB_ICON}. You have **{bal:,}**, need **{cost:,}** "
                        f"for **{q}** ticket(s) (price **{price:,}** each).",
                        ephemeral=True
                    )
                else:
                    raise
            except Exception as e:
                return await inter.followup.send(f"Payment error: {e}", ephemeral=True)

            await db.execute(
                "INSERT INTO tickets (lottery_id, user_id, quantity, amount_paid) VALUES (?,?,?,?) "
                "ON CONFLICT(lottery_id, user_id) DO UPDATE SET "
                "quantity = quantity + EXCLUDED.quantity, "
                "amount_paid = amount_paid + EXCLUDED.amount_paid",
                (int(lot["id"]), inter.user.id, q, cost)
            )
            await db.commit()

            bonus_per_ticket = int(lot["bonus_per_ticket"])
            pot_delta = q * (price + bonus_per_ticket)

            row = await (await db.execute(
                "SELECT quantity FROM tickets WHERE lottery_id=? AND user_id=?",
                (int(lot["id"]), inter.user.id)
            )).fetchone()
            user_qty = int(row["quantity"]) if row else q

        await inter.followup.send(
            f"✅ Bought **{q}** ticket(s). Your total: **{user_qty:,}**.\n"
            f"Pot increased by {UNB_ICON} **{pot_delta:,}** "
            f"(includes +{UNB_ICON} {bonus_per_ticket:,} / ticket).",
            ephemeral=True
        )

    @group.command(name="status", description="Show current daily lottery status.")
    async def status_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        db = await self._get_db()
        lot = await self._current_open(inter.guild_id)
        if not lot:
            bank = await self._bank_get(inter.guild_id)
            return await inter.followup.send(
                f"🎟️ Daily Lottery is **idle**. Next round auto-opens at **11:00 AM ET**.\n"
                f"Rollover bank: {UNB_ICON} **{bank:,}**",
                ephemeral=True
            )

        qty, gross_paid, bonus = await self._pot_components(int(lot["id"]))
        seed = int(lot["seed_amount"])
        total_pot = seed + gross_paid + bonus

        row = await (await db.execute(
            "SELECT COUNT(*) u FROM tickets WHERE lottery_id=? AND quantity>0",
            (int(lot["id"]),)
        )).fetchone()
        participants = int(row["u"])

        await inter.followup.send(
            f"🎟️ **Daily Lottery OPEN**\n"
            f"• Ticket: {UNB_ICON} **{int(lot['ticket_price']):,}**  • Bonus: {UNB_ICON} **{int(lot['bonus_per_ticket']):,}** / ticket\n"
            f"• Seed: {UNB_ICON} **{seed:,}**  • Participants: **{participants}**  • Tickets: **{qty:,}**\n"
            f"• Gross: {UNB_ICON} **{gross_paid:,}**  • Bonus: {UNB_ICON} **{bonus:,}**\n"
            f"• **Total pot:** {UNB_ICON} **{total_pot:,}**\n"
            f"• Closes: <t:{int(lot['close_ts'])}:R> (<t:{int(lot['close_ts'])}:f>)",
            ephemeral=True
        )

    @group.command(name="draw", description="(Admin) Force close now.")
    @app_commands.default_permissions(administrator=True)
    async def draw_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        async with self._lock(inter.guild_id):
            db = await self._get_db()
            lot = await self._current_open(inter.guild_id)
            if not lot:
                return await inter.followup.send("No open daily lottery to draw.", ephemeral=True)
            await self._close_and_settle_or_rollover_locked(inter.guild_id, int(lot["id"]), force_rollover=False)
        await inter.followup.send("Processing end of round…", ephemeral=True)

    @group.command(name="cancel", description="(Admin) Cancel and REFUND everyone (no rollover).")
    @app_commands.default_permissions(administrator=True)
    async def cancel_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        async with self._lock(inter.guild_id):
            db = await self._get_db()
            lot = await self._current_open(inter.guild_id)
            if not lot:
                return await inter.followup.send("No open daily lottery to cancel.", ephemeral=True)

            await db.execute("UPDATE lotteries SET status='drawing' WHERE id=?", (int(lot["id"]),))
            await db.commit()

            # Refund all
            async with db.execute("SELECT user_id, amount_paid FROM tickets WHERE lottery_id=?", (int(lot["id"]),)) as cur:
                for r in await cur.fetchall():
                    uid = int(r["user_id"])
                    amt = int(r["amount_paid"])
                    if amt > 0:
                        try:
                            # Refunds go to cash (where tickets were purchased from)
                            await credit_user(inter.guild_id, uid, amt, reason="Daily Lottery cancelled (admin)")
                        except Exception as e:
                            print(f"refund error uid={uid}: {e}")

            await db.execute("UPDATE lotteries SET status='cancelled' WHERE id=?", (int(lot["id"]),))
            await db.commit()

        await inter.followup.send("✅ Cancelled and refunded.", ephemeral=True)

    @group.command(name="rollover_nowinner", description="(Admin) Force no-winner and roll the pot to tomorrow.")
    @app_commands.default_permissions(administrator=True)
    async def rollover_nowinner_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        async with self._lock(inter.guild_id):
            db = await self._get_db()
            lot = await self._current_open(inter.guild_id)
            if not lot:
                return await inter.followup.send("No open daily lottery to rollover.", ephemeral=True)
            await self._close_and_settle_or_rollover_locked(inter.guild_id, int(lot["id"]), force_rollover=True)
        await inter.followup.send("✅ Rolled over. Pot carried to tomorrow’s 11:00 AM ET round.", ephemeral=True)

    @group.command(name="history", description="Show recent daily results.")
    async def history_cmd(self, inter: discord.Interaction, limit: app_commands.Range[int, 1, 10] = 5):
        await inter.response.defer(ephemeral=True)
        db = await self._get_db()
        lots = await (await db.execute(
            "SELECT id, status, seed_amount, open_ts, close_ts "
            "FROM lotteries WHERE guild_id=? AND status IN ('settled','rolled','cancelled') "
            "ORDER BY id DESC LIMIT ?",
            (inter.guild_id, int(limit))
        )).fetchall()

        if not lots:
            return await inter.followup.send("No past daily rounds yet.", ephemeral=True)

        lines = []
        for lot in lots:
            lot_id = int(lot["id"])
            qty, gross_paid, bonus = await self._pot_components(lot_id)
            total_pot = int(lot["seed_amount"]) + gross_paid + bonus

            winners = await (await db.execute(
                "SELECT place, user_id, prize_amount FROM winners WHERE lottery_id=? ORDER BY place ASC",
                (lot_id,)
            )).fetchall()

            if winners and lot["status"] == "settled":
                wt = " • ".join(
                    f"#{int(w['place'])}: <@{int(w['user_id'])}> ({UNB_ICON} {int(w['prize_amount']):,})"
                    for w in winners
                )
            else:
                wt = "No winner (rolled or cancelled)"

            lines.append(
                f"**#{lot_id}** [{lot['status']}]: Pot {UNB_ICON} **{total_pot:,}** • Tickets **{qty:,}**\n"
                f"Open <t:{int(lot['open_ts'])}:f> → Close <t:{int(lot['close_ts'])}:f>\n→ {wt}"
            )

        await inter.followup.send("\n\n".join(lines)[:1995], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LotteryDaily(bot))
