import os
import asyncio
import aiohttp
import aiosqlite
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime

# ================== Config ===================
DB_PATH = "predictions.db"

CURRENCY_ICON = os.getenv("CURRENCY_EMOJI")
if not CURRENCY_ICON:
    raise RuntimeError("CURRENCY_EMOJI must be set in your .env")

MIN_UNIQUE_BETTORS = int(os.getenv("PRED_MIN_UNIQUE", "4"))  # default 4

# ================== Errors ===================
class InsufficientFunds(Exception):
    pass

# ================== Engauge API ===================
class EngaugeAdapter:
    """
    Engauge currency client.
    Uses POST https://engau.ge/api/v1/servers/{server_id}/members/{member_id}/currency?amount=±N
    """

    def __init__(self, server_id: int):
        self.base = "https://engau.ge/api/v1"
        self.token = os.getenv("ENGAUGE_API_TOKEN") or os.getenv("ENGAUGE_TOKEN", "")
        self.server_id = int(server_id)
        if not self.token:
            raise RuntimeError("ENGAUGE_API_TOKEN or ENGAUGE_TOKEN must be set")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def adjust(self, member_id: int, amount: int):
        url = f"{self.base}/servers/{self.server_id}/members/{int(member_id)}/currency"
        params = {"amount": str(int(amount))}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params, headers=self._headers()) as r:
                if r.status == 402:
                    raise InsufficientFunds("Insufficient balance")
                r.raise_for_status()
                return await r.json()

    async def debit(self, member_id: int, amount: int):
        return await self.adjust(member_id, -abs(int(amount)))

    async def credit(self, member_id: int, amount: int):
        return await self.adjust(member_id, abs(int(amount)))


