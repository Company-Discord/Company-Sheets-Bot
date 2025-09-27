# src/games/highlow.py
# Weekly Lottery: on win, dispatches "gamble_winnings" with profit == bet.

import os
import random
from dataclasses import dataclass
from typing import Optional, Dict

import discord
from discord import app_commands
from src.bot.command_groups import games
from discord.ext import commands

from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager

CURRENCY_EMOTE = os.getenv("CURRENCY_EMOTE", ":TC:")
MAX_BET = int(os.getenv("HL_MAX_BET", "300000"))  

def fmt_tc(n: int) -> str:
    return f"{CURRENCY_EMOTE} {n:,}"

@dataclass
class HLState:
    user_id: int
    guild_id: int
    bet: int
    x: int                # starting number (revealed immediately)
    done: bool = False
    message: Optional[discord.Message] = None

class HLView(discord.ui.View):
    def __init__(self, cog: "HighLow", st: HLState, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.st = st

    async def on_timeout(self):
        st = self.st
        if st.done:
            return
        st.done = True
        # Refund (treat as cancel)
        try:
            await self.cog.add_cash(st.user_id, st.guild_id, st.bet, "HighLow timeout (refund)")
        except Exception:
            pass

        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.disabled = True

        emb = discord.Embed(
            title="High / Low — Timed out",
            description=f"Bet {fmt_tc(st.bet)} refunded.",
            color=discord.Color.gold()
        )
        emb.add_field(name="Starting Number", value=f"**{st.x}**", inline=True)

        try:
            if st.message:
                await st.message.edit(embed=emb, view=self)
        except Exception:
            pass
        self.cog.active.pop(st.user_id, None)

    # ---------- Buttons ----------

    @discord.ui.button(label="Higher", style=discord.ButtonStyle.success)
    async def higher(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._resolve(interaction, choice="higher")

    @discord.ui.button(label="Lower", style=discord.ButtonStyle.danger)
    async def lower(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._resolve(interaction, choice="lower")

    # ---------- Core resolve ----------

    async def _resolve(self, interaction: discord.Interaction, choice: str):
        st = self.st
        if interaction.user.id != st.user_id:
            return await interaction.response.send_message("This isn’t your game.", ephemeral=True)
        if st.done:
            return await interaction.response.defer()

        st.done = True
        self.cog.active.pop(st.user_id, None)

        # Draw new number
        y = random.randint(1, 100)

        # Decide outcome
        if y == st.x:
            outcome = "push"
            credit = st.bet
            result_text = f"**Push.** New number was **{y}** (same). Your bet is returned."
        elif (choice == "higher" and y > st.x) or (choice == "lower" and y < st.x):
            outcome = "win"
            credit = st.bet * 2  # even money
            result_text = f"**You win!** New number **{y}**. Payout {fmt_tc(credit)}."
        else:
            outcome = "lose"
            credit = 0
            result_text = f"**You lose.** New number **{y}**."

        # Payout / Refund
        if credit:
            try:
                await self.cog.add_cash(st.user_id, st.guild_id, credit, f"HighLow {outcome}")
            except Exception as e:
                result_text += f"\n⚠️ Payout error: {e}"

        # --- Weekly Lottery: award tickets on net-positive winnings (High/Low) ---
        # High/Low is even-money; profit on a win == original bet. Push/Lose => no event.
        try:
            if outcome == "win":
                self.cog.bot.dispatch(
                    "gamble_winnings",
                    st.guild_id,
                    st.user_id,
                    st.bet,     # profit
                    "HighLow",
                )
        except Exception:
            pass
        # --- end weekly lottery block ---

        
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.disabled = True

        emb = discord.Embed(title="High / Low — Result", color=discord.Color.green() if outcome=="win" else (discord.Color.gold() if outcome=="push" else discord.Color.red()))
        emb.add_field(name="Starting Number", value=f"**{st.x}**", inline=True)
        emb.add_field(name="Your Choice", value=choice.capitalize(), inline=True)
        emb.add_field(name="Bet", value=fmt_tc(st.bet), inline=True)
        emb.add_field(name="Outcome", value=result_text, inline=False)

        if interaction.response.is_done():
            if st.message:
                await st.message.edit(embed=emb, view=self)
        else:
            await interaction.response.edit_message(embed=emb, view=self)

class HighLow(BaseCog):
    """High/Low numbers (1–100)."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.active: Dict[int, HLState] = {}  # per-user lock

    def _locked(self, user_id: int) -> Optional[str]:
        return "You already have a High/Low game in progress." if user_id in self.active else None

    @games.command(name="highlow", description="Play High/Low (1–100). Bet before seeing the number.")
    @app_commands.describe(bet=f"Bet amount in {CURRENCY_EMOTE} (max {MAX_BET:,})")
    @is_admin_or_manager()
    async def highlow_cmd(self, interaction: discord.Interaction, bet: int):
        if interaction.guild_id is None:
            return await interaction.response.send_message("Server-only command.", ephemeral=True)

        # Check lock
        msg = self._locked(interaction.user.id)
        if msg:
            return await interaction.response.send_message(msg, ephemeral=True)

        # Validate bet
        if bet <= 0 or bet > MAX_BET:
            return await interaction.response.send_message(
                f"Invalid bet. Min 1, max {fmt_tc(MAX_BET)}.", ephemeral=True
            )

        # Balance check & escrow
        bal = await self.get_user_balance(interaction.user.id, interaction.guild_id)
        if bal.cash < bet:
            settings = await self.get_guild_settings(interaction.guild_id)
            return await interaction.response.send_message(
                f"Not enough cash. You have {self.format_currency(bal.cash, settings.currency_symbol)}.",
                ephemeral=True
            )

        ok = await self.deduct_cash(interaction.user.id, interaction.guild_id, bet, "HighLow bet escrow")
        if not ok:
            return await interaction.response.send_message("Failed to place bet.", ephemeral=True)

        # Start game
        x = random.randint(1, 100)
        st = HLState(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            bet=bet,
            x=x
        )

        emb = discord.Embed(title="High / Low — Make your call", color=discord.Color.blurple())
        emb.add_field(name="Starting Number", value=f"**{x}**", inline=True)
        emb.add_field(name="Bet", value=fmt_tc(bet), inline=True)
        emb.add_field(name="Payout", value=f"Win: {fmt_tc(bet*2)} • Tie: refund", inline=False)
        emb.set_footer(text="You have 60s to choose Higher or Lower.")

        view = HLView(self, st, timeout=60)
        await interaction.response.send_message(embed=emb, view=view)
        msg = await interaction.original_response()
        st.message = msg
        self.active[st.user_id] = st

    # Short alias
    @games.command(name="hl", description="Alias of /highlow")
    @app_commands.describe(bet=f"Bet amount in {CURRENCY_EMOTE} (max {MAX_BET:,})")
    @is_admin_or_manager()
    async def hl_alias(self, interaction: discord.Interaction, bet: int):
        await self.highlow_cmd.callback(self, interaction, bet)  # type: ignore

async def setup(bot: commands.Bot):
    await bot.add_cog(HighLow(bot))
