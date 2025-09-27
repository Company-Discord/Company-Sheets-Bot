import discord
from discord import app_commands
import os
import json
from typing import Dict, Any, Optional
# from src.api.unbelievaboat_api import Client  # COMMENTED OUT - Using unified database system instead
from dotenv import load_dotenv
from PIL import Image, ImageOps

load_dotenv()
MANAGER_ROLE_NAME = os.getenv("MANAGER_ROLE_NAME", "Techie")

# Role data parsing utilities
def get_role_data() -> Dict[str, Dict[str, int]]:
    """
    Parse role data from environment variable.
    
    Returns:
        Dictionary with role names as keys and dicts containing 'id' and 'salary' as values
        Example: {"Coordinator": {"id": 1, "salary": 11000}, ...}
    """
    role_data_str = os.getenv("ROLE_DATA", "{}")
    try:
        return json.loads(role_data_str)
    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse ROLE_DATA environment variable: {e}")
        return {}


def get_role_by_name(role_name: str) -> Optional[Dict[str, int]]:
    """
    Get role information by name.
    
    Args:
        role_name: Name of the role to look up
        
    Returns:
        Dictionary with 'id' and 'salary' keys, or None if role not found
    """
    role_data = get_role_data()
    return role_data.get(role_name)


def get_role_by_id(role_id: int) -> Optional[Dict[str, Any]]:
    """
    Get role information by ID.
    
    Args:
        role_id: ID of the role to look up
        
    Returns:
        Dictionary with role name as key and role info as value, or None if not found
    """
    role_data = get_role_data()
    for role_name, role_info in role_data.items():
        if role_info.get("id") == role_id:
            return {role_name: role_info}
    return None


def get_all_roles() -> Dict[str, Dict[str, int]]:
    """
    Get all role data.
    
    Returns:
        Complete dictionary of all roles with their IDs and salaries
    """
    return get_role_data()


def render_hand(card_paths, out_path, *, show_all=True,
                angle_step=4, overlap_px=45, scale=0.5, back_path=None):
    """
    card_paths: list of file paths (e.g. ['src/assets/cards/JS.png', 'src/assets/cards/7C.png'])
    show_all:   if False, only show first card + back (for dealer)
    back_path:  path to back.png (used when show_all=False)
    """
    cards = [Image.open(p).convert("RGBA") for p in card_paths]
    if scale != 1.0:
        cards = [c.resize((int(c.width*scale), int(c.height*scale)), Image.LANCZOS) for c in cards]

    if not show_all:
        assert back_path, "back_path required when show_all=False"
        cards = [cards[0], Image.open(back_path).convert("RGBA").resize(cards[0].size, Image.LANCZOS)]

    # Fan the cards a little: negative to positive angles
    n = len(cards)
    angles = [int((i-(n-1)/2)*angle_step) for i in range(n)]
    rotated = [c.rotate(angles[i], resample=Image.BICUBIC, expand=True) for i,c in enumerate(cards)]

    # Compute canvas size with overlap
    w = rotated[0].width + (n-1)*overlap_px + max(0, rotated[-1].width - cards[-1].width)
    h = max(img.height for img in rotated)
    canvas = Image.new("RGBA", (w, h), (0,0,0,0))

    # Paste with slight vertical alignment to keep bottoms level-ish
    x = 0
    for img in rotated:
        y = h - img.height  # align to bottom
        canvas.alpha_composite(img, (x, y))
        x += overlap_px

    canvas.save(out_path)
    return out_path
# COMMENTED OUT - Using unified database system instead of Unbelievaboat API
# # Global UnbelievaBoat client
# _unb_client: Client = None

# def initialize_unb_client(is_dev: bool = False) -> None:
#     """
#     Initialize the global UnbelievaBoat client.
    
#     Args:
#         is_dev: If True, use development token, otherwise use production token
#     """
#     global _unb_client
    
