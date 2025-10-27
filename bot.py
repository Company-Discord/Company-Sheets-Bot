# bot.py
import os
import asyncio
import random
import json

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from src.utils.utils import is_admin_or_manager
from src.api.engauge_adapter import EngaugeAdapter

# ================= Env & config ==================
load_dotenv()

TC_EMOJI = os.getenv("TC_EMOJI", "💰")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    raise RuntimeError("Missing DISCORD_BOT_TOKEN environment variable.")

if not os.getenv("ENGAUGE_API_TOKEN"):
    print("⚠️  ENGAUGE_API_TOKEN is not set. The predictions extension may fail to load until you set it.")

DEV_GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # your guild for fast propagation

# ================= Discord bot ==================
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ================= Crate Drop System =================
async def random_crate_drop_task():
    """Drop crates at random intervals between 65–180 minutes."""
    server_id = int(os.getenv("DISCORD_GUILD_ID", 0))
    if not server_id:
        print("⚠️  DISCORD_GUILD_ID not set. Crate drops disabled.")
        return

    try:
        adapter = EngaugeAdapter(server_id)
        print("🎁 Crate drop system initialized")
    except Exception as e:
        print(f"❌ Failed to initialize crate drop system: {e}")
        return

    drop_count = 0
    while True:
        try:
            drop_count += 1
            wait_time = random.randint(10800, 18000)
            # wait_time = random.randint(90, 180)
            print(f"⏰ Next crate drop (#{drop_count}) in {wait_time // 60} minutes ({wait_time} seconds)")
            await asyncio.sleep(wait_time)
            print(f"🎁 Dropping random crate (#{drop_count})...")
            result = await adapter.drop_crate()
            print(f"✅ Crate #{drop_count} dropped successfully: {result}")
        except Exception as e:
            print(f"❌ Error in crate drop task (attempt #{drop_count}): {e}")
            print("⏳ Waiting 5 minutes before retrying...")
            await asyncio.sleep(300)
            print("🔄 Retrying crate drop task...")

# ================= Extension loading =================
@bot.event
async def setup_hook():
    # ---- Command groups removed - all commands are now flat ----
    
    # ---- Load Duel Royale ----
    try:
        await bot.load_extension("src.games.duel_royale")
        print("Loaded duel_royale cog ✅")
    except Exception as e:
        print(f"Failed loading duel_royale: {e}")

    # ---- Load Fun ----
    try:
        await bot.load_extension("src.bot.extensions.fun")
        print("Loaded fun cog ✅")
    except Exception as e:
        print(f"Failed loading fun: {e}")

    # ---- Load Horse Race (Engauge) ----
    try:
        await bot.load_extension("src.games.horse_race_engauge")
        print("Loaded horse_race_engauge cog ✅")
    except Exception as e:
        print(f"Failed loading horse_race_engauge: {e}")

    # ---- Load Predictions ----
    try:
        await bot.load_extension("src.bot.extensions.predictions")
        print("Loaded predictions cog ✅")
    except Exception as e:
        print(f"Failed loading predictions: {e}")

    # ---- Load Crash ----
    try:
        await bot.load_extension("src.games.crash")
        print("Loaded crash cog ✅")
    except Exception as e:
        print(f"Failed loading crash: {e}")

    # ---- Load Daily Lottery ----
    try:
        await bot.load_extension("src.games.lottery_daily")
        print("Loaded lottery_daily cog ✅")
    except Exception as e:
        print(f"Failed loading lottery_daily: {e}")

    # ---- Load Poker-Lite ----
    try:
        await bot.load_extension("src.games.poker_lite")
        print("Loaded poker_lite cog ✅")
    except Exception as e:
        print(f"Failed loading poker_lite: {e}")

    # ---- Load Currency System (FLAT COMMANDS) ----
    try:
        await bot.load_extension("src.bot.extensions.currency_system")
        print("Loaded currency_system cog ✅")
    except Exception as e:
        print(f"Failed loading currency_system: {e}")

    # ---- Load Cockfight ----
    try:
        await bot.load_extension("src.games.cockfight")
        print("Loaded cockfight cog ✅")
    except Exception as e:
        print(f"Failed loading cockfight: {e}")

    # ---- Load Blackjack (v1) ----
    try:
        await bot.load_extension("src.games.blackjack")
        print("Loaded blackjack cog ♠️")
    except Exception as e:
        print(f"Failed loading blackjack: {e}")

    # ---- Load HighLow ----
    try:
        await bot.load_extension("src.games.highlow")
        print("Loaded highlow cog 🔼🔽")
    except Exception as e:
        print(f"Failed loading highlow: {e}")

    # ---- Load Weekly Lottery ----
    try:
        await bot.load_extension("src.games.lottery")
        print("Loaded weekly lottery cog ✅")
    except Exception as e:
        print(f"Failed loading weekly lottery: {e}")

    # ---- Load Blackjack v2 ----
    try:
        await bot.load_extension("src.games.blackjack_v2")
        print("Loaded blackjack_v2 cog ✅")
    except Exception as e:
        print(f"Failed loading blackjack_v2: {e}")

    # ---- Load Star Resonance ----
    try:
        await bot.load_extension("src.bot.extensions.star_resonance")
        print("Loaded star_resonance cog ⚔️")
    except Exception as e:
        print(f"Failed loading star_resonance: {e}")

    # ---- Game-specific command groups removed - all commands are now flat ----

    # ---- Start Crate Drop Task ----
    try:
        asyncio.create_task(random_crate_drop_task())
        print("Started random crate drop task ✅")
    except Exception as e:
        print(f"Failed to start crate drop task: {e}")

