"""
Unified Cockfight game using centralized database.
"""

import asyncio
import random
import time
from collections import deque
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager

BASE_WIN_PERCENT = 50.0         # base chance %
PER_USER_LIMIT = 5              # max cockfights per rolling 60s (per user)
PER_USER_WINDOW = 60.0          # seconds
BUTTON_COOLDOWN_SECONDS = 2     # small pause after clicking "Bet Again"


class CockfightCog(BaseCog):
    """Cockfight betting that uses the unified database."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self._rate: dict[int, deque[float]] = {}

    # ------------------ UI: Bet Again button ------------------
    class BetAgainView(discord.ui.View):
        def __init__(self, cog: "CockfightCog", user_id: int, bet: int):
            super().__init__(timeout=60)
            self.cog = cog
            self.user_id = user_id
            self.bet = bet

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            # Only allow the same admin/manager who triggered the command
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "This button isn't for you.", ephemeral=True
                )
                return False
            
            # # Check if user has admin or manager permissions
            # if not (interaction.user.guild_permissions.administrator or 
            #         any(role.name.lower() in ['manager', 'moderator'] for role in interaction.user.roles)):
            #     await interaction.response.send_message(
            #         "You don't have permission to use this.", ephemeral=True
            #     )
            #     return False
            return True

        @discord.ui.button(label="Bet Again", style=discord.ButtonStyle.primary, custom_id="cockfight_bet_again")
        async def bet_again(self, interaction: discord.Interaction, button: discord.ui.Button):
            # grey out immediately (one-time use)
            button.disabled = True
            await interaction.response.edit_message(view=self)

            # rate limit check
            if not self.cog._check_rate_limit(self.user_id):
                await interaction.followup.send(
                    f"⏳ You're going too fast. Max {PER_USER_LIMIT} cockfights per {PER_USER_WINDOW}s. Try again later.", 
                    ephemeral=True
                )
                return

            await asyncio.sleep(BUTTON_COOLDOWN_SECONDS)
            await self.cog._handle_bet(interaction, interaction.user, self.bet, from_button=True)

    async def cog_load(self):
        """Initialize database when cog loads."""
        await super().cog_load()
        print("✅ Cockfight streaks table initialized in unified database")

    def _rate_limit_key(self, user_id: int) -> str:
        """Generate rate limit key for user."""
        return f"cockfight:{user_id}"

    def _check_rate_limit(self, user_id: int) -> bool:
        """Check if user is within rate limits."""
        now = time.time()
        key = self._rate_limit_key(user_id)
        
        if key not in self._rate:
            self._rate[key] = deque()
        
        # Remove old entries
        while self._rate[key] and self._rate[key][0] <= now - PER_USER_WINDOW:
            self._rate[key].popleft()
        
        # Check if under limit
        if len(self._rate[key]) >= PER_USER_LIMIT:
            return False
        
        # Add current timestamp
        self._rate[key].append(now)
        return True

    def _compute_win_chance(self, streak: int) -> float:
        """Compute win chance based on streak."""
        return BASE_WIN_PERCENT + (streak * 1.0)  # +1% per streak

    @is_admin_or_manager()
    @app_commands.command(name="cockfight", description="Bet on a cockfight. Win doubles your bet.")
    @app_commands.describe(bet="Amount to bet (positive integer, taken from your custom currency cash)")
    async def cockfight(self, interaction: discord.Interaction, bet: int):
        """Cockfight betting command."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Rate limiting
        if not self._check_rate_limit(user_id):
            await interaction.response.send_message(
                f"⏰ Rate limit: max {PER_USER_LIMIT} cockfights per {PER_USER_WINDOW}s. Try again later.",
                ephemeral=True
            )
            return

        await self._handle_bet(interaction, interaction.user, bet)

    @is_admin_or_manager()
    @app_commands.command(name="cockstats", description="Show your cockfight streak & current win chance.")
    async def cockstats(self, interaction: discord.Interaction):
        """Show cockfight statistics."""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        streak = await self.get_cockfight_streak(user_id, guild_id)
        chance = self._compute_win_chance(streak)
        await interaction.followup.send(
            f"Your streak: **{streak}**  •  Current win chance: **{chance:.2f}%**",
            ephemeral=True,
        )

    async def _handle_bet(self, interaction: discord.Interaction, user: discord.Member, amount: int, from_button: bool = False):
        """Handle the betting logic."""
        user_id = int(user.id)
        guild_id = int(interaction.guild.id)

        # Defer response for initial command (not for button interactions)
        if not from_button:
            await interaction.response.defer()

        # Validate bet
        if amount <= 0:
            if from_button:
                await interaction.followup.send(
                    "Bet must be greater than zero.", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Bet must be greater than zero.", 
                    ephemeral=True
                )
            return

        # Check balance
        if not await self.check_balance(user_id, guild_id, amount):
            user_balance = await self.get_user_balance(user_id, guild_id)
            settings = await self.get_guild_settings(guild_id)
            if from_button:
                await interaction.followup.send(
                    f"You don't have enough cash! You have {self.format_currency(user_balance.cash, settings.currency_symbol)}.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"You don't have enough cash! You have {self.format_currency(user_balance.cash, settings.currency_symbol)}.",
                    ephemeral=True
                )
            return

        # Deduct bet amount
        if not await self.deduct_cash(user_id, guild_id, amount, "Cockfight bet"):
            if from_button:
                await interaction.followup.send(
                    "Failed to place bet. Please try again.", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Failed to place bet. Please try again.", 
                    ephemeral=True
                )
            return

        # Get streak and calculate win chance
        streak = await self.get_cockfight_streak(user_id, guild_id)
        win_chance = self._compute_win_chance(streak)
        
        # Determine outcome
        won = random.random() < (win_chance / 100.0)
        
        # Update streak
        await self.update_cockfight_streak(user_id, guild_id, won)
        
        if won:
            # Win: double the bet
            winnings = amount * 2
            await self.add_cash(user_id, guild_id, winnings, "Cockfight win")
            
            # --- Weekly Lottery: award tickets on net-positive winnings (Cockfight) ---
            try:
                # Net profit = winnings - original bet  (here = amount)
                net_profit = max(0, int(winnings) - int(amount))
                if net_profit > 0:
                    self.bot.dispatch(
                        "gamble_winnings",
                        guild_id,
                        user_id,
                        net_profit,
                        "Cockfight",
                    )
            except Exception:
                pass
            # --- end weekly lottery block ---

            settings = await self.get_guild_settings(guild_id)
            
            # Add funny win messages like in the original
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
                    f"**Won:** {winnings:,}\n"
                    f"**Chicken strength:** {self._compute_win_chance(streak + 1):.2f}%"
                ),
                color=discord.Color.green(),
            )
            
            # Add Bet Again button for wins
            view = self.BetAgainView(self, user_id, amount)
            
            await interaction.followup.send(embed=embed, view=view)
        else:
            # Loss: bet is already deducted
            await self.log_transaction(
                user_id, guild_id, -amount, "cockfight_loss", 
                success=False, reason=f"Lost with {win_chance:.1f}% chance"
            )
            
            settings = await self.get_guild_settings(guild_id)
            
            # Add funny loss messages like in the original
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
                description=f"{funny_loss}\n\n**Lost:** {amount:,}",
                color=discord.Color.red(),
            )
            
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CockfightCog(bot))