# ================== Cog ===================
class Predictions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = None
        self._lock_task.start()

    def cog_unload(self):
        self._lock_task.cancel()

    # ---------- Helpers ----------
    async def get_db(self):
        if not self.db:
            self.db = await aiosqlite.connect(DB_PATH)
            self.db.row_factory = aiosqlite.Row
            await self._migrate()
        return self.db

    async def _migrate(self):
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS predictions (
                guild_id INTEGER PRIMARY KEY,
                title TEXT,
                outcome_a TEXT,
                outcome_b TEXT,
                status TEXT,
                created_by INTEGER,
                created_ts INTEGER,
                lock_ts INTEGER,
                announce_channel_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS bets (
                guild_id INTEGER,
                user_id INTEGER,
                side TEXT,
                amount INTEGER,
                PRIMARY KEY (guild_id,user_id)
            );
            """
        )
        await self.db.commit()

    def now(self) -> int:
        return int(datetime.now().timestamp())

    def fmt_amt(self, amt: int) -> str:
        return f"{CURRENCY_ICON} {amt:,}"

    async def current_pred(self, guild_id: int):
        db = await self.get_db()
        cur = await db.execute("SELECT * FROM predictions WHERE guild_id=?", (guild_id,))
        return await cur.fetchone()

    async def pools(self, guild_id: int):
        db = await self.get_db()
        cur = await db.execute(
            "SELECT side,SUM(amount) as total FROM bets WHERE guild_id=? GROUP BY side", (guild_id,)
        )
        rows = await cur.fetchall()
        pool_a = pool_b = 0
        for r in rows:
            if r["side"] == "A":
                pool_a = r["total"]
            if r["side"] == "B":
                pool_b = r["total"]
        return pool_a or 0, pool_b or 0

    async def unique_bettors(self, guild_id: int) -> int:
        db = await self.get_db()
        cur = await db.execute("SELECT COUNT(DISTINCT user_id) FROM bets WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return row[0] if row else 0

    async def _refund_everyone(self, guild_id: int, reason: str):
        db = await self.get_db()
        cur = await db.execute("SELECT * FROM bets WHERE guild_id=?", (guild_id,))
        bets = await cur.fetchall()
        for b in bets:
            try:
                eng = EngaugeAdapter(guild_id)
                await eng.credit(b["user_id"], b["amount"])
            except Exception as e:
                print("refund error", e)
        await db.execute("DELETE FROM bets WHERE guild_id=?", (guild_id,))
        await db.commit()

    # ---------- Slash commands ----------
    @app_commands.command(name="pred_start", description="(Admin) Start a new prediction")
    @app_commands.default_permissions(administrator=True)
    async def start(
        self,
        inter: discord.Interaction,
        title: str,
        outcome_a: str,
        outcome_b: str,
        open_minutes: int = 5,
    ):
        await inter.response.defer(ephemeral=True)
        db = await self.get_db()
        lock_ts = self.now() + open_minutes * 60
        await db.execute(
            """REPLACE INTO predictions
            (guild_id,title,outcome_a,outcome_b,status,created_by,created_ts,lock_ts,announce_channel_id)
            VALUES (?,?,?,?, 'open', ?, ?, ?, ?)""",
            (inter.guild_id, title, outcome_a, outcome_b, inter.user.id, self.now(), lock_ts, inter.channel_id),
        )
        await db.execute("DELETE FROM bets WHERE guild_id=?", (inter.guild_id,))
        await db.commit()

        await inter.followup.send(f"Prediction started: **{title}**", ephemeral=True)
        channel = inter.channel
        if channel:
            await channel.send(embed=await self.make_embed(inter.guild_id))

    @app_commands.command(name="pred_bet", description="Place a bet on the current prediction")
    async def bet(self, inter: discord.Interaction, side: str, amount: int):
        side = side.upper()
        if side not in ("A", "B"):
            return await inter.response.send_message("Side must be A or B", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        pred = await self.current_pred(inter.guild_id)
        if not pred or pred["status"] != "open":
            return await inter.followup.send("No open prediction.", ephemeral=True)

        try:
            eng = EngaugeAdapter(inter.guild_id)
            await eng.debit(inter.user.id, amount)
        except InsufficientFunds:
            return await inter.followup.send("You don't have enough currency for this bet.", ephemeral=True)

        db = await self.get_db()
        # refund any previous bet first
        cur = await db.execute("SELECT amount FROM bets WHERE guild_id=? AND user_id=?", (inter.guild_id, inter.user.id))
        row = await cur.fetchone()
        if row:
            old_amt = row["amount"]
            old_side = row["side"]
            await eng.credit(inter.user.id, old_amt)
            await db.execute("DELETE FROM bets WHERE guild_id=? AND user_id=?", (inter.guild_id, inter.user.id))
            await db.commit()
            await inter.followup.send(
                f"Changed bet from {old_side} ({self.fmt_amt(old_amt)}) to {side} ({self.fmt_amt(amount)}).",
                ephemeral=True,
            )
        else:
            await inter.followup.send(f"Bet placed on {side} for {self.fmt_amt(amount)}.", ephemeral=True)

        await db.execute(
            "INSERT INTO bets (guild_id,user_id,side,amount) VALUES (?,?,?,?)",
            (inter.guild_id, inter.user.id, side, amount),
        )
        await db.commit()

        channel = inter.channel
        if channel:
            await channel.send(embed=await self.make_embed(inter.guild_id))

    @app_commands.command(name="pred_resolve", description="(Admin) Resolve and pay out a prediction")
    @app_commands.default_permissions(administrator=True)
    async def resolve(self, inter: discord.Interaction, winner: str):
        winner = winner.upper()
        if winner not in ("A", "B"):
            return await inter.response.send_message("Winner must be A or B", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        pred = await self.current_pred(inter.guild_id)
        if not pred or pred["status"] not in ("open", "locked"):
            return await inter.followup.send("No open/locked prediction.", ephemeral=True)

        pool_a, pool_b = await self.pools(inter.guild_id)
        total = pool_a + pool_b
        win_pool = pool_a if winner == "A" else pool_b

        if total <= 0 or win_pool <= 0:
            await self._refund_everyone(inter.guild_id, "pred-resolve-refund")
            msg = "No valid winners; all stakes refunded."
        else:
            multiplier = total / win_pool
            db = await self.get_db()
            cur = await db.execute("SELECT * FROM bets WHERE guild_id=? AND side=?", (inter.guild_id, winner))
            winners = await cur.fetchall()
            for w in winners:
                payout = int(w["amount"] * multiplier)
                eng = EngaugeAdapter(inter.guild_id)
                await eng.credit(w["user_id"], payout)
            msg = f"# 🏆 Payouts sent to Outcome {winner} backers!"

        db = await self.get_db()
        await db.execute("UPDATE predictions SET status='resolved' WHERE guild_id=?", (inter.guild_id,))
        await db.commit()

        await inter.followup.send("Resolved.", ephemeral=True)
        channel = inter.channel
        if channel:
            await channel.send(msg, embed=await self.make_embed(inter.guild_id))

    @app_commands.command(name="pred_cancel", description="(Admin) Cancel the current prediction and refund all")
    @app_commands.default_permissions(administrator=True)
    async def cancel(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        pred = await self.current_pred(inter.guild_id)
        if not pred or pred["status"] not in ("open", "locked"):
            return await inter.followup.send("No open/locked prediction.", ephemeral=True)

        await self._refund_everyone(inter.guild_id, "pred-cancel")
        db = await self.get_db()
        await db.execute("UPDATE predictions SET status='canceled' WHERE guild_id=?", (inter.guild_id,))
        await db.commit()

        await inter.followup.send("Canceled and refunded.", ephemeral=True)
        channel = inter.channel
        if channel:
            await channel.send("Prediction canceled and refunded.", embed=await self.make_embed(inter.guild_id))

    @app_commands.command(name="pred_status", description="Show the current prediction status")
    async def status(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        pred = await self.current_pred(inter.guild_id)
        if not pred:
            return await inter.followup.send("No active prediction.", ephemeral=True)
        await inter.followup.send(embed=await self.make_embed(inter.guild_id), ephemeral=True)

    # ---------- Embed ----------
    async def make_embed(self, guild_id: int):
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
                f"⚠️ Auto-cancels at lock if fewer than {MIN_UNIQUE_BETTORS} unique participants.\n"
                f"➡️ Use `/pred_bet` to place your bets!"
            ),
            color=discord.Color.blurple(),
        )

        e.add_field(name="Pool A", value=self.fmt_amt(pool_a), inline=True)
        e.add_field(name="Pool B", value=self.fmt_amt(pool_b), inline=True)
        e.add_field(name="Current Odds", value=f"**A)** {mult(pool_a)}\n**B)** {mult(pool_b)}", inline=False)
        return e

    # ---------- Background task ----------
    @tasks.loop(seconds=15)
    async def _lock_task(self):
        db = await self.get_db()
        now = self.now()
        cur = await db.execute(
            "SELECT guild_id, lock_ts, announce_channel_id FROM predictions WHERE status='open' AND lock_ts <= ?",
            (now,),
        )
        rows = await cur.fetchall()
        for r in rows:
            gid = r["guild_id"]
            ch_id = r["announce_channel_id"]
            channel = self.bot.get_channel(ch_id) if ch_id else None
            guild = self.bot.get_guild(gid)

            bettors = await self.unique_bettors(gid)
            if bettors < MIN_UNIQUE_BETTORS:
                await self._refund_everyone(gid, "pred-auto-cancel")
                await db.execute("UPDATE predictions SET status='canceled' WHERE guild_id=?", (gid,))
                await db.commit()

                if channel:
                    await channel.send(f"❌ Prediction auto-canceled — fewer than {MIN_UNIQUE_BETTORS} participants.")
                elif guild and guild.system_channel:
                    await guild.system_channel.send(
                        f"❌ Prediction auto-canceled — fewer than {MIN_UNIQUE_BETTORS} participants."
                    )
                continue

            # otherwise lock
            await db.execute("UPDATE predictions SET status='locked' WHERE guild_id=?", (gid,))
            await db.commit()
            if channel:
                await channel.send("🔒 Betting is now locked.")
            elif guild and guild.system_channel:
                await guild.system_channel.send("🔒 Betting is now locked.")

    @_lock_task.before_loop
    async def before_lock(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Predictions(bot))
