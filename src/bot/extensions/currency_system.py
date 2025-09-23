"""
Custom Currency System for Discord Bot

A comprehensive economy system with work, slut, crime, and rob commands.
Based on UnbelievaBoat mechanics but implemented as a standalone system.
"""

import os
import asyncio
import aiosqlite
import discord
from discord.ext import commands
from discord import app_commands
import random
import time
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

from src.utils.utils import is_admin_or_manager

# ================= Configuration =================
CURRENCY_EMOJI = os.getenv("CURRENCY_EMOJI", "💰")
DATABASE_PATH = "data/databases/currency.db"

# Default economy settings
DEFAULT_SETTINGS = {
    "currency_symbol": CURRENCY_EMOJI,
    "work_cooldown": 30,  # 30 seconds
    "slut_cooldown": 90,  # 1 minute 30 seconds
    "crime_cooldown": 180,  # 3 minutes
    "rob_cooldown": 900,  # 15 minutes
    "work_min_percent": 0.01,  # 1% of total balance
    "work_max_percent": 0.05,  # 5% of total balance
    "slut_min_percent": 0.02,  # 2% of total balance
    "slut_max_percent": 0.08,  # 8% of total balance
    "slut_fail_chance": 0.3,  # 30% chance
    "crime_min_percent": 0.03,  # 3% of total balance
    "crime_max_percent": 0.12,  # 12% of total balance
    "crime_success_rate": 0.4,  # 40% success
    "rob_min_percent": 0.02,  # 2% of target's total balance
    "rob_max_percent": 0.08,  # 8% of target's total balance
    "rob_success_rate": 0.3,  # 30% success
}

# ================= Data Classes =================
@dataclass
class UserBalance:
    user_id: int
    guild_id: int
    cash: int = 0
    bank: int = 0
    total_earned: int = 0
    total_spent: int = 0
    crimes_committed: int = 0
    crimes_succeeded: int = 0
    robs_attempted: int = 0
    robs_succeeded: int = 0
    last_work: Optional[datetime] = None
    last_slut: Optional[datetime] = None
    last_crime: Optional[datetime] = None
    last_rob: Optional[datetime] = None

@dataclass
class Transaction:
    id: int
    user_id: int
    guild_id: int
    amount: int
    transaction_type: str
    target_user_id: Optional[int] = None
    success: bool = True
    reason: str = ""
    created_at: datetime = None

@dataclass
class GuildSettings:
    guild_id: int
    currency_symbol: str = CURRENCY_EMOJI
    work_cooldown: int = 30
    slut_cooldown: int = 90
    crime_cooldown: int = 180
    rob_cooldown: int = 900
    work_min_percent: float = 0.01  # 1% of total balance
    work_max_percent: float = 0.05  # 5% of total balance
    slut_min_percent: float = 0.02  # 2% of total balance
    slut_max_percent: float = 0.08  # 8% of total balance
    slut_fail_chance: float = 0.3
    crime_min_percent: float = 0.03  # 3% of total balance
    crime_max_percent: float = 0.12  # 12% of total balance
    crime_success_rate: float = 0.4
    rob_min_percent: float = 0.02  # 2% of target's total balance
    rob_max_percent: float = 0.08  # 8% of target's total balance
    rob_success_rate: float = 0.3

