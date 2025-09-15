# predictions.py
import os
import time
import math
import uuid
from typing import Optional, Literal

import aiosqlite
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

DB_PATH = "predictions.db"
CURRENCY_ICON = os.getenv("CURRENCY_EMOJI")
if not CURRENCY_ICON:
    raise RuntimeError("CURRENCY_EMOJI must be set in your .env")
MIN_UNIQUE_BETTORS = int(os.getenv("PRED_MIN_UNIQUE", "4"))  # default 4

# ---------- Permissions ----------
def is_guild_admin():
    async def predicate(inter: discord.Interaction) -> bool:
        p = inter.user.guild_permissions
        return p.manage_guild or p.administrator
    return app_commands.check(predicate)

# ---------- Engauge Adapter (server-scoped) ----------
class EngaugeError(Exception):
    pass

class InsufficientFunds(EngaugeError):
    pass

class EngaugeAdapter:
    """
    Engauge currency client (server-scoped).
    Uses POST https://engau.ge/api/v1/servers/{server_id}/members/{member_id}/currency?amount=±N
    - amount > 0 => credit
    - amount < 0 => debit
    Auth: Authorization: Bearer ENGAUGE_API_TOKEN
    """
    def __init__(self):
        self.base = "https://engau.ge/api/v1"
        self.token = os.getenv("ENGAUGE_API_TOKEN") or os.getenv("ENGAUGE_TOKEN", "")
        if not self.token:
            raise RuntimeError("ENGAUGE_API_TOKEN must be set")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def adjust(self, server_id: int, member_id: int, amount: int):
        url = f"{self.base}/servers/{int(server_id)}/members/{int(member_id)}/currency"
        params = {"amount": str(int(amount))}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params, headers=self._headers()) as r:
                if r.status == 402:
                    raise InsufficientFunds("Insufficient Engauge balance")
                if r.status >= 400:
                    text = await r.text()
                    raise EngaugeError(f"Engauge HTTP {r.status}: {text}")
                # response body not strictly needed here, but we return it if present
                try:
                    return await r.json()
                except Exception:
                    return None

    async def debit(self, server_id: int, member_id: int, amount: int):
        return await self.adjust(server_id, member_id, -abs(int(amount)))

    async def credit(self, server_id: int, member_id: int, amount: int):
        return await self.adjust(server_id, member_id, abs(int(amount)))

