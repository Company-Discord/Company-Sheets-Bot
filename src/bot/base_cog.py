"""
Base cog class with unified database functionality.
"""

import discord
from discord.ext import commands
from typing import Optional

from src.database.database import Database


class BaseCog(commands.Cog):
    """Base cog class that provides shared unified database functionality."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: Optional[Database] = None
    
    async def cog_load(self):
        """Initialize the shared database connection."""
        # Get or create the shared database instance
        if not hasattr(self.bot, '_unified_db'):
            self.bot._unified_db = Database()
            await self.bot._unified_db.init_database()
        
        self.db = self.bot._unified_db
    
    def format_currency(self, amount: int, symbol: str = "💰") -> str:
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
    
    # ================= Currency System Methods =================
    
    async def get_user_balance(self, user_id: int, guild_id: int):
        """Get user's balance information."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.get_user_balance(user_id, guild_id)
    
    async def get_guild_settings(self, guild_id: int):
        """Get guild economy settings."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.get_guild_settings(guild_id)
    
    async def check_balance(self, user_id: int, guild_id: int, amount: int) -> bool:
        """Check if user has sufficient cash balance."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.check_balance(user_id, guild_id, amount)
    
    async def deduct_cash(self, user_id: int, guild_id: int, amount: int, reason: str = "") -> bool:
        """Deduct cash from user's balance. Returns True if successful."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.deduct_cash(user_id, guild_id, amount, reason)
    
    async def add_cash(self, user_id: int, guild_id: int, amount: int, reason: str = ""):
        """Add cash to user's balance."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.add_cash(user_id, guild_id, amount, reason)
    
    async def transfer_money(self, from_user_id: int, to_user_id: int, guild_id: int, 
                           amount: int, reason: str = "") -> bool:
        """Transfer money between users. Returns True if successful."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.transfer_money(from_user_id, to_user_id, guild_id, amount, reason)
    
    async def log_transaction(self, user_id: int, guild_id: int, amount: int,
                            transaction_type: str, target_user_id: Optional[int] = None,
                            success: bool = True, reason: str = ""):
        """Log a transaction."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.log_transaction(user_id, guild_id, amount, transaction_type, 
                                    target_user_id, success, reason)
    
    # ================= Game Integration Methods =================
    
    async def get_cockfight_streak(self, user_id: int, guild_id: int) -> int:
        """Get user's cockfight streak."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.get_cockfight_streak(user_id, guild_id)
    
    async def update_cockfight_streak(self, user_id: int, guild_id: int, won: bool):
        """Update user's cockfight streak."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.update_cockfight_streak(user_id, guild_id, won)
    
    async def add_lottery_entry(self, user_id: int, guild_id: int, amount: int):
        """Add a lottery entry."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.add_lottery_entry(user_id, guild_id, amount)
    
    async def get_lottery_entries(self, guild_id: int):
        """Get all lottery entries for a guild."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.get_lottery_entries(guild_id)
    
    async def record_lottery_winner(self, user_id: int, guild_id: int, amount: int):
        """Record a lottery winner."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.record_lottery_winner(user_id, guild_id, amount)
    
    async def save_poker_session(self, user_id: int, guild_id: int, bet_amount: int,
                                hand_cards: str, dealer_cards: str, result: str, winnings: int):
        """Save a poker game session."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.save_poker_session(user_id, guild_id, bet_amount, hand_cards, dealer_cards, result, winnings)
    
    async def add_crash_bet(self, user_id: int, guild_id: int, amount: int, multiplier: float = 0.0):
        """Add a crash game bet."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.add_crash_bet(user_id, guild_id, amount, multiplier)
    
    async def create_duel_match(self, challenger_id: int, challenged_id: int, guild_id: int, bet_amount: int) -> int:
        """Create a new duel match."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.create_duel_match(challenger_id, challenged_id, guild_id, bet_amount)
    
    async def update_duel_match(self, match_id: int, winner_id: int, status: str = "completed"):
        """Update a duel match result."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.update_duel_match(match_id, winner_id, status)
    
    # ================= Prediction System Methods =================
    
    async def create_prediction(self, guild_id: int, title: str, description: str, 
                              option1: str, option2: str) -> int:
        """Create a new prediction."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.create_prediction(guild_id, title, description, option1, option2)
    
    async def add_prediction_bet(self, prediction_id: int, user_id: int, guild_id: int, 
                                option: int, amount: int):
        """Add a prediction bet."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.add_prediction_bet(prediction_id, user_id, guild_id, option, amount)
    
    async def close_prediction(self, prediction_id: int, winning_option: int):
        """Close a prediction."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.close_prediction(prediction_id, winning_option)
    
    # ================= Utility Methods =================
    
    async def get_database_stats(self):
        """Get database statistics."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        return await self.db.get_database_stats()
    
    async def cleanup_old_data(self, days: int = 30):
        """Clean up old data older than specified days."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        await self.db.cleanup_old_data(days)
