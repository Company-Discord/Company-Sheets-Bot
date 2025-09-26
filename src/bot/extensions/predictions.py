import os
import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime

from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager

# ================== Config ===================
MANAGER_ROLE_NAME = os.getenv("MANAGER_ROLE_NAME", "Techie")
CURRENCY_ICON = os.getenv("CURRENCY_EMOJI", "💰")
MIN_UNIQUE_BETTORS = int(os.getenv("PRED_MIN_UNIQUE", "4"))  # default 4

# ================== UI Components ===================

class BetModal(discord.ui.Modal, title="Place Your Bet"):
    """Modal for entering bet amount"""
    
    def __init__(self, side: str, cog_instance, user_id: int):
        super().__init__()
        self.side = side
        self.cog = cog_instance
        self.user_id = user_id
        
        # Get user's current bet status for better modal title
        self.title = f"Bet on {side} - Place Your Bet"
        
    bet_amount = discord.ui.TextInput(
        label="Bet Amount",
        placeholder="Enter the amount you want to bet...",
        min_length=1,
        max_length=10,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.bet_amount.value)
            if amount <= 0:
                await interaction.response.send_message("Bet amount must be positive!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Please enter a valid number!", ephemeral=True)
            return
        
        # Process the bet and get feedback
        feedback_embed = await self.cog.process_bet(interaction, self.side, amount)
        
        # Build a personalized buttons view to reflect user selection
        selected_side = self.side if feedback_embed is not None else None
        view = PersonalBetButtons(self.cog, selected_side)
        
        # Send the feedback embed or error message with personalized buttons
        if feedback_embed:
            await interaction.response.send_message(embed=feedback_embed, view=view, ephemeral=True)
        else:
            # Handle error cases
            pred = await self.cog.current_pred(interaction.guild_id)
            if not pred or pred["status"] != "open":
                await interaction.response.send_message("No open prediction available.", ephemeral=True)
            else:
                await interaction.response.send_message("You don't have enough currency for this bet.", ephemeral=True)