# ---------- Cog ----------
class Predictions(commands.Cog):
    """
    Twitch-like Predictions using Engauge currency.
    - One active prediction per guild
    - Two outcomes, open window auto-locks
    - Auto-cancels at lock if unique bettors < MIN_UNIQUE_BETTORS
    - Admins: start/lock/resolve/cancel
    - Users: bet (can change before lock)
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: Optional[aiosqlite.Connection] = None
        self.engauge = EngaugeAdapter()
        self._lock_task.start()

    async def cog_load(self):
        self.db = await aiosqlite.connect(DB_PATH)
        self.db.row_factory = aiosqlite.Row
        await self._migrate()

    async def cog_unload(self):
        self._lock_task.cancel()
        if self.db:
            await self.db.close()

    async def _migrate(self):
        await self.db.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS predictions (
            guild_id      INTEGER PRIMARY KEY,
            title         TEXT NOT NULL,
            outcome_a     TEXT NOT NULL,
            outcome_b     TEXT NOT NULL,
            status        TEXT NOT NULL,  -- open, locked, resolved, canceled
            created_by    INTEGER NOT NULL,
            created_ts    INTEGER NOT NULL,
            lock_ts       INTEGER NOT NULL,
            resolved_ts   INTEGER
        );

        CREATE TABLE IF NOT EXISTS stakes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id      INTEGER NOT NULL,
            user_id       INTEGER NOT NULL,
            side          TEXT NOT NULL,  -- 'A' or 'B'
            amount        INTEGER NOT NULL,
            created_ts    INTEGER NOT NULL,
            UNIQUE(guild_id, user_id)
        );

        -- local idempotency log (tracking only; Engauge endpoint itself doesn't accept an idem key)
        CREATE TABLE IF NOT EXISTS tx_log (
            key           TEXT PRIMARY KEY,
            kind          TEXT NOT NULL,   -- 'debit'|'credit'
            guild_id      INTEGER NOT NULL,
            user_id       INTEGER NOT NULL,
            amount        INTEGER NOT NULL,
            created_ts    INTEGER NOT NULL
        );
        """)
        await self.db.commit()

    # ---------- Utilities ----------
    @staticmethod
    def now() -> int:
        return int(time.time())

    def fmt_amt(self, v: int) -> str:
        return f"{CURRENCY_ICON} {v:,}"

    async def current_pred(self, guild_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.db.execute("SELECT * FROM predictions WHERE guild_id = ?", (guild_id,))
        return await cur.fetchone()

    async def pools(self, guild_id: int) -> tuple[int, int]:
        cur = await self.db.execute(
            "SELECT side, SUM(amount) FROM stakes WHERE guild_id = ? GROUP BY side", (guild_id,)
        )
        sums = {"A": 0, "B": 0}
        for row in await cur.fetchall():
            side, s = row[0], row[1] or 0
            sums[side] = int(s)
        return sums["A"], sums["B"]

    async def unique_bettors(self, guild_id: int) -> int:
        cur = await self.db.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT user_id FROM stakes WHERE guild_id = ?)", (guild_id,)
        )
        row = await cur.fetchone()
        return int(row[0] if row else 0)

    async def add_tx(self, key: str, kind: str, guild_id: int, user_id: int, amount: int):
        try:
            await self.db.execute(
                "INSERT INTO tx_log (key, kind, guild_id, user_id, amount, created_ts) VALUES (?,?,?,?,?,?)",
                (key, kind, guild_id, user_id, amount, self.now()),
            )
            await self.db.commit()
        except Exception:
            # duplicate key is fine
            pass

    async def _refund_everyone(self, guild_id: int, reason_key: str):
        cur = await self.db.execute("SELECT user_id, amount FROM stakes WHERE guild_id=?", (guild_id,))
        rows = await cur.fetchall()
        for r in rows:
            uid, amt = int(r["user_id"]), int(r["amount"])
            if amt > 0:
                idem = f"{reason_key}:{guild_id}:{uid}:{uuid.uuid4()}"
                await self.engauge.credit(guild_id, uid, amt)
                await self.add_tx(idem, "credit", guild_id, uid, amt)
        await self.db.execute("DELETE FROM stakes WHERE guild_id=?", (guild_id,))
        await self.db.commit()

    # ---------- Background: auto-lock/auto-cancel ----------
    @tasks.loop(seconds=15)
    async def _lock_task(self):
        if not self.db: return
        now = self.now()
        cur = await self.db.execute(
            "SELECT guild_id, lock_ts FROM predictions WHERE status='open' AND lock_ts <= ?",
            (now,)
        )
        rows = await cur.fetchall()
        for r in rows:
            gid = r["guild_id"]
            # participation check
            bettors = await self.unique_bettors(gid)
            if bettors < MIN_UNIQUE_BETTORS:
                await self._refund_everyone(gid, "pred-auto-cancel")
                await self.db.execute("UPDATE predictions SET status='canceled' WHERE guild_id=?", (gid,))
                await self.db.commit()
                guild = self.bot.get_guild(gid)
                # Prefer the system channel; otherwise do nothing (no channel context)
                if guild and guild.system_channel:
                    await guild.system_channel.send(
                        f"❌ Prediction auto-canceled — fewer than {MIN_UNIQUE_BETTORS} participants."
                    )
                continue
            # otherwise lock
            await self.db.execute("UPDATE predictions SET status='locked' WHERE guild_id=?", (gid,))
            await self.db.commit()

    @_lock_task.before_loop
    async def _before_lock_task(self):
        await self.bot.wait_until_ready()

    # ---------- Embeds ----------
    async def make_embed(self, guild_id: int) -> Optional[discord.Embed]:
        p = await self.current_pred(guild_id)
        if not p:
            return None
        pool_a, pool_b = await self.pools(guild_id)
        total = pool_a + pool_b

        def mult(my_pool: int) -> str:
            if my_pool <= 0:
                return "—"
            return f"{total / my_pool:.2f}×"

        lock_ts = p["lock_ts"]
        rel = f"<t:{lock_ts}:R>"
        abs_t = f"<t:{lock_ts}:t>"

        e = discord.Embed(
            title="🔮 Prediction",
            description=(
                f"**{p['title']}**\n"
                f"**Status:** `{p['status'].upper()}`\n"
                f"⏳ **Time left:** {rel}  (locks at {abs_t})\n\n"
                f"**A)** {p['outcome_a']}\n"
                f"**B)** {p['outcome_b']}\n\n"
                f"⚠️ *Auto-cancels at lock if fewer than {MIN_UNIQUE_BETTORS} unique participants.*"
            ),
            color=discord.Color.blurple()
        )
        e.add_field(name="Pool A", value=self.fmt_amt(pool_a), inline=True)
        e.add_field(name="Pool B", value=self.fmt_amt(pool_b), inline=True)
        e.add_field(
            name="Current Odds (no rake)",
            value=f"A: {mult(pool_a)} | B: {mult(pool_b)}",
            inline=False
        )
        return e

    # ---------- Commands ----------
    group = app_commands.Group(name="pred", description="Twitch-like predictions")

    @group.command(name="start", description="Start a new prediction (admin)")
    @is_guild_admin()
    @app_commands.describe(
        title="Question/title (e.g., Who wins Map 1?)",
        outcome_a="Outcome A label",
        outcome_b="Outcome B label",
        open_minutes="How many minutes betting stays open"
    )
    async def start(
        self, inter: discord.Interaction,
        title: str,
        outcome_a: str,
        outcome_b: str,
        open_minutes: app_commands.Range[int, 1, 1440] = 10
    ):
        await inter.response.defer(thinking=True, ephemeral=True)
        existing = await self.current_pred(inter.guild_id)
        if existing and existing["status"] in ("open", "locked"):
            return await inter.followup.send("There is already an active prediction in this server.", ephemeral=True)

        lock_ts = self.now() + open_minutes * 60
        await self.db.execute(
            "REPLACE INTO predictions (guild_id,title,outcome_a,outcome_b,status,created_by,created_ts,lock_ts) "
            "VALUES (?,?,?,?, 'open', ?, ?, ?)",
            (inter.guild_id, title, outcome_a, outcome_b, inter.user.id, self.now(), lock_ts)
        )
        await self.db.execute("DELETE FROM stakes WHERE guild_id = ?", (inter.guild_id,))
        await self.db.commit()

        embed = await self.make_embed(inter.guild_id)
        await inter.followup.send(
            content=(
                f"Prediction started. Use **/pred bet** to participate!\n"
                f"⚠️ *Reminder: Auto-cancels at lock if fewer than {MIN_UNIQUE_BETTORS} people enter.*"
            ),
            embed=embed,
            ephemeral=True
        )
        # Public announce in the current channel
        if inter.channel:
            await inter.channel.send(
                content=(
                    f"A new prediction has begun! Use **/pred bet** to stake your {CURRENCY_ICON}\n"
                    f"⚠️ *Auto-cancels at lock if fewer than {MIN_UNIQUE_BETTORS} unique participants.*"
                ),
                embed=embed
            )

    @group.command(name="status", description="Show current prediction status")
    async def status(self, inter: discord.Interaction):
        p = await self.current_pred(inter.guild_id)
        if not p:
            return await inter.response.send_message("No active prediction.", ephemeral=True)
        embed = await self.make_embed(inter.guild_id)
        await inter.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="bet", description="Place or change your bet")
    @app_commands.describe(
        side="Choose outcome A or B",
        amount="Amount to stake (integer)"
    )
    async def bet(
        self, inter: discord.Interaction,
        side: Literal["A", "B"],
        amount: app_commands.Range[int, 1, 10_000_000]
    ):
        await inter.response.defer(ephemeral=True, thinking=True)
        p = await self.current_pred(inter.guild_id)
        if not p or p["status"] != "open":
            return await inter.followup.send("Betting is not open right now.", ephemeral=True)
        if self.now() >= p["lock_ts"]:
            await self.db.execute("UPDATE predictions SET status='locked' WHERE guild_id=?",(inter.guild_id,))
            await self.db.commit()
            return await inter.followup.send("Betting is now locked.", ephemeral=True)

        # If user has an existing stake, refund it first (credit back), then place the new one.
        cur = await self.db.execute(
            "SELECT side, amount FROM stakes WHERE guild_id=? AND user_id=?",
            (inter.guild_id, inter.user.id)
        )
        prev = await cur.fetchone()
        try:
            if prev:
                refund_amt = int(prev["amount"])
                if refund_amt > 0:
                    idem_refund = f"pred-refund:{inter.guild_id}:{inter.user.id}:{uuid.uuid4()}"
                    await self.engauge.credit(inter.guild_id, inter.user.id, refund_amt)
                    await self.add_tx(idem_refund, "credit", inter.guild_id, inter.user.id, refund_amt)
                await self.db.execute("DELETE FROM stakes WHERE guild_id=? AND user_id=?",
                                      (inter.guild_id, inter.user.id))
                await self.db.commit()

            # Charge for new amount
            idem_debit = f"pred-debit:{inter.guild_id}:{inter.user.id}:{uuid.uuid4()}"
            await self.engauge.debit(inter.guild_id, inter.user.id, amount)
            await self.add_tx(idem_debit, "debit", inter.guild_id, inter.user.id, amount)

            await self.db.execute(
                "INSERT INTO stakes (guild_id,user_id,side,amount,created_ts) VALUES (?,?,?,?,?)",
                (inter.guild_id, inter.user.id, side, int(amount), self.now())
            )
            await self.db.commit()

        except InsufficientFunds:
            return await inter.followup.send(f"You don't have enough {CURRENCY_ICON} for this bet", ephemeral=True)
        except EngaugeError as e:
            return await inter.followup.send(f"Engauge error: {e}", ephemeral=True)

        embed = await self.make_embed(inter.guild_id)
        await inter.followup.send(
            f"Bet placed on **{ 'A' if side=='A' else 'B' }** for **{self.fmt_amt(amount)}**.\n"
            f"⚠️ *Auto-cancels at lock if fewer than {MIN_UNIQUE_BETTORS} participants.*",
            embed=embed,
            ephemeral=True
        )

    @group.command(name="lock", description="Lock betting (admin)")
    @is_guild_admin()
    async def lock(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        p = await self.current_pred(inter.guild_id)
        if not p or p["status"] != "open":
            return await inter.followup.send("No open prediction to lock.", ephemeral=True)

        bettors = await self.unique_bettors(inter.guild_id)
        if bettors < MIN_UNIQUE_BETTORS:
            await self._refund_everyone(inter.guild_id, "pred-manual-auto-cancel")
            await self.db.execute("UPDATE predictions SET status='canceled' WHERE guild_id=?", (inter.guild_id,))
            await self.db.commit()
            await inter.followup.send(
                f"Prediction auto-canceled — fewer than {MIN_UNIQUE_BETTORS} participants.",
                ephemeral=True
            )
            if inter.channel:
                await inter.channel.send(
                    f"❌ Prediction auto-canceled — fewer than {MIN_UNIQUE_BETTORS} participants."
                )
            return

        await self.db.execute("UPDATE predictions SET status='locked' WHERE guild_id=?", (inter.guild_id,))
        await self.db.commit()
        await inter.followup.send("Betting locked.", ephemeral=True)
        if inter.channel:
            await inter.channel.send("🔒 Betting is now locked.")

    @group.command(name="cancel", description="Cancel the prediction and refund everyone (admin)")
    @is_guild_admin()
    async def cancel(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        p = await self.current_pred(inter.guild_id)
        if not p or p["status"] in ("canceled", "resolved"):
            return await inter.followup.send("No cancellable prediction.", ephemeral=True)

        await self._refund_everyone(inter.guild_id, "pred-cancel")
        await self.db.execute("UPDATE predictions SET status='canceled' WHERE guild_id=?", (inter.guild_id,))
        await self.db.commit()
        await inter.followup.send("Prediction canceled. All bets refunded.", ephemeral=True)
        if inter.channel:
            await inter.channel.send("❌ Prediction canceled — all stakes refunded.")

    @group.command(name="resolve", description="Resolve the prediction and pay winners (admin)")
    @is_guild_admin()
    @app_commands.describe(winner="Pick the winning outcome")
    async def resolve(self, inter: discord.Interaction, winner: Literal["A", "B"]):
        await inter.response.defer(ephemeral=True, thinking=True)
        p = await self.current_pred(inter.guild_id)
        if not p or p["status"] not in ("open", "locked"):
            return await inter.followup.send("No prediction ready to resolve.", ephemeral=True)

        # If still open (edge), enforce lock first without participation check
        if p["status"] == "open":
            await self.db.execute("UPDATE predictions SET status='locked' WHERE guild_id=?", (inter.guild_id,))
            await self.db.commit()

        pool_a, pool_b = await self.pools(inter.guild_id)
        total = pool_a + pool_b
        win_pool = pool_a if winner == "A" else pool_b

        if total <= 0 or win_pool <= 0:
            # no winners / degenerate: refund everyone
            await self._refund_everyone(inter.guild_id, "pred-resolve-refund")
            msg = "No valid winners; all stakes refunded."
        else:
            cur = await self.db.execute(
                "SELECT user_id, amount FROM stakes WHERE guild_id=? AND side=?",
                (inter.guild_id, winner)
            )
            winners = await cur.fetchall()
            for w in winners:
                uid = int(w["user_id"])
                a = int(w["amount"])
                payout = math.floor(a * total / win_pool) 
                if payout > 0:
                    idem = f"pred-payout:{inter.guild_id}:{uid}:{uuid.uuid4()}"
                    await self.engauge.credit(inter.guild_id, uid, payout)
                    await self.add_tx(idem, "credit", inter.guild_id, uid, payout)
            msg = f"Payouts sent to **Outcome {winner}** backers."

        await self.db.execute("DELETE FROM stakes WHERE guild_id=?", (inter.guild_id,))
        await self.db.execute(
            "UPDATE predictions SET status='resolved', resolved_ts=? WHERE guild_id=?",
            (self.now(), inter.guild_id)
        )
        await self.db.commit()

        await inter.followup.send("Resolved. " + msg, ephemeral=True)
        if inter.channel:
            embed = await self.make_embed(inter.guild_id)
            if embed:
                embed.title = "✅ Prediction Resolved"
                embed.description = f"**{p['title']}**\nWinner: **Outcome {winner}**\n\n" + embed.description
            await inter.channel.send(content=msg, embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Predictions(bot))
