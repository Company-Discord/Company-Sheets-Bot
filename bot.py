# bot.py
import os
import json
import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials

# ================= Env & config =================
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")            # the /d/<THIS>/edit ID
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Sheet1")  # your tab name
SA_JSON_INLINE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_INLINE")
SA_JSON_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")    # optional alternative

if not DISCORD_BOT_TOKEN:
    raise RuntimeError("Missing DISCORD_BOT_TOKEN environment variable.")

# ================= Discord bot =================
intents = discord.Intents.default()
intents.members = True  # optional; helps with display names

bot = commands.Bot(command_prefix="!", intents=intents)  # prefix unused for slash
tree = bot.tree

write_lock = asyncio.Lock()

# ================= Google Sheets helpers =================
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
            "Missing Google service account credentials. Set GOOGLE_SERVICE_ACCOUNT_JSON_INLINE "
            "or GOOGLE_SERVICE_ACCOUNT_JSON_PATH."
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

# ================= Startup & sync =================
@bot.event
async def setup_hook():
    # Load cogs before the first sync
    try:
        await bot.load_extension("duel_royale")
        print("Loaded duel_royale cog ✅")
    except Exception as e:
        print(f"Failed loading duel_royale: {e}")

@bot.event
async def on_ready():
    try:
        print("Registered commands in code:", [c.name for c in tree.get_commands()])

        # Per-guild sync (instant in each server)
        total = 0
        for g in bot.guilds:
            gobj = discord.Object(id=g.id)
            synced = await tree.sync(guild=gobj)
            print(f"Synced {len(synced)} commands to guild {g.name} ({g.id})")
            total += len(synced)

        # Global sync (rolls out everywhere; may take longer to appear)
        synced_global = await tree.sync()
        print(f"Synced {len(synced_global)} commands globally")

        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    except Exception as e:
        print("Command sync failed:", e)

# ================= Utility / admin =================
@app_commands.default_permissions(administrator=True)
@tree.command(name="sync_commands", description="Force-resync slash commands to THIS server (admin only).")
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        gobj = discord.Object(id=interaction.guild_id)
        synced = await tree.sync(guild=gobj)
        await interaction.followup.send(
            f"Synced **{len(synced)}** commands to **{interaction.guild.name}** ({interaction.guild_id}).",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"Sync failed: `{e}`", ephemeral=True)

# ================= Bot health =================
@tree.command(name="status", description="Check bot → Google Sheets connectivity.")
async def status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        _, _, ws = open_sheet()
        await interaction.followup.send(
            f"✅ Connected to **{ws.spreadsheet.title}** / **{ws.title}**.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Sheets error: `{e}`", ephemeral=True)

@tree.command(name="ping", description="Latency check.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! `{round(bot.latency*1000)}ms`", ephemeral=True)

# ================= Sheets commands =================
@tree.command(name="append", description="Append a row: date, user, category.")
@app_commands.describe(username="Name to log", category="Category to log", worksheet="Optional worksheet/tab")
async def append(interaction: discord.Interaction, username: str, category: str, worksheet: str | None = None):
    await interaction.response.defer(ephemeral=True)
    date_str = datetime.now().strftime("%m/%d/%Y")
    values = [date_str, username, category]
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values, worksheet)
            await interaction.followup.send(f"📝 Logged **{username}** → **{category}**.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Append failed: `{e}`", ephemeral=True)

@tree.command(name="loguser", description="(Admins) Log a user to a category you pick.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(username="User to log", category="Category", worksheet="Optional worksheet/tab")
async def loguser(interaction: discord.Interaction, username: str, category: str, worksheet: str | None = None):
    await interaction.response.defer(ephemeral=True)
    date_str = datetime.now().strftime("%m/%d/%Y")
    values = [date_str, username, category]
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values, worksheet)
            await interaction.followup.send(f"✅ Logged **{username}** → **{category}**.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ `{e}`", ephemeral=True)

@tree.command(name="loguser_text", description="(Admins) Log a category for a name you type.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(username="Name to record (free text)", category="Category to log", worksheet="Optional worksheet/tab")
async def loguser_text(interaction: discord.Interaction, username: str, category: str, worksheet: str | None = None):
    await interaction.response.defer(ephemeral=True)
    date_str = datetime.now().strftime("%m/%d/%Y")
    values = [date_str, username, category]
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values, worksheet)
            await interaction.followup.send(f"🗂️ Logged **{username}** → **{category}**.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ `{e}`", ephemeral=True)

@tree.command(name="setcell", description="Set a single cell (A1) to a value.")
@app_commands.describe(a1="Cell (e.g., B2)", value="Value to write", worksheet="Optional worksheet/tab")
async def setcell(interaction: discord.Interaction, a1: str, value: str, worksheet: str | None = None):
    await interaction.response.defer(ephemeral=True)
    async with write_lock:
        try:
            await asyncio.to_thread(safe_set_cell, a1, value, worksheet)
            await interaction.followup.send(f"✅ Set **{a1}** → `{value}`.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ `{e}`", ephemeral=True)

# ================= Run =================
if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
