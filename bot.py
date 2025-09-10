import os
import json
import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# OPTIONAL: only needed if you still use Google Sheets commands elsewhere.
# Safe to keep; remove if you don't use them.
import gspread
from google.oauth2.service_account import Credentials

# ================= Env & config =================
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    raise RuntimeError("Missing DISCORD_BOT_TOKEN environment variable.")

# ---- If you still use Sheets; otherwise you can delete this whole block ----
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Sheet1")
SA_JSON_INLINE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_INLINE")
SA_JSON_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def make_gspread_client() -> gspread.Client:
    if SA_JSON_INLINE:
        info = json.loads(SA_JSON_INLINE)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    elif SA_JSON_PATH:
        creds = Credentials.from_service_account_file(SA_JSON_PATH, scopes=SCOPES)
    else:
        raise RuntimeError(
            "Missing Google service account credentials. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON_INLINE or GOOGLE_SERVICE_ACCOUNT_JSON_PATH."
        )
    return gspread.authorize(creds)

def open_sheet(worksheet_name: str | None = None):
    gc = make_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(worksheet_name or WORKSHEET_NAME)
    return gc, sh, ws

def safe_append_row(values: list[str | int | float], worksheet_name: str | None = None):
    _, _, ws = open_sheet(worksheet_name)
    ws.append_row(values, value_input_option="USER_ENTERED")

def safe_set_cell(a1: str, value: str | int | float, worksheet_name: str | None = None):
    _, _, ws = open_sheet(worksheet_name)
    ws.update_acell(a1, value)
# ---------------------------------------------------------------------------

# ================= Discord bot =================
intents = discord.Intents.default()
intents.members = True  # helpful for display names
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
write_lock = asyncio.Lock()

@bot.event
async def setup_hook():
    # Load your other cogs if you have them
    for ext in ("duel_royale", "fun"):
        try:
            await bot.load_extension(ext)
            print(f"Loaded {ext} cog ✅")
        except Exception as e:
            print(f"Failed loading {ext}: {e}")

    # Load the horse race cog
    try:
        await bot.load_extension("horse_race_engauge")
        print("Loaded horse_race_engauge cog ✅")
    except Exception as e:
        print(f"Failed loading horse_race_engauge: {e}")

@bot.event
async def on_ready():
    try:
        # Per-guild sync (immediate in those servers)
        for g in bot.guilds:
            synced = await tree.sync(guild=discord.Object(id=g.id))
            print(f"Synced {len(synced)} commands to guild {g.name} ({g.id})")

        # Global sync (slow to propagate; fine to keep)
        synced_global = await tree.sync()
        print(f"Synced {len(synced_global)} commands globally")

        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    except Exception as e:
        print("Command sync failed:", e)

# ================= Utility / admin =================
@app_commands.default_permissions(administrator=True)
@tree.command(name="sync_commands", description="Force-resync slash commands to THIS server (admin only).")
async def sync_commands(interaction: discord.Interaction):
    # Avoid 10062 by deferring once, quickly, and using followups
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        gobj = discord.Object(id=interaction.guild_id)
        synced = await tree.sync(guild=gobj)
        await interaction.followup.send(
            f"Synced **{len(synced)}** commands to **{interaction.guild.name}** ({interaction.guild_id}).",
            ephemeral=True
        )
    except Exception as e:
        try:
            await interaction.followup.send(f"Sync failed: `{e}`", ephemeral=True)
        except Exception:
            pass
        print("sync_commands error:", e)

# ---- (Optional) simple bot health command ----
@tree.command(name="ping", description="Latency check.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! `{round(bot.latency*1000)}ms`", ephemeral=True)

# (Keep/remove your Sheets commands as you like)
# ================= Run =================
if __name__ == "__main__":
    # Recommended start command on Railway: python -u bot.py
    bot.run(DISCORD_BOT_TOKEN)
