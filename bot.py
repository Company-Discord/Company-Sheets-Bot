# bot_unified.py
import os
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from src.utils.utils import is_admin_or_manager
from src.api.engauge_adapter import EngaugeAdapter

# ================= Env & config ==================
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    raise RuntimeError("Missing DISCORD_BOT_TOKEN environment variable.")

# Engauge token is required by predictions.py; if missing, we warn here so load failure is obvious
if not os.getenv("ENGAUGE_API_TOKEN"):
    print("⚠️  ENGAUGE_API_TOKEN is not set. The predictions extension will fail to load until you set it.")

# ================= Discord bot =================
intents = discord.Intents.default()
intents.members = True  # optional; helps with display names
bot = commands.Bot(command_prefix="!", intents=intents)  # prefix unused for slash
tree = bot.tree

write_lock = asyncio.Lock()

# ================= Crate Drop System =================
async def random_crate_drop_task():
    """
    Background task that drops crates at random intervals between 65-180 minutes.
    Crates are read from the ENGAUGE_CRATES environment variable.
    """
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
    
    while True:
        try:
            # Wait for random interval between 65-180 minutes (3900-10800 seconds)
            wait_time = random.randint(3900, 10800)
            print(f"⏰ Next crate drop in {wait_time // 60} minutes ({wait_time} seconds)")
            await asyncio.sleep(wait_time)
            
            # Drop a crate
            print("🎁 Dropping random crate...")
            result = await adapter.drop_crate()
            print(f"✅ Crate dropped successfully: {result}")
            
        except Exception as e:
            print(f"❌ Error in crate drop task: {e}")
            # Wait 5 minutes before retrying on error
            await asyncio.sleep(300)

@bot.event
async def setup_hook():
    # --- Load cogs with unified database ---
    try:
        await bot.load_extension("src.games.duel_royale")
        print("Loaded duel_royale cog ✅")
    except Exception as e:
        print(f"Failed loading duel_royale: {e}")

    try:
        await bot.load_extension("src.bot.extensions.fun")
        print("Loaded fun cog ✅")
    except Exception as e:
        print(f"Failed loading fun: {e}")

    try:
        await bot.load_extension("src.games.horse_race_engauge")
        print("Loaded horse_race_engauge cog ✅")
    except Exception as e:
        print(f"Failed loading horse_race_engauge: {e}")

    # ---- Load the Twitch-style Engauge predictions extension ----
    try:
        await bot.load_extension("src.bot.extensions.predictions")
        print("Loaded predictions cog ✅")
    except Exception as e:
        print(f"Failed loading predictions: {e}")

    # ---- Load the Crash game extension ----
    try:
        await bot.load_extension("src.games.crash")
        print("Loaded crash cog ✅")
    except Exception as e:
        print(f"Failed loading crash: {e}")

    # ---- Load Lottery extension ----
    try:
        await bot.load_extension("src.games.lottery_daily")
        print("Loaded lottery_daily cog ✅")
    except Exception as e:
        print(f"Failed loading lottery_daily: {e}")

    # ---- Load Poker-Lite extension ----
    try:
        await bot.load_extension("src.games.poker_lite")
        print("Loaded poker_lite cog ✅")
    except Exception as e:
        print(f"Failed loading poker_lite: {e}")

    # ---- Load Currency System extension ----
    try:
        await bot.load_extension("src.bot.extensions.currency_system")
        print("Loaded currency_system cog ✅")
    except Exception as e:
        print(f"Failed loading currency_system: {e}")
    
    # ---- Load Cockfight extension ----
    try:
        await bot.load_extension("src.games.cockfight")
        print("Loaded cockfight cog ✅")
    except Exception as e:
        print(f"Failed loading cockfight: {e}")
    
    # ---- Load Blackjack extension ----
    try:
        await bot.load_extension("src.games.blackjack")
        print("Loaded blackjack cog ♠️")
    except Exception as e:
        print(f"Failed loading blackjack: {e}")

    # ---- Start Crate Drop Task ----
    try:
        asyncio.create_task(random_crate_drop_task())
        print("Started random crate drop task ✅")
    except Exception as e:
        print(f"Failed to start crate drop task: {e}")

      # ---- Load HighLow extension ----
    try:
        await bot.load_extension("src.games.highlow")
        print("Loaded highlow cog 🔼🔽")
    except Exception as e:
        print(f"Failed loading highlow: {e}")

    try:
        await bot.load_extension("src.games.lottery")
        print("Loaded weekly lottery cog ✅")
    except Exception as e:
        print(f"Failed loading weekly lottery: {e}")
    try:
        await bot.load_extension("src.games.blackjack_v2")
        print("Loaded blackjack_v2 cog ✅")
    except Exception as e:
        print(f"Failed loading blackjack_v2: {e}")

@bot.event
async def on_ready():
    try:
        # ---- Populate emoji cache ---
        from src.bot.base_cog import BaseCog
        temp_cog = BaseCog(bot)
        await temp_cog.populate_emoji_cache()
        
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

@bot.event
async def on_guild_emojis_update(guild, before, after):
    """Automatically refresh emoji cache when emojis are added/removed"""
    try:
        print(f"🔄 Emoji cache refreshed due to changes in guild {guild.name}")
    except Exception as e:
        print(f"❌ Failed to refresh emoji cache: {e}")

# ================= Admin sync helpers =================
@is_admin_or_manager()
@tree.command(name="sync_commands", description="Force-resync slash commands globally (admin only).")
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.send_message("Syncing commands…", ephemeral=True)
    try:
        # Reload all currently loaded extensions (safe & future-proof)
        reloaded = []
        for ext_path in list(bot.extensions.keys()):
            try:
                await bot.reload_extension(ext_path)
                reloaded.append(ext_path)
            except Exception as e:
                print(f"Failed to reload {ext_path}: {e}")

        if reloaded:
            print(f"Reloaded extensions:\n- " + "\n- ".join(reloaded))

        # Guild sync first (fast propagation for testing)
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

# ================= Run =================
if __name__ == "__main__":
    # Recommended Railway start: python -u bot_unified.py
    bot.run(DISCORD_BOT_TOKEN)
