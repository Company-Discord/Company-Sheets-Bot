# bot.py
import os
import json
import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ====== Google Sheets (optional; keep if you use these commands) =======
import gspread
from google.oauth2.service_account import Credentials

# ================= Env & config ==================
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    raise RuntimeError("Missing DISCORD_BOT_TOKEN environment variable.")

# Engauge token is required by predictions.py; if missing, we warn here so load failure is obvious
if not os.getenv("ENGAUGE_API_TOKEN"):
    print("⚠️  ENGAUGE_API_TOKEN is not set. The predictions extension will fail to load until you set it.")

SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")            # the /d/<THIS>/edit ID
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Sheet1")  # your tab name
SA_JSON_INLINE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_INLINE")
SA_JSON_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")    # optional alternative

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

@bot.event
async def setup_hook():
    # --- Load cogs ---
    try:
        await bot.load_extension("duel_royale")            # or: "cogs.duel_royale"
        print("Loaded duel_royale cog ✅")
    except Exception as e:
        print(f"Failed loading duel_royale: {e}")

    try:
        await bot.load_extension("fun")                    # or: "cogs.fun"
        print("Loaded fun cog ✅")
    except Exception as e:
        print(f"Failed loading fun: {e}")

    try:
        if(os.getenv("IS_DEV") != "True"):
            await bot.load_extension("horse_race_engauge")     # or: "cogs.horse_race_engauge"
            print("Loaded horse_race_engauge cog ✅")
    except Exception as e:
        print(f"Failed loading horse_race_engauge: {e}")

    # ---- Load the Twitch-style Engauge predictions extension ----
    try:
        await bot.load_extension("predictions")            # file: predictions.py
        print("Loaded predictions cog ✅")
    except Exception as e:
        print(f"Failed loading predictions: {e}")

@bot.event
async def on_ready():
    try:
        guild_id = os.getenv("DISCORD_GUILD_ID")
        
        # ---- Guild-specific sync (copy globals for fast dev), then global ----
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            guild_synced = await tree.sync(guild=guild)
            guild_names = [cmd.name for cmd in guild_synced]
            print(f"Guild sync → {len(guild_synced)} commands to guild {guild_id}: {', '.join(guild_names)}")

        global_synced = await tree.sync()
        command_names = [cmd.name for cmd in global_synced]
        print(f"Global sync → {len(global_synced)} commands: {', '.join(command_names)}")

        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    except Exception as e:
        print("Command sync failed:", e)


# ================= Admin sync helpers =================

@app_commands.default_permissions(administrator=True)
@tree.command(name="sync_commands", description="Force-resync slash commands globally (admin only).")
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.send_message("Syncing commands…", ephemeral=True)
    try:
        # Hot-reload known extensions so new/changed cog commands are registered
        reloaded = []
        for ext in ("duel_royale", "fun", "horse_race_engauge"):
            if ext in bot.extensions:
                try:
                    await bot.reload_extension(ext)
                    reloaded.append(ext)
                except Exception as e:
                    print(f"Failed to reload {ext}: {e}")
        if reloaded:
            print(f"Reloaded extensions: {', '.join(reloaded)}")

        # Guild sync first if configured, copying globals for fast propagation
        guild_id = os.getenv("DISCORD_GUILD_ID")
        guild_response = ""
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            guild_synced = await tree.sync(guild=guild)
            guild_names = [cmd.name for cmd in guild_synced]
            print(f"Manual guild sync → {len(guild_synced)} commands to guild {guild_id}: {', '.join(guild_names)}")
            guild_response = f"🏠 **Guild**: **{len(guild_synced)}** commands: `{', '.join(guild_names)}`\n"

        # Global sync
        global_synced = await tree.sync()
        global_names = [cmd.name for cmd in global_synced]
        print(f"Manual global sync → {len(global_synced)} commands: {', '.join(global_names)}")

        response = f"✅ {guild_response}🌐 **Global**: **{len(global_synced)}** commands: `{', '.join(global_names)}`"
        await interaction.followup.send(response, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: `{e}`", ephemeral=True)
        print("sync_commands error:", e)

# ================= Bot health =================
@tree.command(name="ping", description="Latency check.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! `{round(bot.latency*1000)}ms`", ephemeral=True)

@tree.command(name="test_currency", description="Test command that replies with the currency emoji.", guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID"))) if os.getenv("DISCORD_GUILD_ID") else None)
async def test_currency(interaction: discord.Interaction):
    currency_emoji = (os.getenv("CURRENCY_EMOJI") or "").strip() or "💰"
    print(f"Currency emoji: {currency_emoji}")
    embed = discord.Embed(title="Currency Test", color=discord.Color.blurple())
    embed.add_field(name="Currency Emoji", value=currency_emoji, inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= Sheets commands (optional) =================
@tree.command(name="status", description="Check bot → Google Sheets connectivity.", guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID"))) if os.getenv("DISCORD_GUILD_ID") else None)
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

@tree.command(name="append", description="Append a row: date, user, category.", guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID"))) if os.getenv("DISCORD_GUILD_ID") else None)
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

@tree.command(name="loguser", description="(Admins) Log a user to a category you pick.", guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID"))) if os.getenv("DISCORD_GUILD_ID") else None)
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

@tree.command(name="loguser_text", description="(Admins) Log a category for a name you type.", guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID"))) if os.getenv("DISCORD_GUILD_ID") else None)
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

@tree.command(name="setcell", description="Set a single cell (A1) to a value.", guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID"))) if os.getenv("DISCORD_GUILD_ID") else None)
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
    # Recommended Railway start: python -u bot.py
    bot.run(DISCORD_BOT_TOKEN)
