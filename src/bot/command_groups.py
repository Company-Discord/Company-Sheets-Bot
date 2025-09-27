import discord
from discord import app_commands

# Single shared /tc command group for the entire bot.
# Every cog should import `tc` from here and attach commands to it.

tc = app_commands.Group(name="tc", description="Company Sheets Bot commands")

# Subgroups to stay under Discord's 25 child limit per command
games = app_commands.Group(name="games", description="All game commands", parent=tc)
fun = app_commands.Group(name="fun", description="Fun image and utility commands", parent=tc)
pred = app_commands.Group(name="pred", description="Predictions commands", parent=tc)

# Currency admin subgroup under /tc defined centrally to avoid duplicate registration
admin = app_commands.Group(name="admin", description="Admin commands for economy management", parent=tc)