# ================= Ready & initial sync =================
@bot.event
async def on_ready():
    try:
        # Optional: warm emoji cache
        try:
            from src.bot.base_cog import BaseCog
            temp_cog = BaseCog(bot)
            await temp_cog.populate_emoji_cache()
        except Exception as e:
            print(f"Emoji cache warmup skipped: {e}")

        # Sync once per process — DO NOT clear/copy; just sync
        if not getattr(bot, "_did_initial_sync", False):
            # Always sync globally first
            global_synced = await bot.tree.sync()
            print(f"Global sync → {len(global_synced)} commands: {[c.name for c in global_synced]}")
            
            # If DEV_GUILD_ID is set, also sync to the specific guild
            if DEV_GUILD_ID:
                g = discord.Object(id=int(DEV_GUILD_ID))
                guild_synced = await bot.tree.sync(guild=g)
                print(f"Guild sync → {len(guild_synced)} commands: {[c.name for c in guild_synced]}")
            
            bot._did_initial_sync = True

        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    except Exception as e:
        print("Command sync failed:", e)

@bot.event
async def on_guild_emojis_update(guild, before, after):
    try:
        print(f"🔄 Emoji cache refreshed due to changes in guild {guild.name}")
    except Exception as e:
        print(f"❌ Failed to refresh emoji cache: {e}")

# ================= Admin: manual sync (no nukes, no clear) =================
@is_admin_or_manager()
@tree.command(
    name="sync_commands",
    description="Resync slash commands globally and to guild (if DEV_GUILD_ID is set).",
    guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID", "0"))),
)
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        # Always sync globally first
        global_synced = await bot.tree.sync()
        global_names = [c.name for c in global_synced]
        print(f"Global sync → {len(global_synced)} commands: {global_names}")
        
        response_parts = [f"✅ Global sync: **{len(global_synced)}** commands"]
        
        # If DEV_GUILD_ID is set, also sync to the specific guild
        if DEV_GUILD_ID:
            g = discord.Object(id=int(DEV_GUILD_ID))
            guild_synced = await bot.tree.sync(guild=g)
            guild_names = [c.name for c in guild_synced]
            print(f"Guild sync → {len(guild_synced)} commands: {guild_names}")
            response_parts.append(f"✅ Guild sync: **{len(guild_synced)}** commands")
        
        await interaction.followup.send(
            "\n".join(response_parts),
            ephemeral=True,
        )
    except Exception as e:
        print("sync_commands error:", e)
        await interaction.followup.send(f"❌ Sync failed: `{e}`", ephemeral=True)

# ================= Health =================
@tree.command(name="ping", description="Latency check.")
@is_admin_or_manager()
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! `{round(bot.latency * 1000)}ms`", ephemeral=True)

# ================= Global app command error logger =================
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        print(f"AppCommandError: {type(error).__name__}: {error}")
        data = getattr(interaction, "data", None)
        try:
            print("Interaction data:")
            print(json.dumps(data, indent=2))
        except Exception:
            print("Interaction data (raw):", data)
    except Exception as log_e:
        print("Failed to log app command error:", log_e)

# ================= Run =================
if __name__ == "__main__":
    # Railway: python -u bot.py
    bot.run(DISCORD_BOT_TOKEN)
