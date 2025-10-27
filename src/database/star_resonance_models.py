"""
Star Resonance database models integrated with existing unified database.
Uses the same PostgreSQL connection as the main bot.
"""

import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass

# These will be added to the existing Database class
@dataclass
class StarResonanceUser:
    """User registration and authentication for Star Resonance integration."""
    id: int
    discord_id: int
    discord_username: str
    auth_token: str
    game_uid: Optional[int] = None
    game_name: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    last_seen: Optional[datetime] = None

@dataclass
class Battle:
    """Battle metadata and summary information."""
    id: int
    battle_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    monster_id: Optional[int] = None
    monster_name: Optional[str] = None
    monster_max_hp: Optional[int] = None
    is_complete: bool = False
    total_damage: int = 0
    total_healing: int = 0
    participant_count: int = 0
    created_at: Optional[datetime] = None

@dataclass
class BattleParticipant:
    """Individual player performance in a battle."""
    id: int
    battle_id: str
    user_id: int
    game_uid: int
    game_name: str
    profession: Optional[str] = None
    
    # Damage stats
    total_damage: int = 0
    normal_damage: int = 0
    critical_damage: int = 0
    lucky_damage: int = 0
    crit_lucky_damage: int = 0
    
    # Healing stats
    total_healing: int = 0
    normal_healing: int = 0
    critical_healing: int = 0
    lucky_healing: int = 0
    crit_lucky_healing: int = 0
    
    # Performance metrics
    dps: float = 0.0
    hps: float = 0.0
    crit_rate: float = 0.0
    lucky_rate: float = 0.0
    
    # Additional stats
    taken_damage: int = 0
    death_count: int = 0
    fight_point: int = 0
    
    # Rankings
    damage_rank: Optional[int] = None
    healing_rank: Optional[int] = None
    dps_rank: Optional[int] = None
    hps_rank: Optional[int] = None
    
    created_at: Optional[datetime] = None

@dataclass
class BattleMonster:
    """Monster information for each battle."""
    id: int
    battle_id: str
    monster_id: int
    monster_name: str
    max_hp: Optional[int] = None
    current_hp: Optional[int] = None
    is_defeated: bool = False
    created_at: Optional[datetime] = None

@dataclass
class GuildConfig:
    """Guild-specific configuration for Star Resonance integration."""
    id: int
    guild_id: int
    report_channel_id: Optional[int] = None
    auto_report_enabled: bool = True
    min_battle_duration: int = 10000
    leaderboard_channel_id: Optional[int] = None
    weekly_reset_enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# Utility functions for the existing Database class
def generate_battle_id() -> str:
    """Generate unique battle ID."""
    return f"battle_{uuid.uuid4().hex[:16]}"

def generate_auth_token() -> str:
    """Generate unique auth token."""
    return f"sr_{uuid.uuid4().hex[:32]}"