#     if is_dev:
#         api_token = os.getenv("UNBELIEVABOAT_TOKEN_DEV", "your-api-token-here")
#     else:
#         api_token = os.getenv("UNBELIEVABOAT_TOKEN", "your-api-token-here")
    
#     _unb_client = Client(api_token)
#     print(f"🔧 UnbelievaBoat client initialized ({'dev' if is_dev else 'prod'} mode)")


# async def close_unb_client() -> None:
#     """Close the global UnbelievaBoat client."""
#     global _unb_client
    
#     if _unb_client:
#         await _unb_client.close()
#         _unb_client = None
#         print("🔧 UnbelievaBoat client closed")


# def get_unb_client() -> Client:
#     """Get the global UnbelievaBoat client."""
#     global _unb_client
    
#     if not _unb_client:
#         raise Exception("UnbelievaBoat client not initialized. Call initialize_unb_client() first.")
    
#     return _unb_client


def is_admin_or_manager():
    async def predicate(inter: discord.Interaction) -> bool:
        # admins always allowed
        if inter.user.guild_permissions.administrator:
            return True
        # allow by role name
        if isinstance(inter.user, discord.Member):
            if any(r.name == MANAGER_ROLE_NAME for r in inter.user.roles):
                return True
        return False
    return app_commands.check(predicate)


# COMMENTED OUT - Using unified database system instead of Unbelievaboat API
# async def check_user_balances(guild_id: int, user_ids: list[int], bet_amount: int) -> tuple[bool, dict[int, int], list[int]]:
#     """
#     Check if all users have sufficient balance for the bet amount.
    
#     Args:
#         guild_id: Discord guild ID
#         user_ids: List of Discord user IDs to check
#         bet_amount: Required bet amount
        
#     Returns:
#         tuple: (all_sufficient: bool, balances: dict[user_id: cash_amount], insufficient_user_ids: list[int])
#     """
#     unb_client = get_unb_client()
    
#     balances = {}
#     insufficient_users = []
    
#     # Check each user's balance
#     for user_id in user_ids:
#         user = await unb_client.get_user_balance(guild_id, user_id)
#         balances[user_id] = user.cash
        
#         if user.cash < bet_amount:
#             insufficient_users.append(user_id)
    
#     return len(insufficient_users) == 0, balances, insufficient_users


# async def send_insufficient_funds_message(followup: discord.Webhook, insufficient_user_ids: list[int], 
#                                         bet_amount: int, balances: dict[int, int]) -> None:
#     """
#     Send a message about insufficient funds for specified users.
    
#     Args:
#         followup: Discord webhook for sending messages
#         insufficient_user_ids: List of user IDs with insufficient funds
#         bet_amount: Required bet amount
#         balances: Dictionary mapping user IDs to their current cash amounts
#     """
#     if not insufficient_user_ids or not followup:
#         return
        
#     insufficient_mentions = [f"<@{uid}>" for uid in insufficient_user_ids]
#     await followup.send(
#         f"❌ Insufficient funds! {', '.join(insufficient_mentions)} need at least ${bet_amount} cash. "
#         f"Current balances: {', '.join([f'<@{uid}>: ${balances[uid]}' for uid in insufficient_user_ids])}"
#     )


# # ================= Business-Focused UnbelievaBoat Operations =================

# async def credit_user(guild_id: int, user_id: int, amount: int, reason: str) -> None:
#     """
#     Credit money to a user's account.
    
#     Args:
#         guild_id: Discord guild ID
#         user_id: Discord user ID  
#         amount: Amount to credit (positive integer)
#         reason: Reason for the transaction
        
#     Raises:
#         UnbelievaBoatError: On API errors
#     """
#     unb_client = get_unb_client()
#     await unb_client.update_user_balance(guild_id, user_id, bank=abs(amount), reason=reason)


# async def debit_user(guild_id: int, user_id: int, amount: int, reason: str) -> None:
#     """
#     Debit money from a user's account.
    
#     Args:
#         guild_id: Discord guild ID
#         user_id: Discord user ID
#         amount: Amount to debit (positive integer) 
#         reason: Reason for the transaction
        
