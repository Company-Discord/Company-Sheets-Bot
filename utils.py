import discord
from discord import app_commands
import os
MANAGER_ROLE_NAME = os.getenv("MANAGER_ROLE_NAME", "Techie")

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