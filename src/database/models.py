"""
Data models for the currency system.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Currency emoji constant
TC_EMOJI = os.getenv('TC_EMOJI', '💰')


@dataclass
class UserBalance:
    """User balance information."""
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
    last_collect: Optional[datetime] = None


@dataclass
class Transaction:
    """Transaction record."""
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
    """Guild economy settings."""
    guild_id: int
    currency_symbol: str = TC_EMOJI
    work_cooldown: int = 30
    slut_cooldown: int = 90
    crime_cooldown: int = 180
    rob_cooldown: int = 900
    collect_cooldown: int = 86400  # 24 hours (daily salary)
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