#     Raises:
#         UnbelievaBoatError: On API errors
#         InsufficientFunds: If user doesn't have enough money
#     """
#     unb_client = get_unb_client()
    
#     # Check balance first to provide clear error message
#     try:
#         user = await unb_client.get_user_balance(guild_id, user_id)
#         if user.cash < amount:
#             from unbelievaboat_api import UnbelievaBoatError
#             class InsufficientFunds(UnbelievaBoatError):
#                 pass
#             raise InsufficientFunds(f"User {user_id} has {user.cash} but needs {amount}")
#     except Exception as e:
#         # If balance check fails, still attempt the debit (API will handle insufficient funds)
#         pass
    
#     await unb_client.update_user_balance(guild_id, user_id, cash=-abs(amount), reason=reason)


# async def get_user_balance(guild_id: int, user_id: int) -> int:
#     """
#     Get a user's current cash balance.
    
#     Args:
#         guild_id: Discord guild ID
#         user_id: Discord user ID
        
#     Returns:
#         Current cash balance
#     """
#     unb_client = get_unb_client()
#     user = await unb_client.get_user_balance(guild_id, user_id)
#     return user.cash


# COMMENTED OUT - Using unified database system instead of Unbelievaboat API
# async def transfer_money(guild_id: int, from_user_id: int, to_user_id: int, 
#                         amount: int, reason: str) -> None:
#     """
#     Transfer money between two users atomically.
    
#     Args:
#         guild_id: Discord guild ID
#         from_user_id: Source user ID
#         to_user_id: Destination user ID
#         amount: Amount to transfer
#         reason: Reason for the transaction
#     """
#     # Debit first (this will check for sufficient funds)
#     await debit_user(guild_id, from_user_id, amount, f"{reason} (sent)")
#     try:
#         await credit_user(guild_id, to_user_id, amount, f"{reason} (received)")
#     except Exception as e:
#         # If credit fails, refund the debit
#         await credit_user(guild_id, from_user_id, amount, f"Refund: {reason} (failed transfer)")
#         raise
# # ================= Economy Data Classes =================
# from dataclasses import dataclass
# from datetime import datetime
# from typing import Optional, List, Tuple

TC_EMOJI = os.getenv("TC_EMOJI", "💰")


# @dataclass
# class UserBalance:
#     user_id: int
#     guild_id: int
#     cash: int = 0
#     bank: int = 0
#     total_earned: int = 0
#     total_spent: int = 0
#     crimes_committed: int = 0
#     crimes_succeeded: int = 0
#     robs_attempted: int = 0
#     robs_succeeded: int = 0
#     last_work: Optional[datetime] = None
#     last_slut: Optional[datetime] = None
#     last_crime: Optional[datetime] = None
#     last_rob: Optional[datetime] = None
#     last_collect: Optional[datetime] = None


# @dataclass
# class Transaction:
#     id: int
#     user_id: int
#     guild_id: int
#     amount: int
#     transaction_type: str
#     target_user_id: Optional[int] = None
#     success: bool = True
#     reason: str = ""
#     created_at: datetime = None


# @dataclass
# class GuildSettings:
#     guild_id: int
#     currency_symbol: str = CURRENCY_EMOJI
#     work_cooldown: int = 30
#     slut_cooldown: int = 90
#     crime_cooldown: int = 180
#     rob_cooldown: int = 900
#     collect_cooldown: int = 86400  # 24 hours
#     work_min_percent: float = 0.01  # 1% of total balance
#     work_max_percent: float = 0.05  # 5% of total balance
#     slut_min_percent: float = 0.02
#     slut_max_percent: float = 0.08
#     slut_fail_chance: float = 0.3
#     crime_min_percent: float = 0.03
#     crime_max_percent: float = 0.12
#     crime_success_rate: float = 0.4
#     rob_min_percent: float = 0.02
#     rob_max_percent: float = 0.08
#     rob_success_rate: float = 0.3
