"""
Unified Currency System using centralized database.
"""

import os
import random
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import discord
from discord.ext import commands
from discord import app_commands
import pytz

from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager
from src.bot.command_groups import tc, admin

# Currency emoji constant
TC_EMOJI = os.getenv('TC_EMOJI', '💰')


"""
Define the single global /tc group here to avoid duplicate registrations across cogs.
Only the currency system uses /tc; other cogs are top-level.
"""


class CurrencySystem(BaseCog):
    """Custom currency system with work, slut, crime, and rob commands."""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.work_quips = self.load_work_quips()
        self.slut_quips = self.load_slut_quips()
        self.crime_quips = self.load_crime_quips()
    
    def load_work_quips(self) -> List[str]:
        """Load work quips from JSON file."""
        try:
            with open("data/assets/quips/work_quips.json", "r", encoding="utf-8") as f:
                quips = json.load(f)
                print(f"✅ Loaded {len(quips)} work quips")
                return quips
        except FileNotFoundError:
            print("⚠️ work_quips.json not found, using default quip")
            return ["You worked hard and earned some money!"]
        except json.JSONDecodeError:
            print("⚠️ Error parsing work_quips.json, using default quip")
            return ["You worked hard and earned some money!"]
    
    def load_slut_quips(self) -> Dict[str, List[str]]:
        """Load slut quips from JSON file."""
        try:
            with open("data/assets/quips/slut_quips.json", "r", encoding="utf-8") as f:
                quips = json.load(f)
                print(f"✅ Loaded {len(quips['success'])} success and {len(quips['failure'])} failure slut quips")
                return quips
        except FileNotFoundError:
            print("⚠️ slut_quips.json not found, using default quips")
            return {
                "success": ["You successfully seduced someone and earned money!"],
                "failure": ["You tried to seduce someone but failed."]
            }
        except json.JSONDecodeError:
            print("⚠️ Error parsing slut_quips.json, using default quips")
            return {
                "success": ["You successfully seduced someone and earned money!"],
                "failure": ["You tried to seduce someone but failed."]
            }
    
    def load_crime_quips(self) -> Dict[str, List[str]]:
        """Load crime quips from JSON file."""
        try:
            with open("data/assets/quips/crime_quips.json", "r", encoding="utf-8") as f:
                quips = json.load(f)
                print(f"✅ Loaded {len(quips['success'])} success and {len(quips['failure'])} failure crime quips")
                return quips
        except FileNotFoundError:
            print("⚠️ crime_quips.json not found, using default quips")
            return {
                "success": ["You successfully committed a crime and earned money!"],
                "failure": ["You tried to commit a crime but failed."]
            }
        except json.JSONDecodeError:
            print("⚠️ Error parsing crime_quips.json, using default quips")
            return {
                "success": ["You successfully committed a crime and earned money!"],
                "failure": ["You tried to commit a crime but failed."]
            }
    
    async def cog_load(self):
        """Initialize database when cog loads."""
        await super().cog_load()
        print("✅ Currency system database initialized")
        
        # Optional: scope slash commands to a single guild for faster registration
        # guild_id = os.getenv("DISCORD_GUILD_ID")
        # if guild_id:
        #     guild_obj = discord.Object(id=int(guild_id))
        #     for cmd in self.__cog_app_commands__:
        #         cmd.guild = guild_obj
    
    def get_next_reset_time(self) -> datetime:
        """Get the next 11AM EST reset time."""
        est = pytz.timezone('America/New_York')
        now_est = datetime.now(est)
        
        next_reset = now_est.replace(hour=11, minute=0, second=0, microsecond=0)
        if now_est >= next_reset:
            next_reset += timedelta(days=1)
        
        return next_reset
    
    async def has_collected_today(self, user_id: int, guild_id: int) -> bool:
        """Check if user has already collected salary today (since last 11AM EST reset)."""
        est = pytz.timezone('America/New_York')
        now_est = datetime.now(est)
        
        today_reset = now_est.replace(hour=11, minute=0, second=0, microsecond=0)
        if now_est < today_reset:
            today_reset -= timedelta(days=1)
        
        user_balance = await self.get_user_balance(user_id, guild_id)
        
        if user_balance.last_collect is None:
            return False
        
        if user_balance.last_collect.tzinfo is None:
            last_collect_utc = pytz.UTC.localize(user_balance.last_collect)
            last_collect_est = last_collect_utc.astimezone(est)
        else:
            last_collect_est = user_balance.last_collect.astimezone(est)
        
        return last_collect_est >= today_reset
    
    async def check_cooldown(self, user_id: int, guild_id: int, command: str) -> Tuple[bool, int]:
        """Check if user is on cooldown for a command. Returns (can_use, seconds_remaining)."""
        user = await self.get_user_balance(user_id, guild_id)
        settings = await self.get_guild_settings(guild_id)
        
        est = pytz.timezone('America/New_York')
        now = datetime.now(est)
        last_used = None
        cooldown_seconds = 0
        
        if command == "work":
            last_used = user.last_work
            cooldown_seconds = settings.work_cooldown
        elif command == "slut":
            last_used = user.last_slut
            cooldown_seconds = settings.slut_cooldown
        elif command == "crime":
            last_used = user.last_crime
            cooldown_seconds = settings.crime_cooldown
        elif command == "rob":
            last_used = user.last_rob
            cooldown_seconds = settings.rob_cooldown
        elif command == "collect":
            last_used = user.last_collect
            cooldown_seconds = settings.collect_cooldown
        
        if last_used is None:
            return True, 0
        
        # Ensure both datetimes are timezone-aware for comparison
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=est)
        else:
            # Convert to EST if it's in a different timezone
            last_used = last_used.astimezone(est)
        
        time_passed = (now - last_used).total_seconds()
        if time_passed >= cooldown_seconds:
            return True, 0
        else:
            return False, int(cooldown_seconds - time_passed)
    
    # ================= Command Groups =================
    # Use centrally defined admin subgroup (under /tc)
    
    # ================= Work Command =================

    # internal implementation (called by the public slash callback below)
    async def _work_impl(self, interaction: discord.Interaction):
        """Work command - earn money with no risk."""
        # Temporary minimal body to diagnose CommandSignatureMismatch vs TypeError in body
        # await interaction.response.send_message("ok", ephemeral=True)
        # return
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Check cooldown
        can_use, time_remaining = await self.check_cooldown(user_id, guild_id, "work")
        if not can_use:
            embed = discord.Embed(
                title="⏰ Work Cooldown",
                description=f"You're still tired from your last shift! Try again in {self.format_time_remaining(time_remaining)}.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get user balance and settings, then calculate earnings as percentage of total balance
        user_balance = await self.get_user_balance(user_id, guild_id)
        settings = await self.get_guild_settings(guild_id)
        total_balance = user_balance.cash + user_balance.bank
        min_earnings = int(total_balance * settings.work_min_percent)
        max_earnings = int(total_balance * settings.work_max_percent)
        calculated_earnings = max(1, random.randint(min_earnings, max_earnings))
        
        # Apply minimum reward: if calculated earnings < 100, award 100-150 instead
        if calculated_earnings < 100:
            earnings = random.randint(200, 500)
        else:
            earnings = calculated_earnings
        
        # Update user balance
        est = pytz.timezone('America/New_York')
        await self.db.update_user_balance(
            user_id, guild_id,
            cash_delta=earnings,
            total_earned_delta=earnings,
            last_work=datetime.now(est)
        )
        
        # Log transaction
        await self.log_transaction(
            user_id, guild_id, earnings, "work", success=True,
            reason=f"Worked and earned {earnings}"
        )
        
        # Get random work quip
        work_quip = random.choice(self.work_quips)
        
        # Create response
        embed = discord.Embed(
            title="💼 Work Complete!",
            description=f"{work_quip}\n\nYou earned {self.format_currency(earnings, settings.currency_symbol)}!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Next Work Available",
            value=f"In {self.format_time_remaining(settings.work_cooldown)}",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Slut Command =================
    @tc.command(name="slut", description="High-risk earning activity with potential consequences")
    @is_admin_or_manager()
    async def slut(self, interaction: discord.Interaction):
        """Slut command - high risk, high reward."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Check cooldown
        can_use, time_remaining = await self.check_cooldown(user_id, guild_id, "slut")
        if not can_use:
            embed = discord.Embed(
                title="⏰ Slut Cooldown",
                description=f"You need to rest! Try again in {self.format_time_remaining(time_remaining)}.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get user balance and settings, then calculate potential earnings as percentage of total balance
        user_balance = await self.get_user_balance(user_id, guild_id)
        settings = await self.get_guild_settings(guild_id)
        total_balance = user_balance.cash + user_balance.bank
        min_earnings = int(total_balance * settings.slut_min_percent)
        max_earnings = int(total_balance * settings.slut_max_percent)
        calculated_earnings = max(1, random.randint(min_earnings, max_earnings))
        
        # Apply minimum reward: if calculated earnings < 750, award 750-5000 instead
        if calculated_earnings < 750:
            potential_earnings = random.randint(750, 5000)
        else:
            potential_earnings = calculated_earnings
        
        # Check for failure
        success = random.random() > settings.slut_fail_chance
        
        if success:
            # Success - earn money
            await self.db.update_user_balance(
                user_id, guild_id,
                cash_delta=potential_earnings,
                total_earned_delta=potential_earnings,
                last_slut=datetime.now(pytz.timezone('America/New_York'))
            )
            
            await self.log_transaction(
                user_id, guild_id, potential_earnings, "slut", success=True,
                reason=f"Successful slut activity, earned {potential_earnings}"
            )
            
            # Get random success quip
            success_quip = random.choice(self.slut_quips["success"])
            
            embed = discord.Embed(
                title="💋 Slut Activity Successful!",
                description=f"{success_quip}\n\nYou earned {self.format_currency(potential_earnings, settings.currency_symbol)}!",
                color=discord.Color.green()
            )
        else:
            # Failure - lose money and get penalty
            penalty = int(potential_earnings * 0.25)  # Lose 25% of potential earnings
            current_balance = await self.get_user_balance(user_id, guild_id)
            actual_loss = min(penalty, current_balance.cash)  # Can't go below 0
            
            if actual_loss > 0:
                await self.db.update_user_balance(
                    user_id, guild_id,
                    cash_delta=-actual_loss,
                    total_spent_delta=actual_loss,
                    last_slut=datetime.now(pytz.timezone('America/New_York'))
                )
            
            await self.log_transaction(
                user_id, guild_id, -actual_loss, "slut", success=False,
                reason=f"Failed slut activity, lost {actual_loss}"
            )
            
            # Get random failure quip
            failure_quip = random.choice(self.slut_quips["failure"])
            
            embed = discord.Embed(
                title="💔 Slut Activity Failed!",
                description=f"{failure_quip}\n\nYou lost {self.format_currency(actual_loss, settings.currency_symbol)}!",
                color=discord.Color.red()
            )
        
        embed.add_field(
            name="Next Slut Available",
            value=f"In {self.format_time_remaining(settings.slut_cooldown)}",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Crime Command =================
    @tc.command(name="crime", description="Criminal activities with success/failure mechanics")
    @is_admin_or_manager()
    async def crime(self, interaction: discord.Interaction):
        """Crime command - criminal activities with consequences."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Check cooldown
        can_use, time_remaining = await self.check_cooldown(user_id, guild_id, "crime")
        if not can_use:
            embed = discord.Embed(
                title="⏰ Crime Cooldown",
                description=f"You're laying low! Try again in {self.format_time_remaining(time_remaining)}.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get user balance and settings, then calculate potential earnings as percentage of total balance
        user_balance = await self.get_user_balance(user_id, guild_id)
        settings = await self.get_guild_settings(guild_id)
        total_balance = user_balance.cash + user_balance.bank
        min_earnings = int(total_balance * settings.crime_min_percent)
        max_earnings = int(total_balance * settings.crime_max_percent)
        calculated_earnings = max(1, random.randint(min_earnings, max_earnings))
        
        # Apply minimum reward: if calculated earnings < 15000, award 15000-25000 instead
        if calculated_earnings < 15000:
            potential_earnings = random.randint(15000, 25000)
        else:
            potential_earnings = calculated_earnings
        
        # Check for success
        success = random.random() <= settings.crime_success_rate
        
        # Update crime stats
        await self.db.update_user_balance(
            user_id, guild_id,
            crimes_committed_delta=1,
            crimes_succeeded_delta=1 if success else 0,
            last_crime=datetime.now(pytz.timezone('America/New_York'))
        )
        
        if success:
            # Success - earn money
            await self.db.update_user_balance(
                user_id, guild_id,
                cash_delta=potential_earnings,
                total_earned_delta=potential_earnings
            )
            
            await self.log_transaction(
                user_id, guild_id, potential_earnings, "crime", success=True,
                reason=f"Successful crime, earned {potential_earnings}"
            )
            
            # Get random success quip
            success_quip = random.choice(self.crime_quips["success"])
            
            embed = discord.Embed(
                title="🔫 Crime Successful!",
                description=f"{success_quip}\n\nYou earned {self.format_currency(potential_earnings, settings.currency_symbol)}!",
                color=discord.Color.green()
            )
        else:
            # Failure - lose money and get longer cooldown
            penalty = int(potential_earnings * 0.5)  # Lose 50% of potential earnings
            current_balance = await self.get_user_balance(user_id, guild_id)
            actual_loss = min(penalty, current_balance.cash)  # Can't go below 0
            
            if actual_loss > 0:
                await self.db.update_user_balance(
                    user_id, guild_id,
                    cash_delta=-actual_loss,
                    total_spent_delta=actual_loss
                )
            
            await self.log_transaction(
                user_id, guild_id, -actual_loss, "crime", success=False,
                reason=f"Failed crime, lost {actual_loss}"
            )
            
            # Get random failure quip
            failure_quip = random.choice(self.crime_quips["failure"])
            
            embed = discord.Embed(
                title="🚨 Crime Failed!",
                description=f"{failure_quip}\n\nYou lost {self.format_currency(actual_loss, settings.currency_symbol)}!",
                color=discord.Color.red()
            )
        
        embed.add_field(
            name="Next Crime Available",
            value=f"In {self.format_time_remaining(settings.crime_cooldown)}",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Rob Command =================
    @tc.command(name="rob", description="Steal money from another user")
    @is_admin_or_manager()
    @app_commands.describe(target="The user you want to rob")
    async def rob(self, interaction: discord.Interaction, target: discord.Member):
        """Rob command - steal money from another user."""
        user_id = interaction.user.id
        target_id = target.id
        guild_id = interaction.guild.id
        
        # Can't rob yourself
        if user_id == target_id:
            embed = discord.Embed(
                title="❌ Invalid Target",
                description="You can't rob yourself!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check cooldown
        can_use, time_remaining = await self.check_cooldown(user_id, guild_id, "rob")
        if not can_use:
            embed = discord.Embed(
                title="⏰ Rob Cooldown",
                description=f"You're still hiding! Try again in {self.format_time_remaining(time_remaining)}.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if target has enough money
        target_balance = await self.get_user_balance(target_id, guild_id)
        if target_balance.cash < 50:  # Minimum amount to rob
            embed = discord.Embed(
                title="❌ Poor Target",
                description=f"{target.display_name} doesn't have enough cash to rob!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get settings and calculate new probability and steal amount
        settings = await self.get_guild_settings(guild_id)
        
        # Get robber's balance for networth calculation
        robber_balance = await self.get_user_balance(user_id, guild_id)
        robber_networth = robber_balance.cash + robber_balance.bank
        target_networth = target_balance.cash + target_balance.bank
        # Calculate success probability: robber_networth / (target_networth + robber_networth)
        if target_networth + robber_networth == 0:
            success_probability = 0.2  # Default to 20% if both have 0 networth
        else:
            success_probability = 1 - (robber_networth / (target_networth + robber_networth))

        success_probability = min(success_probability, 0.8)

        # Calculate steal amount: success_probability * target's cash
        potential_earnings = int(success_probability * target_balance.cash)
        
        # Ensure minimum earnings of 1 if calculated amount is 0
        potential_earnings = max(1, potential_earnings)
        
        # Check for success using the new probability
        success = random.random() <= success_probability
        
        # Update rob stats
        await self.db.update_user_balance(
            user_id, guild_id,
            robs_attempted_delta=1,
            robs_succeeded_delta=1 if success else 0,
            last_rob=datetime.now(pytz.timezone('America/New_York'))
        )

        emoji = discord.utils.get(self.bot.emojis, name="ratJAM")
        

        
        await interaction.response.send_message(f"{emoji} <@{user_id}> attempted to rob <@{target_id}>", ephemeral=False)
        if success:
            # Success - transfer money
            await self.db.update_user_balance(
                user_id, guild_id,
                cash_delta=potential_earnings,
                total_earned_delta=potential_earnings
            )
            await self.db.update_user_balance(
                target_id, guild_id,
                cash_delta=-potential_earnings,
                total_spent_delta=potential_earnings
            )
            
            await self.log_transaction(
                user_id, guild_id, potential_earnings, "rob", target_user_id=target_id,
                success=True, reason=f"Successfully robbed {target.display_name} for {potential_earnings}"
            )
            await self.log_transaction(
                target_id, guild_id, -potential_earnings, "rob", target_user_id=user_id,
                success=False, reason=f"Got robbed by {interaction.user.display_name} for {potential_earnings}"
            )
            
            embed = discord.Embed(
                title=f"{TC_EMOJI} Rob Successful!",
                description=f"You successfully robbed {target.display_name} and got {self.format_currency(potential_earnings, settings.currency_symbol)}!",
                color=discord.Color.green()
            )
            embed.set_image(url=os.getenv("ROB_SUCCESS_GIF"))
        else:
            # Failure - lose money (5-10% of total balance)
            current_balance = await self.get_user_balance(user_id, guild_id)
            total_balance = current_balance.cash + current_balance.bank
            
            # Calculate penalty as 5-10% of total balance
            penalty_percentage = random.uniform(0.05, 0.10)  # 5-10%
            penalty = int(total_balance * penalty_percentage)
            
            # Determine how to split the penalty between cash and bank
            if current_balance.cash >= penalty:
                # Take from cash first
                cash_loss = penalty
                bank_loss = 0
            else:
                # Take all cash and remainder from bank
                cash_loss = current_balance.cash
                bank_loss = penalty - current_balance.cash
            
            # Apply the penalty
            if penalty > 0:
                await self.db.update_user_balance(
                    user_id, guild_id,
                    cash_delta=-cash_loss,
                    bank_delta=-bank_loss,
                    total_spent_delta=penalty
                )
            
            await self.log_transaction(
                user_id, guild_id, -penalty, "rob", target_user_id=target_id,
                success=False, reason=f"Failed to rob {target.display_name}, lost {penalty} (penalty: {penalty_percentage:.1%} of total balance)"
            )
            
            embed = discord.Embed(
                title="🚨 Rob Failed!",
                description=f"You failed to rob {target.display_name} and lost {self.format_currency(penalty, settings.currency_symbol)}",
                color=discord.Color.red()
            )
            embed.set_image(url=os.getenv("ROB_FAILURE_GIF"))
        
        embed.add_field(
            name="Next Rob Available",
            value=f"In {self.format_time_remaining(settings.rob_cooldown)}",
            inline=False
        )
        
        await interaction.followup.send(embed=embed)
    
    # ================= Collect Command =================
    @tc.command(name="collect", description="Collect salary from your roles")
    @is_admin_or_manager()
    async def collect(self, interaction: discord.Interaction):
        """Collect salary from user's roles."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Check if user has already collected today (daily reset at 11AM EST)
        if await self.has_collected_today(user_id, guild_id):
            # Calculate time until next reset (11AM EST tomorrow)
            next_reset = self.get_next_reset_time()
            now_est = datetime.now(pytz.timezone('America/New_York'))
            time_until_reset = (next_reset - now_est).total_seconds()
            
            embed = discord.Embed(
                title="⏰ Already Collected Today",
                description=f"You've already collected your salary today! Next reset in {self.format_time_remaining(int(time_until_reset))}.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user has any roles
        if not interaction.user.roles:
            embed = discord.Embed(
                title="❌ No Roles",
                description="You don't have any roles to collect salary from!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get role salary data from database
        role_salaries = await self.db.get_role_salaries()
        
        if not role_salaries:
            embed = discord.Embed(
                title="❌ No Salary Data",
                description="No role salary data is configured! Contact an administrator.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check user's roles and calculate total salary
        total_salary = 0
        salary_breakdown = []
        user_roles = [role.name for role in interaction.user.roles if role.name != "@everyone"]
        
        for role_name in user_roles:
            if role_name in role_salaries:
                salary = role_salaries[role_name]["salary"]
                total_salary += salary
                salary_breakdown.append(f"**{role_name}**: {self.format_currency(salary)}")
        
        if total_salary == 0:
            embed = discord.Embed(
                title="❌ No Salary Roles",
                description="None of your roles have salary configured!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Add salary to user's bank
        await self.db.update_user_balance(
            user_id, guild_id,
            bank_delta=total_salary,
            total_earned_delta=total_salary,
            last_collect=datetime.now(pytz.timezone('America/New_York'))
        )
        
        # Log transaction
        settings = await self.get_guild_settings(guild_id)
        await self.log_transaction(
            user_id, guild_id, total_salary, "collect", success=True,
            reason=f"Salary deposited to bank from {len(salary_breakdown)} role(s)"
        )
        
        # Create response embed
        embed = discord.Embed(
            title=f"{TC_EMOJI} Salary Deposited!",
            description=f"Your salary from {len(salary_breakdown)} role(s) has been deposited to your bank!",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="💵 Total Salary",
            value=self.format_currency(total_salary, settings.currency_symbol),
            inline=False
        )
        
        embed.add_field(
            name="📋 Salary Breakdown",
            value="\n".join(salary_breakdown),
            inline=False
        )
        
        # Add next reset time
        next_reset = self.get_next_reset_time()
        embed.add_field(
            name="🔄 Next Reset",
            value=f"Salary resets daily at 11AM EST\nNext reset: <t:{int(next_reset.timestamp())}:F>",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Balance Command =================
    @tc.command(name="balance", description="Check your balance and stats")
    @is_admin_or_manager()
    @app_commands.describe(user="Check another user's balance (optional)")
    async def balance(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Check user's balance and statistics."""
        target_user = user or interaction.user
        user_id = target_user.id
        guild_id = interaction.guild.id
        
        # Get user balance and settings
        user_balance = await self.get_user_balance(user_id, guild_id)
        settings = await self.get_guild_settings(guild_id)
        rank = await self.db.get_user_rank(user_id, guild_id)
        
        # Create embed
        embed = discord.Embed(
            title=f"{settings.currency_symbol} {target_user.display_name}'s Balance",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name=f"{TC_EMOJI} Cash",
            value=self.format_currency(user_balance.cash, settings.currency_symbol),
            inline=True
        )
        embed.add_field(
            name="🏦 Bank",
            value=self.format_currency(user_balance.bank, settings.currency_symbol),
            inline=True
        )
        embed.add_field(
            name="📊 Total",
            value=self.format_currency(user_balance.cash + user_balance.bank, settings.currency_symbol),
            inline=True
        )
        
        embed.add_field(
            name="📈 Rank",
            value=f"#{rank}",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Leaderboard Command =================
    @tc.command(name="leaderboard", description="View the server's money leaderboard")
    @is_admin_or_manager()
    @app_commands.describe(page="Page number to view (default: 1)")
    async def leaderboard(self, interaction: discord.Interaction, page: int = 1):
        """Show the server's leaderboard."""
        guild_id = interaction.guild.id
        settings = await self.get_guild_settings(guild_id)
        
        # Validate page number
        if page < 1:
            page = 1
        
        # Get leaderboard data
        limit = 10
        offset = (page - 1) * limit
        leaderboard_data = await self.db.get_leaderboard(guild_id, limit, offset)
        
        if not leaderboard_data:
            embed = discord.Embed(
                title="📊 Leaderboard",
                description="No users found on the leaderboard!",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        # Create leaderboard list
        leaderboard_text = ""
        
        # Add leaderboard entries
        for i, (user_id, cash, bank, total) in enumerate(leaderboard_data, start=offset + 1):
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                username = user.display_name if hasattr(user, 'display_name') else user.name
            except:
                username = f"Unknown User ({user_id})"
            
            leaderboard_text += f"**#{i}** {username}: {self.format_currency(total, settings.currency_symbol)}\n"
        
        # Create embed with the list
        embed = discord.Embed(
            title=f"📊 {interaction.guild.name} Leaderboard",
            description=leaderboard_text,
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Page {page}")
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Give Command =================
    @tc.command(name="give", description="Give money to another user")
    @is_admin_or_manager()
    @app_commands.describe(user="The user to give money to", amount="Amount to give")
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        """Give money to another user."""
        user_id = interaction.user.id
        target_id = user.id
        guild_id = interaction.guild.id
        
        # Can't give to yourself
        if user_id == target_id:
            embed = discord.Embed(
                title="❌ Invalid Target",
                description="You can't give money to yourself!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Validate amount
        if amount <= 0:
            embed = discord.Embed(
                title="❌ Invalid Amount",
                description="Amount must be positive!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user has enough cash
        user_balance = await self.get_user_balance(user_id, guild_id)
        if user_balance.cash < amount:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"You don't have enough cash! You have {self.format_currency(user_balance.cash)}.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Transfer money
        await self.db.update_user_balance(
            user_id, guild_id,
            cash_delta=-amount,
            total_spent_delta=amount
        )
        await self.db.update_user_balance(
            target_id, guild_id,
            cash_delta=amount,
            total_earned_delta=amount
        )
        
        # Log transactions
        settings = await self.get_guild_settings(guild_id)
        await self.log_transaction(
            user_id, guild_id, -amount, "give", target_user_id=target_id,
            success=True, reason=f"Gave {amount} to {user.display_name}"
        )
        await self.log_transaction(
            target_id, guild_id, amount, "give", target_user_id=user_id,
            success=True, reason=f"Received {amount} from {interaction.user.display_name}"
        )
        
        embed = discord.Embed(
            title=f"{TC_EMOJI} Money Transferred!",
            description=f"You gave {self.format_currency(amount, settings.currency_symbol)} to <@{target_id}>!",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Deposit Command =================
    @tc.command(name="deposit", description="Move money from cash to bank")
    @is_admin_or_manager()
    @app_commands.describe(amount="Amount to deposit (or 'all' for all cash)")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        """Deposit money from cash to bank."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Get user balance
        user_balance = await self.get_user_balance(user_id, guild_id)
        
        # Parse amount
        if amount.lower() == "all":
            deposit_amount = user_balance.cash
        else:
            try:
                deposit_amount = int(amount)
            except ValueError:
                embed = discord.Embed(
                    title="❌ Invalid Amount",
                    description="Please enter a valid number or 'all'!",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        # Validate amount
        if deposit_amount <= 0:
            embed = discord.Embed(
                title="❌ Invalid Amount",
                description="Amount must be positive!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if deposit_amount > user_balance.cash:
            embed = discord.Embed(
                title="❌ Insufficient Cash",
                description=f"You don't have enough cash! You have {self.format_currency(user_balance.cash)}.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Transfer money
        await self.db.update_user_balance(
            user_id, guild_id,
            cash_delta=-deposit_amount,
            bank_delta=deposit_amount
        )
        
        # Log transaction
        settings = await self.get_guild_settings(guild_id)
        await self.log_transaction(
            user_id, guild_id, deposit_amount, "deposit", success=True,
            reason=f"Deposited {deposit_amount} to bank"
        )
        
        embed = discord.Embed(
            title="🏦 Deposit Successful!",
            description=f"You deposited {self.format_currency(deposit_amount, settings.currency_symbol)} to your bank!",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Withdraw Command =================
    @tc.command(name="withdraw", description="Move money from bank to cash")
    @is_admin_or_manager()
    @app_commands.describe(amount="Amount to withdraw (or 'all' for all bank)")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        """Withdraw money from bank to cash."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Get user balance
        user_balance = await self.get_user_balance(user_id, guild_id)
        
        # Parse amount
        if amount.lower() == "all":
            withdraw_amount = user_balance.bank
        else:
            try:
                withdraw_amount = int(amount)
            except ValueError:
                embed = discord.Embed(
                    title="❌ Invalid Amount",
                    description="Please enter a valid number or 'all'!",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        # Validate amount
        if withdraw_amount <= 0:
            embed = discord.Embed(
                title="❌ Invalid Amount",
                description="Amount must be positive!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if withdraw_amount > user_balance.bank:
            embed = discord.Embed(
                title="❌ Insufficient Bank Balance",
                description=f"You don't have enough in your bank! You have {self.format_currency(user_balance.bank)}.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Transfer money
        await self.db.update_user_balance(
            user_id, guild_id,
            cash_delta=withdraw_amount,
            bank_delta=-withdraw_amount
        )
        
        # Log transaction
        settings = await self.get_guild_settings(guild_id)
        await self.log_transaction(
            user_id, guild_id, withdraw_amount, "withdraw", success=True,
            reason=f"Withdrew {withdraw_amount} from bank"
        )
        
        embed = discord.Embed(
            title="💸 Withdrawal Successful!",
            description=f"You withdrew {self.format_currency(withdraw_amount, settings.currency_symbol)} from your bank!",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Admin Commands =================
    @admin.command(name="add-money", description="Add money to a user's account")
    @is_admin_or_manager()
    @app_commands.describe(user="The user to add money to", amount="Amount to add", location="Where to add the money")
    @app_commands.choices(location=[
        app_commands.Choice(name="Cash", value="cash"),
        app_commands.Choice(name="Bank", value="bank")
    ])
    async def add_money(self, interaction: discord.Interaction, user: discord.Member, amount: int, location: str = "cash"):
        """Add money to a user's account (admin only)."""
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need administrator permissions to use this command!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Validate amount
        if amount <= 0:
            embed = discord.Embed(
                title="❌ Invalid Amount",
                description="Amount must be positive!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Add money
        user_id = user.id
        guild_id = interaction.guild.id
        
        if location == "cash":
            await self.db.update_user_balance(user_id, guild_id, cash_delta=amount)
        else:
            await self.db.update_user_balance(user_id, guild_id, bank_delta=amount)
        
        # Log transaction
        settings = await self.get_guild_settings(guild_id)
        await self.log_transaction(
            user_id, guild_id, amount, "admin_add", success=True,
            reason=f"Admin {interaction.user.display_name} added {amount} to {location}"
        )
        
        embed = discord.Embed(
            title="✅ Money Added!",
            description=f"Added {self.format_currency(amount, settings.currency_symbol)} to {user.display_name}'s {location}!",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)
    
    @admin.command(name="remove-money", description="Remove money from a user's account")
    @is_admin_or_manager()
    @app_commands.describe(user="The user to remove money from", amount="Amount to remove", location="Where to remove the money from")
    @app_commands.choices(location=[
        app_commands.Choice(name="Cash", value="cash"),
        app_commands.Choice(name="Bank", value="bank")
    ])
    async def remove_money(self, interaction: discord.Interaction, user: discord.Member, amount: int, location: str = "cash"):
        """Remove money from a user's account (admin only)."""
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need administrator permissions to use this command!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Validate amount
        if amount <= 0:
            embed = discord.Embed(
                title="❌ Invalid Amount",
                description="Amount must be positive!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user has enough money
        user_balance = await self.get_user_balance(user.id, interaction.guild.id)
        current_amount = user_balance.cash if location == "cash" else user_balance.bank
        
        if current_amount < amount:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"{user.display_name} doesn't have enough {location}! They have {self.format_currency(current_amount)}.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Remove money
        user_id = user.id
        guild_id = interaction.guild.id
        
        if location == "cash":
            await self.db.update_user_balance(user_id, guild_id, cash_delta=-amount)
        else:
            await self.db.update_user_balance(user_id, guild_id, bank_delta=-amount)
        
        # Log transaction
        settings = await self.get_guild_settings(guild_id)
        await self.log_transaction(
            user_id, guild_id, -amount, "admin_remove", success=True,
            reason=f"Admin {interaction.user.display_name} removed {amount} from {location}"
        )
        
        embed = discord.Embed(
            title="✅ Money Removed!",
            description=f"Removed {self.format_currency(amount, settings.currency_symbol)} from {user.display_name}'s {location}!",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)
    
    @admin.command(name="reset-balance", description="Reset a user's balance to zero")
    @is_admin_or_manager()
    @app_commands.describe(user="The user to reset")
    async def reset_balance(self, interaction: discord.Interaction, user: discord.Member):
        """Reset a user's balance to zero (admin only)."""
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need administrator permissions to use this command!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get current balance
        user_balance = await self.get_user_balance(user.id, interaction.guild.id)
        
        # Reset balance
        await self.db.update_user_balance(
            user.id, interaction.guild.id,
            cash_delta=-user_balance.cash,
            bank_delta=-user_balance.bank
        )
        
        # Log transaction
        settings = await self.get_guild_settings(interaction.guild.id)
        await self.log_transaction(
            user.id, interaction.guild.id, -(user_balance.cash + user_balance.bank), "admin_reset", success=True,
            reason=f"Admin {interaction.user.display_name} reset balance"
        )
        
        embed = discord.Embed(
            title="✅ Balance Reset!",
            description=f"Reset {user.display_name}'s balance to zero!",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)
    
    @admin.command(name="economy-stats", description="View economy statistics")
    @is_admin_or_manager()
    async def economy_stats(self, interaction: discord.Interaction):
        """View economy statistics (admin only)."""
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need administrator permissions to use this command!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        guild_id = interaction.guild.id
        settings = await self.get_guild_settings(guild_id)
        
        # Get economy stats
        stats = await self.get_database_stats()
        
        embed = discord.Embed(
            title="📊 Economy Statistics",
            description=f"Statistics for {interaction.guild.name}",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="👥 Total Users",
            value=str(stats.get('user_balances', 0)),
            inline=True
        )
        embed.add_field(
            name=f"{TC_EMOJI} Total Money",
            value=self.format_currency(stats.get('total_money', 0), settings.currency_symbol),
            inline=True
        )
        embed.add_field(
            name="📈 Total Transactions",
            value=str(stats.get('transactions', 0)),
            inline=True
        )
        
        embed.add_field(
            name="⚙️ Settings",
            value=f"Work Cooldown: {self.format_time_remaining(settings.work_cooldown)}\n"
                  f"Slut Cooldown: {self.format_time_remaining(settings.slut_cooldown)}\n"
                  f"Crime Cooldown: {self.format_time_remaining(settings.crime_cooldown)}\n"
                  f"Rob Cooldown: {self.format_time_remaining(settings.rob_cooldown)}",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    
    @admin.command(name="database-stats", description="View database statistics")
    @is_admin_or_manager()
    async def database_stats(self, interaction: discord.Interaction):
        """View database statistics (admin only)."""
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need administrator permissions to use this command!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get database stats
        stats = await self.get_database_stats()
        
        embed = discord.Embed(
            title="📊 Database Statistics",
            description=f"Statistics for {interaction.guild.name}",
            color=discord.Color.blue()
        )
        
        # Add stats fields
        embed.add_field(
            name="👥 Users",
            value=str(stats.get('user_balances', 0)),
            inline=True
        )
        embed.add_field(
            name=f"{TC_EMOJI} Transactions",
            value=str(stats.get('transactions', 0)),
            inline=True
        )
        embed.add_field(
            name="🎮 Games",
            value=f"Poker: {stats.get('poker_sessions', 0)}\nCrash: {stats.get('crash_bets', 0)}\nDuels: {stats.get('duel_matches', 0)}",
            inline=True
        )
        
        embed.add_field(
            name="🎯 Predictions",
            value=f"Active: {stats.get('predictions', 0)}\nBets: {stats.get('prediction_bets', 0)}",
            inline=True
        )
        
        embed.add_field(
            name="🎲 Lottery",
            value=f"Entries: {stats.get('lottery_entries', 0)}\nWinners: {stats.get('lottery_winners', 0)}",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

    # ---- Public /tc work (wrapper) ----
    @tc.command(name="work", description="Earn money through legitimate work")
    # @is_admin_or_manager()  # optional; keep or remove based on who should use it
    async def work(self, interaction: discord.Interaction):
        await self._work_impl(interaction)


# ================= Setup Function =================
async def setup(bot: commands.Bot):
    await bot.add_cog(CurrencySystem(bot))