# ================= Database Manager =================
class CurrencyDatabase:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._lock = asyncio.Lock()
    
    async def init_database(self):
        """Initialize the database with required tables."""
        async with self._lock:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            async with aiosqlite.connect(self.db_path) as db:
                # User balances table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_balances (
                        user_id INTEGER,
                        guild_id INTEGER,
                        cash INTEGER DEFAULT 0,
                        bank INTEGER DEFAULT 0,
                        total_earned INTEGER DEFAULT 0,
                        total_spent INTEGER DEFAULT 0,
                        crimes_committed INTEGER DEFAULT 0,
                        crimes_succeeded INTEGER DEFAULT 0,
                        robs_attempted INTEGER DEFAULT 0,
                        robs_succeeded INTEGER DEFAULT 0,
                        last_work TIMESTAMP,
                        last_slut TIMESTAMP,
                        last_crime TIMESTAMP,
                        last_rob TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (user_id, guild_id)
                    )
                """)
                
                # Transactions table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        guild_id INTEGER,
                        amount INTEGER,
                        transaction_type TEXT,
                        target_user_id INTEGER,
                        success BOOLEAN,
                        reason TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Guild settings table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS guild_settings (
                        guild_id INTEGER PRIMARY KEY,
                        currency_symbol TEXT DEFAULT '💰',
                        work_cooldown INTEGER DEFAULT 30,
                        slut_cooldown INTEGER DEFAULT 90,
                        crime_cooldown INTEGER DEFAULT 180,
                        rob_cooldown INTEGER DEFAULT 900,
                        work_min_percent REAL DEFAULT 0.01,
                        work_max_percent REAL DEFAULT 0.05,
                        slut_min_percent REAL DEFAULT 0.02,
                        slut_max_percent REAL DEFAULT 0.08,
                        slut_fail_chance REAL DEFAULT 0.3,
                        crime_min_percent REAL DEFAULT 0.03,
                        crime_max_percent REAL DEFAULT 0.12,
                        crime_success_rate REAL DEFAULT 0.4,
                        rob_min_percent REAL DEFAULT 0.02,
                        rob_max_percent REAL DEFAULT 0.08,
                        rob_success_rate REAL DEFAULT 0.3,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                await db.commit()
                
                # Migrate existing guild settings to new default cooldowns
                await self.migrate_guild_settings()
    
    async def migrate_guild_settings(self):
        """Migrate existing guild settings to new percentage-based earnings."""
        async with aiosqlite.connect(self.db_path) as db:
            # First, add new percentage columns if they don't exist
            try:
                await db.execute("ALTER TABLE guild_settings ADD COLUMN work_min_percent REAL DEFAULT 0.01")
                await db.execute("ALTER TABLE guild_settings ADD COLUMN work_max_percent REAL DEFAULT 0.05")
                await db.execute("ALTER TABLE guild_settings ADD COLUMN slut_min_percent REAL DEFAULT 0.02")
                await db.execute("ALTER TABLE guild_settings ADD COLUMN slut_max_percent REAL DEFAULT 0.08")
                await db.execute("ALTER TABLE guild_settings ADD COLUMN crime_min_percent REAL DEFAULT 0.03")
                await db.execute("ALTER TABLE guild_settings ADD COLUMN crime_max_percent REAL DEFAULT 0.12")
                await db.execute("ALTER TABLE guild_settings ADD COLUMN rob_min_percent REAL DEFAULT 0.02")
                await db.execute("ALTER TABLE guild_settings ADD COLUMN rob_max_percent REAL DEFAULT 0.08")
                print("✅ Added new percentage columns to guild_settings table")
            except Exception as e:
                # Columns might already exist, that's okay
                print(f"ℹ️  Percentage columns may already exist: {e}")
            
            # Update ALL existing guild settings with new percentage values from DEFAULT_SETTINGS
            await db.execute("""
                UPDATE guild_settings 
                SET work_cooldown = ?, 
                    slut_cooldown = ?, 
                    crime_cooldown = ?,
                    work_min_percent = ?,
                    work_max_percent = ?,
                    slut_min_percent = ?,
                    slut_max_percent = ?,
                    crime_min_percent = ?,
                    crime_max_percent = ?,
                    rob_min_percent = ?,
                    rob_max_percent = ?
            """, (
                DEFAULT_SETTINGS["work_cooldown"],
                DEFAULT_SETTINGS["slut_cooldown"],
                DEFAULT_SETTINGS["crime_cooldown"],
                DEFAULT_SETTINGS["work_min_percent"],
                DEFAULT_SETTINGS["work_max_percent"],
                DEFAULT_SETTINGS["slut_min_percent"],
                DEFAULT_SETTINGS["slut_max_percent"],
                DEFAULT_SETTINGS["crime_min_percent"],
                DEFAULT_SETTINGS["crime_max_percent"],
                DEFAULT_SETTINGS["rob_min_percent"],
                DEFAULT_SETTINGS["rob_max_percent"]
            ))
            await db.commit()
            print("✅ Migrated existing guild settings to new percentage-based earnings")
    
    async def get_user_balance(self, user_id: int, guild_id: int) -> UserBalance:
        """Get user's balance information."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM user_balances 
                WHERE user_id = ? AND guild_id = ?
            """, (user_id, guild_id)) as cursor:
                row = await cursor.fetchone()
                
                if row:
                    return UserBalance(
                        user_id=row["user_id"],
                        guild_id=row["guild_id"],
                        cash=row["cash"],
                        bank=row["bank"],
                        total_earned=row["total_earned"],
                        total_spent=row["total_spent"],
                        crimes_committed=row["crimes_committed"],
                        crimes_succeeded=row["crimes_succeeded"],
                        robs_attempted=row["robs_attempted"],
                        robs_succeeded=row["robs_succeeded"],
                        last_work=datetime.fromisoformat(row["last_work"]) if row["last_work"] else None,
                        last_slut=datetime.fromisoformat(row["last_slut"]) if row["last_slut"] else None,
                        last_crime=datetime.fromisoformat(row["last_crime"]) if row["last_crime"] else None,
                        last_rob=datetime.fromisoformat(row["last_rob"]) if row["last_rob"] else None
                    )
                else:
                    # Create new user record
                    await self.create_user(user_id, guild_id)
                    return UserBalance(user_id=user_id, guild_id=guild_id)
    
    async def create_user(self, user_id: int, guild_id: int):
        """Create a new user record."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO user_balances (user_id, guild_id)
                VALUES (?, ?)
            """, (user_id, guild_id))
            await db.commit()
    
    async def update_user_balance(self, user_id: int, guild_id: int, 
                                cash_delta: int = 0, bank_delta: int = 0,
                                total_earned_delta: int = 0, total_spent_delta: int = 0,
                                crimes_committed_delta: int = 0, crimes_succeeded_delta: int = 0,
                                robs_attempted_delta: int = 0, robs_succeeded_delta: int = 0,
                                last_work: Optional[datetime] = None,
                                last_slut: Optional[datetime] = None,
                                last_crime: Optional[datetime] = None,
                                last_rob: Optional[datetime] = None):
        """Update user's balance and stats."""
        async with aiosqlite.connect(self.db_path) as db:
            # Ensure user exists
            await self.create_user(user_id, guild_id)
            
            # Build update query dynamically
            updates = []
            params = []
            
            if cash_delta != 0:
                updates.append("cash = cash + ?")
                params.append(cash_delta)
            
            if bank_delta != 0:
                updates.append("bank = bank + ?")
                params.append(bank_delta)
            
            if total_earned_delta != 0:
                updates.append("total_earned = total_earned + ?")
                params.append(total_earned_delta)
            
            if total_spent_delta != 0:
                updates.append("total_spent = total_spent + ?")
                params.append(total_spent_delta)
            
            if crimes_committed_delta != 0:
                updates.append("crimes_committed = crimes_committed + ?")
                params.append(crimes_committed_delta)
            
            if crimes_succeeded_delta != 0:
                updates.append("crimes_succeeded = crimes_succeeded + ?")
                params.append(crimes_succeeded_delta)
            
            if robs_attempted_delta != 0:
                updates.append("robs_attempted = robs_attempted + ?")
                params.append(robs_attempted_delta)
            
            if robs_succeeded_delta != 0:
                updates.append("robs_succeeded = robs_succeeded + ?")
                params.append(robs_succeeded_delta)
            
            if last_work:
                updates.append("last_work = ?")
                params.append(last_work.isoformat())
            
            if last_slut:
                updates.append("last_slut = ?")
                params.append(last_slut.isoformat())
            
            if last_crime:
                updates.append("last_crime = ?")
                params.append(last_crime.isoformat())
            
            if last_rob:
                updates.append("last_rob = ?")
                params.append(last_rob.isoformat())
            
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                query = f"UPDATE user_balances SET {', '.join(updates)} WHERE user_id = ? AND guild_id = ?"
                params.extend([user_id, guild_id])
                
                await db.execute(query, params)
                await db.commit()
    
    async def log_transaction(self, user_id: int, guild_id: int, amount: int,
                            transaction_type: str, target_user_id: Optional[int] = None,
                            success: bool = True, reason: str = ""):
        """Log a transaction."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO transactions 
                (user_id, guild_id, amount, transaction_type, target_user_id, success, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, guild_id, amount, transaction_type, target_user_id, success, reason))
            await db.commit()
    
    async def get_guild_settings(self, guild_id: int) -> GuildSettings:
        """Get guild economy settings."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM guild_settings WHERE guild_id = ?
            """, (guild_id,)) as cursor:
                row = await cursor.fetchone()
                
                if row:
                    return GuildSettings(
                        guild_id=row["guild_id"],
                        currency_symbol=row["currency_symbol"],
                        work_cooldown=row["work_cooldown"],
                        slut_cooldown=row["slut_cooldown"],
                        crime_cooldown=row["crime_cooldown"],
                        rob_cooldown=row["rob_cooldown"],
                        work_min_percent=row["work_min_percent"],
                        work_max_percent=row["work_max_percent"],
                        slut_min_percent=row["slut_min_percent"],
                        slut_max_percent=row["slut_max_percent"],
                        slut_fail_chance=row["slut_fail_chance"],
                        crime_min_percent=row["crime_min_percent"],
                        crime_max_percent=row["crime_max_percent"],
                        crime_success_rate=row["crime_success_rate"],
                        rob_min_percent=row["rob_min_percent"],
                        rob_max_percent=row["rob_max_percent"],
                        rob_success_rate=row["rob_success_rate"]
                    )
                else:
                    # Create default settings
                    await self.create_guild_settings(guild_id)
                    return GuildSettings(guild_id=guild_id)
    
    async def create_guild_settings(self, guild_id: int):
        """Create default guild settings."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)
            """, (guild_id,))
            await db.commit()
    
    async def get_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0) -> List[Tuple[int, int, int, int]]:
        """Get leaderboard (user_id, cash, bank, total)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT user_id, cash, bank, (cash + bank) as total
                FROM user_balances 
                WHERE guild_id = ?
                ORDER BY total DESC
                LIMIT ? OFFSET ?
            """, (guild_id, limit, offset)) as cursor:
                return await cursor.fetchall()
    
    async def get_user_rank(self, user_id: int, guild_id: int) -> int:
        """Get user's rank in the leaderboard."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT COUNT(*) + 1 as rank
                FROM user_balances 
                WHERE guild_id = ? AND (cash + bank) > (
                    SELECT (cash + bank) FROM user_balances 
                    WHERE user_id = ? AND guild_id = ?
                )
            """, (guild_id, user_id, guild_id)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 1

# ================= Main Cog =================
class CurrencySystem(commands.Cog):
    """Custom currency system with work, slut, crime, and rob commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = CurrencyDatabase()
        self.work_quips = self.load_work_quips()
        self.slut_quips = self.load_slut_quips()
        self.crime_quips = self.load_crime_quips()
        
        # Optional: scope slash commands to a single guild for faster registration
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild_obj = discord.Object(id=int(guild_id))
            for cmd in self.__cog_app_commands__:
                cmd.guild = guild_obj
    
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
        await self.db.init_database()
        print("✅ Currency system database initialized")
    
    def format_currency(self, amount: int, symbol: str = CURRENCY_EMOJI) -> str:
        """Format currency amount with symbol."""
        return f"{symbol} {amount:,}"
    
    def format_time_remaining(self, seconds: int) -> str:
        """Format time remaining in human readable format."""
        if seconds < 60:
            return f"{seconds} seconds"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes == 0:
                return f"{hours} hour{'s' if hours != 1 else ''}"
            else:
                return f"{hours}h {minutes}m"
    
    async def check_cooldown(self, user_id: int, guild_id: int, command: str) -> Tuple[bool, int]:
        """Check if user is on cooldown for a command. Returns (can_use, seconds_remaining)."""
        user = await self.db.get_user_balance(user_id, guild_id)
        settings = await self.db.get_guild_settings(guild_id)
        
        now = datetime.now()
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
        
        if last_used is None:
            return True, 0
        
        time_passed = (now - last_used).total_seconds()
        if time_passed >= cooldown_seconds:
            return True, 0
        else:
            return False, int(cooldown_seconds - time_passed)
    
    # ================= Command Groups =================
    economy = app_commands.Group(name="economy", description="Custom currency system commands")
    admin = app_commands.Group(name="admin", description="Admin commands for economy management", parent=economy)
    
    # ================= Work Command =================
    @economy.command(name="work", description="Earn money through legitimate work")
    async def work(self, interaction: discord.Interaction):
        """Work command - earn money with no risk."""
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
        user_balance = await self.db.get_user_balance(user_id, guild_id)
        settings = await self.db.get_guild_settings(guild_id)
        total_balance = user_balance.cash + user_balance.bank
        min_earnings = int(total_balance * settings.work_min_percent)
        max_earnings = int(total_balance * settings.work_max_percent)
        # Ensure minimum earnings of 1 if user has no money
        earnings = max(1, random.randint(min_earnings, max_earnings))
        
        # Update user balance
        await self.db.update_user_balance(
            user_id, guild_id,
            cash_delta=earnings,
            total_earned_delta=earnings,
            last_work=datetime.now()
        )
        
        # Log transaction
        await self.db.log_transaction(
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
    @economy.command(name="slut", description="High-risk earning activity with potential consequences")
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
        user_balance = await self.db.get_user_balance(user_id, guild_id)
        settings = await self.db.get_guild_settings(guild_id)
        total_balance = user_balance.cash + user_balance.bank
        min_earnings = int(total_balance * settings.slut_min_percent)
        max_earnings = int(total_balance * settings.slut_max_percent)
        # Ensure minimum earnings of 1 if user has no money
        potential_earnings = max(1, random.randint(min_earnings, max_earnings))
        
        # Check for failure
        success = random.random() > settings.slut_fail_chance
        
        if success:
            # Success - earn money
            await self.db.update_user_balance(
                user_id, guild_id,
                cash_delta=potential_earnings,
                total_earned_delta=potential_earnings,
                last_slut=datetime.now()
            )
            
            await self.db.log_transaction(
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
            current_balance = await self.db.get_user_balance(user_id, guild_id)
            actual_loss = min(penalty, current_balance.cash)  # Can't go below 0
            
            if actual_loss > 0:
                await self.db.update_user_balance(
                    user_id, guild_id,
                    cash_delta=-actual_loss,
                    total_spent_delta=actual_loss,
                    last_slut=datetime.now()
                )
            
            await self.db.log_transaction(
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
    @economy.command(name="crime", description="Criminal activities with success/failure mechanics")
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
        user_balance = await self.db.get_user_balance(user_id, guild_id)
        settings = await self.db.get_guild_settings(guild_id)
        total_balance = user_balance.cash + user_balance.bank
        min_earnings = int(total_balance * settings.crime_min_percent)
        max_earnings = int(total_balance * settings.crime_max_percent)
        # Ensure minimum earnings of 1 if user has no money
        potential_earnings = max(1, random.randint(min_earnings, max_earnings))
        
        # Check for success
        success = random.random() <= settings.crime_success_rate
        
        # Update crime stats
        await self.db.update_user_balance(
            user_id, guild_id,
            crimes_committed_delta=1,
            crimes_succeeded_delta=1 if success else 0,
            last_crime=datetime.now()
        )
        
        if success:
            # Success - earn money
            await self.db.update_user_balance(
                user_id, guild_id,
                cash_delta=potential_earnings,
                total_earned_delta=potential_earnings
            )
            
            await self.db.log_transaction(
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
            current_balance = await self.db.get_user_balance(user_id, guild_id)
            actual_loss = min(penalty, current_balance.cash)  # Can't go below 0
            
            if actual_loss > 0:
                await self.db.update_user_balance(
                    user_id, guild_id,
                    cash_delta=-actual_loss,
                    total_spent_delta=actual_loss
                )
            
            await self.db.log_transaction(
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
    @economy.command(name="rob", description="Steal money from another user")
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
        target_balance = await self.db.get_user_balance(target_id, guild_id)
        if target_balance.cash < 50:  # Minimum amount to rob
            embed = discord.Embed(
                title="❌ Poor Target",
                description=f"{target.display_name} doesn't have enough cash to rob!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get settings and calculate potential earnings as percentage of target's total balance
        settings = await self.db.get_guild_settings(guild_id)
        target_total = target_balance.cash + target_balance.bank
        min_earnings = int(target_total * settings.rob_min_percent)
        max_earnings = int(target_total * settings.rob_max_percent)
        # Ensure we don't rob more than target has in cash
        max_rob = min(target_balance.cash, max_earnings)
        # Ensure minimum earnings of 1 if target has no money
        potential_earnings = max(1, random.randint(min_earnings, max_rob))
        
        # Check for success
        success = random.random() <= settings.rob_success_rate
        
        # Update rob stats
        await self.db.update_user_balance(
            user_id, guild_id,
            robs_attempted_delta=1,
            robs_succeeded_delta=1 if success else 0,
            last_rob=datetime.now()
        )
        
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
            
            await self.db.log_transaction(
                user_id, guild_id, potential_earnings, "rob", target_user_id=target_id,
                success=True, reason=f"Successfully robbed {target.display_name} for {potential_earnings}"
            )
            await self.db.log_transaction(
                target_id, guild_id, -potential_earnings, "rob", target_user_id=user_id,
                success=False, reason=f"Got robbed by {interaction.user.display_name} for {potential_earnings}"
            )
            
            embed = discord.Embed(
                title="💰 Rob Successful!",
                description=f"You successfully robbed {target.display_name} and got {self.format_currency(potential_earnings, settings.currency_symbol)}!",
                color=discord.Color.green()
            )
        else:
            # Failure - lose money
            penalty = int(potential_earnings * 0.25)  # Lose 25% of potential earnings
            current_balance = await self.db.get_user_balance(user_id, guild_id)
            actual_loss = min(penalty, current_balance.cash)  # Can't go below 0
            
            if actual_loss > 0:
                await self.db.update_user_balance(
                    user_id, guild_id,
                    cash_delta=-actual_loss,
                    total_spent_delta=actual_loss
                )
            
            await self.db.log_transaction(
                user_id, guild_id, -actual_loss, "rob", target_user_id=target_id,
                success=False, reason=f"Failed to rob {target.display_name}, lost {actual_loss}"
            )
            
            embed = discord.Embed(
                title="🚨 Rob Failed!",
                description=f"You failed to rob {target.display_name} and lost {self.format_currency(actual_loss, settings.currency_symbol)}!",
                color=discord.Color.red()
            )
        
        embed.add_field(
            name="Next Rob Available",
            value=f"In {self.format_time_remaining(settings.rob_cooldown)}",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Balance Command =================
    @economy.command(name="balance", description="Check your balance and stats")
    @is_admin_or_manager()
    @app_commands.describe(user="Check another user's balance (optional)")
    async def balance(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Check user's balance and statistics."""
        target_user = user or interaction.user
        user_id = target_user.id
        guild_id = interaction.guild.id
        
        # Get user balance and settings
        user_balance = await self.db.get_user_balance(user_id, guild_id)
        settings = await self.db.get_guild_settings(guild_id)
        rank = await self.db.get_user_rank(user_id, guild_id)
        
        # Create embed
        embed = discord.Embed(
            title=f"{settings.currency_symbol} {target_user.display_name}'s Balance",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="💰 Cash",
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
    @economy.command(name="leaderboard", description="View the server's money leaderboard")
    @is_admin_or_manager()
    @app_commands.describe(page="Page number to view (default: 1)")
    async def leaderboard(self, interaction: discord.Interaction, page: int = 1):
        """Show the server's leaderboard."""
        guild_id = interaction.guild.id
        settings = await self.db.get_guild_settings(guild_id)
        
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
    @economy.command(name="give", description="Give money to another user")
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
        user_balance = await self.db.get_user_balance(user_id, guild_id)
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
        settings = await self.db.get_guild_settings(guild_id)
        await self.db.log_transaction(
            user_id, guild_id, -amount, "give", target_user_id=target_id,
            success=True, reason=f"Gave {amount} to {user.display_name}"
        )
        await self.db.log_transaction(
            target_id, guild_id, amount, "give", target_user_id=user_id,
            success=True, reason=f"Received {amount} from {interaction.user.display_name}"
        )
        
        embed = discord.Embed(
            title="💰 Money Transferred!",
            description=f"You gave {self.format_currency(amount, settings.currency_symbol)} to {user.display_name}!",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ================= Deposit Command =================
    @economy.command(name="deposit", description="Move money from cash to bank")
    @is_admin_or_manager()
    @app_commands.describe(amount="Amount to deposit (or 'all' for all cash)")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        """Deposit money from cash to bank."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Get user balance
        user_balance = await self.db.get_user_balance(user_id, guild_id)
        
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
        settings = await self.db.get_guild_settings(guild_id)
        await self.db.log_transaction(
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
    @economy.command(name="withdraw", description="Move money from bank to cash")
    @is_admin_or_manager()
    @app_commands.describe(amount="Amount to withdraw (or 'all' for all bank)")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        """Withdraw money from bank to cash."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Get user balance
        user_balance = await self.db.get_user_balance(user_id, guild_id)
        
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
        settings = await self.db.get_guild_settings(guild_id)
        await self.db.log_transaction(
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
        settings = await self.db.get_guild_settings(guild_id)
        await self.db.log_transaction(
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
        user_balance = await self.db.get_user_balance(user.id, interaction.guild.id)
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
        settings = await self.db.get_guild_settings(guild_id)
        await self.db.log_transaction(
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
        user_balance = await self.db.get_user_balance(user.id, interaction.guild.id)
        
        # Reset balance
        await self.db.update_user_balance(
            user.id, interaction.guild.id,
            cash_delta=-user_balance.cash,
            bank_delta=-user_balance.bank
        )
        
        # Log transaction
        settings = await self.db.get_guild_settings(interaction.guild.id)
        await self.db.log_transaction(
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
        settings = await self.db.get_guild_settings(guild_id)
        
        # Get economy stats
        async with aiosqlite.connect(self.db.db_path) as db:
            # Total users
            async with db.execute("SELECT COUNT(*) FROM user_balances WHERE guild_id = ?", (guild_id,)) as cursor:
                total_users = (await cursor.fetchone())[0]
            
            # Total money in circulation
            async with db.execute("SELECT SUM(cash + bank) FROM user_balances WHERE guild_id = ?", (guild_id,)) as cursor:
                total_money = (await cursor.fetchone())[0] or 0
            
            # Total transactions
            async with db.execute("SELECT COUNT(*) FROM transactions WHERE guild_id = ?", (guild_id,)) as cursor:
                total_transactions = (await cursor.fetchone())[0]
        
        embed = discord.Embed(
            title="📊 Economy Statistics",
            description=f"Statistics for {interaction.guild.name}",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="👥 Total Users",
            value=str(total_users),
            inline=True
        )
        embed.add_field(
            name="💰 Total Money",
            value=self.format_currency(total_money, settings.currency_symbol),
            inline=True
        )
        embed.add_field(
            name="📈 Total Transactions",
            value=str(total_transactions),
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

# ================= Setup Function =================
async def setup(bot: commands.Bot):
    await bot.add_cog(CurrencySystem(bot))