class BetButtons(discord.ui.View):
    """View containing the Bet on A and Bet on B buttons"""
    
    def __init__(self, cog_instance):
        super().__init__(timeout=None)  # No timeout so buttons persist
        self.cog = cog_instance
    
    @discord.ui.button(label="Bet on A", style=discord.ButtonStyle.primary, emoji="🅰️")
    async def bet_on_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BetModal("A", self.cog, interaction.user.id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Bet on B", style=discord.ButtonStyle.primary, emoji="🅱️")
    async def bet_on_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BetModal("B", self.cog, interaction.user.id)
        await interaction.response.send_modal(modal)

# Personalized buttons view (ephemeral) showing selected side in green and the other in gray
class PersonalBetButtons(discord.ui.View):
    """Ephemeral per-user buttons that reflect user's current selection with colors."""

    def __init__(self, cog_instance, selected_side: str = None):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.selected_side = selected_side

        # Create buttons dynamically so we can change styles at runtime
        self.a_button = discord.ui.Button(
            label="Bet on A",
            emoji="🅰️",
            style=discord.ButtonStyle.primary,
            custom_id="personal_bet_a",
        )
        self.b_button = discord.ui.Button(
            label="Bet on B",
            emoji="🅱️",
            style=discord.ButtonStyle.primary,
            custom_id="personal_bet_b",
        )

        # Apply selected styling
        if self.selected_side == "A":
            self.a_button.style = discord.ButtonStyle.success  # green
            self.b_button.style = discord.ButtonStyle.secondary  # gray
        elif self.selected_side == "B":
            self.a_button.style = discord.ButtonStyle.secondary  # gray
            self.b_button.style = discord.ButtonStyle.success  # green

        # Wire callbacks
        self.a_button.callback = self._on_bet_a
        self.b_button.callback = self._on_bet_b

        # Add to view
        self.add_item(self.a_button)
        self.add_item(self.b_button)

        
    async def _on_bet_a(self, interaction: discord.Interaction):
        modal = BetModal("A", self.cog, interaction.user.id)
        await interaction.response.send_modal(modal)

    async def _on_bet_b(self, interaction: discord.Interaction):
        modal = BetModal("B", self.cog, interaction.user.id)
        await interaction.response.send_modal(modal)

# ================== Cog ===================
class Predictions(BaseCog):
    """Predictions cog that uses the unified database."""
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self._lock_task.start()
        
        # Set all commands in this cog to be guild-specific
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            print(f"[Predictions] Setting guild-specific commands for {guild_id}")
            guild_obj = discord.Object(id=int(guild_id))
            for command in self.__cog_app_commands__:
                command.guild = guild_obj
                print(f"[Predictions] Assigned guild to command: {command.name}")

    def cog_unload(self):
        self._lock_task.cancel()

    # ---------- Helpers ----------

    def now(self) -> int:
        return int(datetime.now().timestamp())

    def fmt_amt(self, amt: int) -> str:
        return f"{CURRENCY_ICON} {amt:,}"

    async def update_embed(self, guild_id: int, content: str = None):
        """Update the existing prediction embed if it exists, otherwise send a new one"""
        pred = await self.current_pred(guild_id)
        if not pred:
            return
        
        embed = await self.make_embed(guild_id)
        if not embed:
            return
        
        # Create view with buttons (only show buttons if prediction is open)
        view = None
        if pred["status"] == "open":
            view = BetButtons(self)
            
        # Try to edit existing message
        if pred["embed_message_id"] and pred["announce_channel_id"]:
            try:
                channel = self.bot.get_channel(pred["announce_channel_id"])
                if channel:
                    message = await channel.fetch_message(pred["embed_message_id"])
                    if content:
                        await message.edit(content=content, embed=embed, view=view)
                    else:
                        await message.edit(embed=embed, view=view)
                    return
            except (discord.NotFound, discord.HTTPException):
                # Message was deleted or other error, fall back to sending new message
                pass
        
        # Fallback: send new message and update stored ID
        if pred["announce_channel_id"]:
            channel = self.bot.get_channel(pred["announce_channel_id"])
            if channel:
                if content:
                    message = await channel.send(content=content, embed=embed, view=view)
                else:
                    message = await channel.send(embed=embed, view=view)
                # Update stored message ID using unified database
                await self.db.update_prediction_embed_message(guild_id, message.id)

    async def current_pred(self, guild_id: int):
        """Get current prediction for guild."""
        return await self.db.get_current_prediction(guild_id)

    async def pools(self, guild_id: int):
        """Get betting pools for guild."""
        return await self.db.get_prediction_pools(guild_id)

    async def unique_bettors(self, guild_id: int) -> int:
        """Get number of unique bettors for guild."""
        return await self.db.get_prediction_unique_bettors(guild_id)

    async def get_user_bet(self, guild_id: int, user_id: int):
        """Get a user's current bet for this prediction"""
        return await self.db.get_user_prediction_bet(guild_id, user_id)

    async def bettor_counts(self, guild_id: int) -> tuple[int, int, int]:
        """Return (count_A, count_B, total_unique_bettors)."""
        return await self.db.get_prediction_bettor_counts(guild_id)

    async def _refund_everyone(self, guild_id: int, reason: str):
        """Refund all bets for a prediction."""
        # Get all bets for this prediction
        bets = await self.db.get_prediction_bets(guild_id)
        
        # Refund each bet using unified currency system
        for bet in bets:
            await self.add_cash(bet["user_id"], guild_id, bet["amount"], f"Prediction refund: {reason}")
        
        # Clear all bets for this prediction
        await self.db.clear_prediction_bets(guild_id)

    async def _resolve_prediction(self, guild_id: int, winner: str):
        """Resolve prediction and pay out winners."""
        # Get pools and calculate payouts
        pool_a, pool_b = await self.pools(guild_id)
        total = pool_a + pool_b
        win_pool = pool_a if winner == "A" else pool_b
        
        if total > 0 and win_pool > 0:
            multiplier = total / win_pool
            # Get winning bets
            winners = await self.db.get_winning_bets(guild_id, winner)
            
            # Pay out winners using unified currency system
            for winner_bet in winners:
                payout = int(winner_bet["amount"] * multiplier)
                await self.add_cash(winner_bet["user_id"], guild_id, payout, f"Prediction win: {winner}")
        
        # Update prediction status
        await self.db.update_prediction_status(guild_id, "resolved", winner)

    async def process_bet(self, interaction: discord.Interaction, side: str, amount: int):
        """Process a bet placed via the button/modal interface"""
        pred = await self.current_pred(interaction.guild_id)
        if not pred or pred["status"] != "open":
            return None  # Return None to indicate error

        # Check if user has enough cash using unified currency system
        if not await self.check_balance(interaction.user.id, interaction.guild_id, amount):
            return None  # Return None to indicate error

        # Deduct the bet amount
        if not await self.deduct_cash(interaction.user.id, interaction.guild_id, amount, f"Prediction bet on {side}"):
            return None  # Return None to indicate error

        # Check for existing bet and refund if necessary
        existing_bet = await self.get_user_bet(interaction.guild_id, interaction.user.id)
        
        feedback_embed = None
        
        if existing_bet:
            old_amt = existing_bet["amount"]
            old_side = existing_bet["side"]
            # Refund the old bet
            await self.add_cash(interaction.user.id, interaction.guild_id, old_amt, f"Prediction bet refund for {old_side}")
            
            # Create embed for bet change feedback
            feedback_embed = discord.Embed(
                title="🔄 Bet Changed",
                description=f"**{interaction.user.display_name}** changed their bet:",
                color=0xFF6B35  # Bright orange color
            )
            feedback_embed.add_field(
                name="Previous Bet", 
                value=f"**{old_side}** - {self.fmt_amt(old_amt)}", 
                inline=True
            )
            feedback_embed.add_field(
                name="New Bet", 
                value=f"**{side}** - {self.fmt_amt(amount)}", 
                inline=True
            )
            feedback_embed.add_field(
                name="Status", 
                value="✅ Bet updated successfully!", 
                inline=False
            )
        else:
            # Create embed for new bet feedback
            feedback_embed = discord.Embed(
                title="🎯 New Bet Placed",
                description=f"**{interaction.user.display_name}** placed a new bet:",
                color=0x00D166  # Bright green color
            )
            feedback_embed.add_field(
                name="Bet Details", 
                value=f"**{side}** - {self.fmt_amt(amount)}", 
                inline=True
            )
            feedback_embed.add_field(
                name="Status", 
                value="✅ Bet placed successfully!", 
                inline=True
            )

        # Record the new bet using unified database
        await self.db.add_prediction_bet(interaction.guild_id, interaction.user.id, side, amount)

        # Update the embed
        await self.update_embed(interaction.guild_id)
        
        return feedback_embed

    # ---------- Slash commands ----------
    @app_commands.command(name="pred_start", description="(Admin/Techie) Start a new prediction")
    @is_admin_or_manager()
    async def start(
        self,
        inter: discord.Interaction,
        title: str,
        outcome_a: str,
        outcome_b: str,
        open_minutes: int = 5,
    ):
        await inter.response.defer(ephemeral=True)
        lock_ts = self.now() + open_minutes * 60
        
        # Create prediction using unified database
        await self.db.create_prediction(
            inter.guild_id, title, outcome_a, outcome_b, 
            inter.user.id, self.now(), lock_ts, inter.channel_id
        )
        
        await inter.followup.send(f"Prediction started: **{title}**", ephemeral=True)
        # Update the embed with buttons
        await self.update_embed(inter.guild_id)


    @app_commands.command(name="pred_resolve", description="(Admin/Techie) Resolve and pay out a prediction")
    @is_admin_or_manager()
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
            # Resolve prediction and pay out winners
            await self._resolve_prediction(inter.guild_id, winner)
            msg = f"# 🏆 Payouts sent to Outcome {winner} backers!"

        await inter.followup.send("Resolved.", ephemeral=True)
        # Update the existing embed with the resolution message
        await self.update_embed(inter.guild_id, content=msg)

    @app_commands.command(name="pred_cancel", description="(Admin/Techie) Cancel the current prediction and refund all")
    @is_admin_or_manager()
    async def cancel(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        pred = await self.current_pred(inter.guild_id)
        if not pred or pred["status"] not in ("open", "locked"):
            return await inter.followup.send("No open/locked prediction.", ephemeral=True)

        await self._refund_everyone(inter.guild_id, "pred-cancel")
        # Cancel prediction
        await self.db.update_prediction_status(inter.guild_id, "canceled")

        await inter.followup.send("Canceled and refunded.", ephemeral=True)
        # Update the existing embed with the cancellation message
        await self.update_embed(inter.guild_id, content="Prediction canceled and refunded.")

    @app_commands.command(name="pred_status", description="Show the current prediction status")
    @is_admin_or_manager()
    async def status(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        pred = await self.current_pred(inter.guild_id)
        if not pred:
            return await inter.followup.send("No active prediction.", ephemeral=True)
        await inter.followup.send(embed=await self.make_embed(inter.guild_id, inter.user.id), ephemeral=True)

    # ---------- Embed ----------
    async def make_embed(self, guild_id: int, user_id: int = None):
        p = await self.current_pred(guild_id)
        if not p:
            return None

        pool_a, pool_b = await self.pools(guild_id)
        total = pool_a + pool_b

        def mult(my_pool: int) -> str:
            if my_pool <= 0:
                return "—"
            return f"{total / my_pool:.2f}×"

        # === NEW: bettor percentages ===
        a_count, b_count, total_bettors = await self.bettor_counts(guild_id)

        def pct(n: int, d: int) -> str:
            return "0%" if d <= 0 else f"{(n * 100 / d):.0f}%"

        lock_ts = p["lock_ts"]
        rel = f"<t:{lock_ts}:R>"
        abs_t = f"<t:{lock_ts}:t>"

        # Prepare outcome text with winner highlighting
        outcome_a_text = p['outcome_a']
        outcome_b_text = p['outcome_b']
        
        # Safely get winner (might not exist in older database records)
        winner = None
        try:
            winner = p['winner']
        except (KeyError, IndexError):
            pass
            
        if p['status'] == 'resolved' and winner:
            if winner == 'A':
                outcome_a_text = f"🏆 **{p['outcome_a']}** 🏆"
            elif winner == 'B':
                outcome_b_text = f"🏆 **{p['outcome_b']}** 🏆"

        # Get user's current bet if user_id provided
        user_bet_info = ""
        if user_id and p['status'] == 'open':
            user_bet = await self.get_user_bet(guild_id, user_id)
            if user_bet:
                user_bet_info = f"\n🎯 **Your current bet:** {user_bet['side']} - {self.fmt_amt(user_bet['amount'])}"
            else:
                user_bet_info = f"\n💡 **No bet placed yet** - Click the buttons below to bet!"

        # Different description based on status
        if p['status'] == 'resolved':
            description = (
                f"**{p['title']}**\n"
                f"**Status:** `{p['status'].upper()}`\n\n"
                f"**A)** {outcome_a_text}\n"
                f"**B)** {outcome_b_text}\n"
            )
        else:
            description = (
                f"**{p['title']}**\n"
                f"**Status:** `{p['status'].upper()}`\n"
                f"⏳ **Time left:** {rel}  (locks at {abs_t})\n\n"
                f"**A)** {outcome_a_text}\n"
                f"**B)** {outcome_b_text}\n"
                f"{user_bet_info}\n\n"
                f"⚠️ Auto-cancels at lock if fewer than {MIN_UNIQUE_BETTORS} unique participants.\n"
                f"➡️ Use the buttons below to place your bets!"
            )

        e = discord.Embed(
            title="🔮 Prediction",
            description=description,
            color=discord.Color.gold() if p['status'] == 'resolved' else discord.Color.blurple(),
        )

        # Highlight winning pool if resolved
        pool_a_name = "Pool A"
        pool_b_name = "Pool B"
        if p['status'] == 'resolved' and winner:
            if winner == 'A':
                pool_a_name = "🏆 Pool A (Winner)"
            elif winner == 'B':
                pool_b_name = "🏆 Pool B (Winner)"

        e.add_field(name=pool_a_name, value=self.fmt_amt(pool_a), inline=True)
        e.add_field(name=pool_b_name, value=self.fmt_amt(pool_b), inline=True)
        
        # Different odds display for resolved vs active predictions
        if p['status'] == 'resolved':
            e.add_field(
                name="Final Results",
                value=(
                    f"**A)** {mult(pool_a)} · {pct(a_count, total_bettors)} of bettors ({a_count}/{total_bettors})\n"
                    f"**B)** {mult(pool_b)} · {pct(b_count, total_bettors)} of bettors ({b_count}/{total_bettors})"
                ),
                inline=False
            )
        else:
            e.add_field(
                name="Current Odds",
                value=(
                    f"**A)** {mult(pool_a)} - {self.fmt_amt(pool_a)} bet by {a_count} players\n"
                    f"**B)** {mult(pool_b)} - {self.fmt_amt(pool_b)} bet by {b_count} players"
                ),
                inline=False
            )
        return e

    # ---------- Background task ----------
    @tasks.loop(seconds=15)
    async def _lock_task(self):
        now = self.now()
        # Get predictions that need to be locked using unified database
        predictions_to_lock = await self.db.get_predictions_to_lock(now)
        
        for pred in predictions_to_lock:
            gid = pred["guild_id"]
            ch_id = pred["announce_channel_id"]
            channel = self.bot.get_channel(ch_id) if ch_id else None
            guild = self.bot.get_guild(gid)

            bettors = await self.unique_bettors(gid)
            if bettors < MIN_UNIQUE_BETTORS:
                await self._refund_everyone(gid, "pred-auto-cancel")
                await self.db.update_prediction_status(gid, "canceled")

                # Update the existing embed with auto-cancel message
                await self.update_embed(gid, content=f"❌ Prediction auto-canceled — fewer than {MIN_UNIQUE_BETTORS} participants.")
                continue

            # otherwise lock
            await self.db.update_prediction_status(gid, "locked")
            # Update the existing embed with lock message
            await self.update_embed(gid, content="🔒 Betting is now locked.")

    @_lock_task.before_loop
    async def before_lock(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Predictions(bot))
