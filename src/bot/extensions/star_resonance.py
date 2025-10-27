"""
Star Resonance Discord bot extension.
Provides commands for battle statistics and leaderboards.
Integrated with existing unified database.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import discord
from discord.ext import commands
from discord import app_commands, Embed

from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager
from src.database.star_resonance_models import (
    StarResonanceUser, Battle, BattleParticipant, 
    BattleMonster, GuildConfig, generate_auth_token
)

class StarResonance(BaseCog):
    """Star Resonance battle statistics and leaderboard commands."""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.report_channel_id = None
        self.auto_report_enabled = True
        self.log = logging.getLogger(__name__)
    
    @app_commands.command(name="register_sr", description="Register your Star Resonance damage counter with the bot.")
    async def register_sr(self, interaction: discord.Interaction):
        """Register user for Star Resonance integration."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # For now, generate a simple auth token for testing
            auth_token = f"sr_test_{interaction.user.id}_{int(datetime.now().timestamp())}"
            
            await interaction.followup.send(
                f"✅ You've been registered! Your auth token is: `{auth_token}`\n"
                f"Please configure your damage counter with this token and the server URL: `http://localhost:5000`",
                ephemeral=True
            )
            
        except Exception as e:
            self.log.error(f"Error during register_sr: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An error occurred during registration: {e}", ephemeral=True)
    
    @app_commands.command(name="link_sr_game_uid", description="Link your in-game UID to your Discord account.")
    @app_commands.describe(game_uid="Your in-game character ID (from the damage counter).")
    async def link_sr_game_uid(self, interaction: discord.Interaction, game_uid: str):
        """Link in-game UID to Discord account."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # For testing, just acknowledge the link
            await interaction.followup.send(f"✅ Your in-game UID `{game_uid}` has been linked to your Discord account for testing.", ephemeral=True)
                
        except ValueError:
            await interaction.followup.send("❌ Invalid game UID. Please provide a number.", ephemeral=True)
        except Exception as e:
            self.log.error(f"Error during link_sr_game_uid: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)
    
    @app_commands.command(name="sr_stats", description="Show your or another user's Star Resonance battle stats.")
    @app_commands.describe(user="The user to get stats for (defaults to you).")
    async def sr_stats(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Show user battle statistics."""
        target_user = user or interaction.user
        await interaction.response.defer()
        
        try:
            # For testing, show a mock stats response
            embed = Embed(
                title=f"⚔️ {target_user.display_name}'s Battle Stats (Test Mode)",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else None)
            
            embed.add_field(
                name="Recent Battle",
                value=(
                    f"**Damage:** 250,000 (2,083 DPS)\n"
                    f"**Healing:** 5,000 (41.67 HPS)\n"
                    f"**Taken Damage:** 15,000\n"
                    f"**Duration:** 120.0s | **Profession:** DPS-射线"
                ),
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            self.log.error(f"Error during sr_stats: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)
    
    @app_commands.command(name="sr_lastbattle", description="Show the most recent Star Resonance battle summary.")
    async def sr_lastbattle(self, interaction: discord.Interaction):
        """Show most recent battle summary."""
        await interaction.response.defer()
        
        try:
            # For testing, show a mock battle summary
            embed = Embed(
                title="Recent Battle Summary (Test Mode)",
                color=discord.Color.green()
            )
            embed.add_field(name="Duration", value="120.0 seconds", inline=True)
            embed.add_field(name="Ended At", value="2024-01-01 12:00:00", inline=True)
            
            embed.add_field(name="--- Participants ---", value=" ", inline=False)
            embed.add_field(
                name="**TestPlayer** (DPS-射线)",
                value="Damage: 250,000 (2,083.33 DPS)\nHealing: 5,000 (41.67 HPS)",
                inline=False
            )
            
            embed.add_field(name="--- Enemies ---", value=" ", inline=False)
            embed.add_field(
                name="**雷电食人魔**",
                value="HP: 0/18,011,262",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            self.log.error(f"Error during sr_lastbattle: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)
    
    @app_commands.command(name="sr_leaderboard", description="Show Star Resonance DPS leaderboard.")
    @app_commands.describe(timeframe="Filter by timeframe (e.g., 'day', 'week', 'month', 'all').")
    async def sr_leaderboard(self, interaction: discord.Interaction, timeframe: str = "day"):
        """Show DPS leaderboard."""
        await interaction.response.defer()
        
        try:
            # For testing, show a mock leaderboard
            embed = Embed(
                title=f"🏆 Star Resonance DPS Leaderboard ({timeframe.capitalize()}) - Test Mode",
                color=discord.Color.gold()
            )
            
            embed.add_field(
                name="1. TestPlayer1 (DPS-射线)",
                value="Total Damage: 250,000 | Avg DPS: 2,083.33",
                inline=False
            )
            embed.add_field(
                name="2. TestPlayer2 (DPS-狼弓)",
                value="Total Damage: 180,000 | Avg DPS: 1,500.00",
                inline=False
            )
            embed.add_field(
                name="3. TestPlayer3 (愈合)",
                value="Total Damage: 50,000 | Avg DPS: 416.67",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            self.log.error(f"Error during sr_leaderboard: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)
    
    @app_commands.command(name="set_sr_report_channel", description="Set the channel for automatic Star Resonance battle reports.")
    @is_admin_or_manager()
    @app_commands.describe(channel="The channel to set for reports.")
    async def set_sr_report_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set report channel for automatic battle reports."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # For testing, just acknowledge the setting
            await interaction.followup.send(f"✅ Star Resonance battle reports will now be sent to {channel.mention} (test mode).", ephemeral=True)
            
        except Exception as e:
            self.log.error(f"Error during set_sr_report_channel: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)
    
    async def send_battle_report_to_channel(self, battle_id: str):
        """Send battle report to configured channel (test mode)."""
        try:
            # For testing, just log that a report would be sent
            self.log.info(f"Would send battle report for battle {battle_id} (test mode)")
            
        except Exception as e:
            self.log.error(f"Error sending battle report to channel: {e}", exc_info=True)

async def setup(bot: commands.Bot):
    """Setup function for the cog."""
    await bot.add_cog(StarResonance(bot))