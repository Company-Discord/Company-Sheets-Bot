# src/games/cockfight.py
import os
import asyncio
import random
import time
from collections import deque
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite

# ✅ Use your utils helpers (UnbelievaBoat-backed currency)
from src.utils.utils import get_user_balance as utils_get_balance
from src.utils.utils import debit_user as utils_debit
from src.utils.utils import credit_user as utils_credit

BASE_WIN_PERCENT = 50.0         # base chance %
PER_USER_LIMIT = 5              # max cockfights per rolling 60s
PER_USER_WINDOW = 60.0          # seconds
BUTTON_COOLDOWN_SECONDS = 2     # pause after clicking "Bet Again"

# Streak storage in your mounted volume
DB_PATH = "data/databases/cockfight.db"
STREAKS_TABLE = "cockfight_streaks"


async def _ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS {STREAKS_TABLE} (
                user_id INTEGER,
                guild_id INTEGER,
                streak  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await db.commit()


class CockfightCog(commands.Cog):
    """Cockfight betting that uses your utils.py currency helpers (UnbelievaBoat-backed)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._rate: dict[int, deque[float]] = {}

    async def cog_load(self):
        await _ensure_db()

    # ------------------ streak helpers ------------------
    async def _get_streak(self, user_id: int, guild_id: int) -> int:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                f"SELECT streak FROM {STREAKS_TABLE} WHERE user_id=? AND guild_id=?",
                (user_id, guild_id),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return int(row[0])
            await db.execute(
                f"INSERT OR IGNORE INTO {STREAKS_TABLE}(user_id,guild_id,streak) VALUES (?,?,0)",
                (user_id, guild_id),
            )
            await db.commit()
        return 0

    async def _set_streak(self, user_id: int, guild_id: int, streak: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"""
                INSERT INTO {STREAKS_TABLE}(user_id,guild_id,streak)
                VALUES (?,?,?)
                ON CONFLICT(user_id,guild_id) DO UPDATE SET streak=excluded.streak
                """,
                (user_id, guild_id, int(streak)),
            )
            await db.commit()

    # ------------------ chance / roll ------------------
    def _compute_win_chance(self, streak: int) -> float:
        # base 50 + 1% per existing (pre-fight) consecutive win
        return BASE_WIN_PERCENT + float(streak)

    def _roll_win(self, win_percent: float) -> bool:
        return random.random() < (win_percent / 100.0)

    # ------------------ rate limiting ------------------
    def _check_rate_limit(self, user_id: int) -> Optional[float]:
        now = time.monotonic()
        dq = self._rate.setdefault(user_id, deque())
        while dq and (now - dq[0]) > PER_USER_WINDOW:
            dq.popleft()
        if len(dq) >= PER_USER_LIMIT:
            return PER_USER_WINDOW - (now - dq[0])
        dq.append(now)
        return None

    # ------------------ UI: Bet Again button ------------------
    class BetAgainView(discord.ui.View):
        def __init__(self, cog: "CockfightCog", user_id: int, bet: int):
            super().__init__(timeout=60)
            self.cog = cog
            self.user_id = user_id
            self.bet = bet

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This button isn’t for you.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Bet Again", style=discord.ButtonStyle.primary, custom_id="cockfight_bet_again")
        async def bet_again(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Grey out immediately (one-time use)
            button.disabled = True
            await interaction.response.edit_message(view=self)

            # Rate limit
            wait = self.cog._check_rate_limit(self.user_id)
            if wait is not None:
                await interaction.followup.send(
                    f"⏳ You’re going too fast. Try again in ~{int(wait)}s.", ephemeral=True
                )
                return

            await asyncio.sleep(BUTTON_COOLDOWN_SECONDS)
            await self.cog._handle_bet(interaction, interaction.user, self.bet, from_button=True)

    # ------------------ slash commands ------------------
    @is_admin_or_manager()
    @app_commands.command(name="cockfight", description="Bet on a cockfight. Win doubles your bet.")
    async def cockfight(self, interaction: discord.Interaction, bet: int):
        # Rate limit fast-path
        wait = self._check_rate_limit(interaction.user.id)
        if wait is not None:
            await interaction.response.send_message(
                f"⏳ You’re going too fast. Max {PER_USER_LIMIT}/min. Try again in ~{int(wait)}s.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await self._handle_bet(interaction, interaction.user, bet)

    @is_admin_or_manager()
    @app_commands.command(name="cockstats", description="Show your cockfight streak & current win chance.")
    async def cockstats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        streak = await self._get_streak(user_id, guild_id)
        chance = self._compute_win_chance(streak)
        await interaction.followup.send(
            f"Your streak: **{streak}**  •  Current win chance: **{chance:.2f}%**",
            ephemeral=True,
        )

    # ------------------ core handler ------------------
    async def _handle_bet(
        self,
        ctx_or_inter: discord.Interaction | commands.Context,
        user: discord.Member,
        amount: int,
        from_button: bool = False,
    ):
        is_inter = isinstance(ctx_or_inter, discord.Interaction)
        send = ctx_or_inter.followup.send if is_inter else ctx_or_inter.send

        user_id = int(user.id)
        guild_id = int(ctx_or_inter.guild.id)

        # Validate bet
        try:
            bet = int(amount)
        except Exception:
            return await send("Invalid bet amount. Use a whole number.", ephemeral=is_inter and not from_button)
        if bet <= 0:
            return await send("Bet must be greater than zero.", ephemeral=is_inter and not from_button)

        # Balance check via your utils (UnbelievaBoat)
        cash = await utils_get_balance(guild_id, user_id)
        if cash < bet:
            return await send(
                f"You only have {cash:,} — can't bet {bet:,}.",
                ephemeral=is_inter and not from_button,
            )

        # Deduct stake up front (cash -bet)
        # We record the reason so it’s visible in your UnbelievaBoat logs
        await utils_debit(guild_id, user_id, bet, reason=f"Cockfight bet {bet}")

        # Roll using current streak
        streak = await self._get_streak(user_id, guild_id)     # pre-fight streak
        win_chance = self._compute_win_chance(streak)
        won = self._roll_win(win_chance)

        if won:
            # Credit winnings equal to bet (net profit +bet)
            await utils_credit(guild_id, user_id, bet, reason=f"Cockfight win +{bet}")

            # Increase streak and persist
            streak += 1
            await self._set_streak(user_id, guild_id, streak)

            funny_win = random.choice([
                "✅ Your chicken won the fight and made you richer! 🐓💰",
                "✅ Cocky Balboa strikes again — victory is yours! 🐔🥊",
                "✅ Your chicken pecked its way to fortune! 🤑",
                "✅ Feathered fury brings you glory and gold! 🐓✨",
                "🐓 Your chicken came out swinging like **Cocky Balboa!**",
                "💪 The rooster flexed its wings and absolutely dominated!",
                "🔥 Cockzilla has risen — flawless victory!",
                "🎉 Your chicken pecked its way to glory!",
            ])

            embed = discord.Embed(
                title="🐔 Cockfight Results",
                description=(
                    f"{funny_win}\n\n"
                    f"**Won:** {bet * 2:,}\n"
                    f"**Chicken strength:** {self._compute_win_chance(streak):.2f}%"
                ),
                color=discord.Color.green(),
            )
            view = self.BetAgainView(self, user_id, bet)
            await send(embed=embed, view=view)

        else:
            # Loss → reset streak. (We already debited their stake above.)
            await self._set_streak(user_id, guild_id, 0)

            funny_loss = random.choice([
                "❌ Your chicken lost the fight and died. 💀🐓",
                "❌ The rooster got cooked… extra crispy. 🍗",
                "❌ RIP chicken, gone but not forgotten. 🪦",
                "❌ Your chicken got clucked up. ☠️",
                "💀 Your chicken fought bravely... then instantly became KFC.",
                "☠️ The rooster tripped, fell, and is now chicken nuggets.",
                "🍗 Colonel Sanders sends his regards — extra crispy.",
                "🪦 RIP Chicken. Gone but not forgotten (until dinner).",
            ])

            embed = discord.Embed(
                title="🐔 Cockfight Results",
                description=f"{funny_loss}\n\n**Lost:** {bet:,}",
                color=discord.Color.red(),
            )
            await send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CockfightCog(bot))
