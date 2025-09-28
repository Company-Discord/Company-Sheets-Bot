# bot_unified.py
import os
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from src.utils.utils import is_admin_or_manager
import json
from src.api.engauge_adapter import EngaugeAdapter

# ================= Env & config ==================
load_dotenv()

# Currency emoji constant
TC_EMOJI = os.getenv('TC_EMOJI', '💰')

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

    # Register /tc after cogs attach commands (single startup registration)
    try:
        from src.bot.command_groups import tc
        guild_id_env = os.getenv("DISCORD_GUILD_ID")
        guild_obj = discord.Object(id=int(guild_id_env)) if guild_id_env else None
        if guild_obj:
            bot.tree.remove_command("tc", type=None, guild=guild_obj)
            bot.tree.add_command(tc, guild=guild_obj)
            print(f"Registered fresh /tc to guild {guild_id_env}")
        else:
            bot.tree.remove_command("tc")
            bot.tree.add_command(tc)
            print("Registered fresh /tc globally")
    except Exception as e:
        print(f"Startup /tc registration skipped: {e}")

@bot.event
async def on_ready():
    try:
        # ---- Populate emoji cache ---
        from src.bot.base_cog import BaseCog
        temp_cog = BaseCog(bot)
        await temp_cog.populate_emoji_cache()
        
        guild_id = os.getenv("DISCORD_GUILD_ID")

        #  ADDED: run NUKE once per process if DISCORD_NUKE=1
        if os.getenv("DISCORD_NUKE", "0") == "1" and not getattr(bot, "_did_nuke", False):
            print("DISCORD_NUKE=1 → nuking all commands")
            await _nuke_all_commands_at_startup()
            bot._did_nuke = True        

        # ---- Sync commands once per process (prevents extra API calls on reconnect) ----
        if not getattr(bot, "_did_initial_sync", False):
            # Guild-specific sync first (fast propagation for testing)
            if guild_id:
                guild = discord.Object(id=int(guild_id))

                # Clear old guild commands
                bot.tree.clear_commands(guild=guild)

                # Re-add /tc
                from src.bot.command_groups import tc
                bot.tree.add_command(tc, guild=guild)

                # Re-add admin/debug commands
                for cmd in (sync_commands, debug_tc_work, debug_tc_tree):
                    try:
                        bot.tree.add_command(cmd, guild=guild)
                    except Exception as e:
                        print(f"Failed to re-add {getattr(cmd, 'name', cmd)}: {e}")

                # Single sync after re-adding
                guild_synced = await tree.sync(guild=guild)
                print(f"Guild sync → {len(guild_synced)} commands: {[c.name for c in guild_synced]}")

            # Global sync is opt-in to avoid rate limits on startup
        if os.getenv("SYNC_GLOBAL_ON_STARTUP", "0") == "1":
            bot.tree.clear_commands(guild=None)
            global_synced = await tree.sync()
            print(f"Global sync → {len(global_synced)} commands")

            bot._did_initial_sync = True

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
@tree.command(
    name="sync_commands",
    description="Force-resync slash commands globally (admin only).",
    guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID", "0")))
)
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.send_message("Syncing commands…", ephemeral=True)
    try:
        import asyncio

        # --- hot-reload cogs so local tree is fresh (optional but helpful)
        for ext_path in list(bot.extensions.keys()):
            try:
                await bot.reload_extension(ext_path)
            except Exception as e:
                print(f"Reload warning {ext_path}: {e}")

        # figure out guild
        gid_env = os.getenv("DISCORD_GUILD_ID")
        if not gid_env:
            # fall back to global sync if you don’t use a dev guild
            global_synced = await tree.sync()
            print(f"Global sync → {len(global_synced)} commands: {', '.join(c.name for c in global_synced)}")
            await interaction.followup.send(
                f"✅ Global sync: **{len(global_synced)}** commands: "
                f"`{', '.join(c.name for c in global_synced)}`",
                ephemeral=True,
            )
            return

        gid = int(gid_env)
        gobj = discord.Object(id=gid)

        # --------- HARD NUKE (guild) ----------
        # 1) Clear local tree for this guild
        tree.clear_commands(guild=gobj)

        # 2) Delete ALL remote guild commands
        app_id = bot.application_id or (await bot.application_info()).id
        try:
            remote = await bot.http.get_guild_commands(app_id, gid)
            for c in remote:
                await bot.http.delete_guild_command(app_id, gid, c["id"])
            print(f"NUKE: deleted {len(remote)} remote guild commands")
        except Exception as e:
            print(f"NUKE: failed to list/delete remote: {e}")

        # tiny pause so Discord processes deletions
        await asyncio.sleep(1)

        # 3) Re-add only your /tc group to the local tree
        from src.bot.command_groups import tc
        bot.tree.add_command(tc, guild=gobj)
        print("Re-added fresh /tc to local tree")

        # 4) Guild sync (fast propagation)
        guild_synced = await tree.sync(guild=gobj)
        names = [c.name for c in guild_synced]
        print(f"Guild sync → {len(guild_synced)} commands: {', '.join(names)}")
        await interaction.followup.send(
            f"✅ Guild sync: **{len(guild_synced)}** commands: `{', '.join(names)}`",
            ephemeral=True,
        )

    except Exception as e:
        print("sync_commands error:", e)
        await interaction.followup.send(f"❌ Sync failed: `{e}`", ephemeral=True)

# ===== One-shot NUKE (runs at startup) =====
async def _nuke_all_commands_at_startup():
    try:
        app_id = bot.application_id or (await bot.application_info()).id
        gid_env = os.getenv("DISCORD_GUILD_ID")
        gid = int(gid_env) if gid_env else None

        deleted_guild = deleted_global = 0

        # delete guild commands
        if gid:
            guild_cmds = await bot.http.get_guild_commands(app_id, gid)
            for c in guild_cmds:
                await bot.http.delete_guild_command(app_id, gid, c["id"])
                deleted_guild += 1

        # delete global commands
        global_cmds = await bot.http.get_global_commands(app_id)
        for c in global_cmds:
            await bot.http.delete_global_command(app_id, c["id"])
            deleted_global += 1

        print(f"NUKE at startup: deleted guild={deleted_guild}, global={deleted_global}")
    except Exception as e:
        print(f"NUKE error: {e}")




# Dangerous: clear all commands and fully resync
"""
@is_admin_or_manager()
@tree.command(name="sync_nuke", description="Danger: clear all slash commands and fully resync (admin only).", guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID", "0"))))
async def sync_nuke(interaction: discord.Interaction):
    await interaction.response.send_message("Clearing and resyncing commands…", ephemeral=True)
    try:
        # Clear guild commands first (if dev guild specified)
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            tree.clear_commands(guild=guild)
            await tree.sync(guild=guild)

        # Clear global commands
        tree.clear_commands(guild=None)
        
        # Wait for Discord to process the clear
        await asyncio.sleep(3)

        # Proactively delete ALL remote commands (global & guild) via REST to avoid stale signatures
        try:
            app_id = bot.application_id
            if not app_id:
                info = await bot.application_info()
                app_id = info.id

            # Delete all guild commands
            if guild_id:
                gid = int(guild_id)
                guild_cmds = await bot.http.get_guild_commands(app_id, gid)
                for cmd in guild_cmds:
                    try:
                        await bot.http.delete_guild_command(app_id, gid, cmd["id"])  # type: ignore[index]
                    except Exception as de:
                        print(f"Failed to delete guild cmd {cmd.get('name')}: {de}")
                print(f"Deleted {len(guild_cmds)} guild commands via REST")

            # Delete all global commands
            global_cmds = await bot.http.get_global_commands(app_id)
            for cmd in global_cmds:
                try:
                    await bot.http.delete_global_command(app_id, cmd["id"])  # type: ignore[index]
                except Exception as de:
                    print(f"Failed to delete global cmd {cmd.get('name')}: {de}")
            print(f"Deleted {len(global_cmds)} global commands via REST")
        except Exception as e:
            print(f"Warning: failed REST deletion of /tc: {e}")

        # Unload all extensions first to clear local command tree
        for ext_path in list(bot.extensions.keys()):
            try:
                await bot.unload_extension(ext_path)
                print(f"Unloaded {ext_path}")
            except Exception as e:
                print(f"Failed to unload {ext_path}: {e}")

        # Clear the command tree completely after unloading
        tree.clear_commands(guild=None)
        if guild_id:
            tree.clear_commands(guild=discord.Object(id=int(guild_id)))

        # Wait a moment for unload to complete
        await asyncio.sleep(2)

        # Reload command_groups to ensure fresh Group objects, then add /tc back
        try:
            import importlib
            import src.bot.command_groups as cg
            importlib.reload(cg)
            if guild_id:
                guild_obj2 = discord.Object(id=int(guild_id))
                tree.add_command(cg.tc, guild=guild_obj2)
                print(f"Re-added fresh /tc group to guild {guild_id}")
            else:
                tree.add_command(cg.tc)
                print("Re-added fresh /tc group globally")
        except Exception as e:
            print(f"Warning: failed to re-add /tc group: {e}")

        # Reload extensions to re-register all commands cleanly
        reloaded = []
        exts_to_load = [
            "src.bot.extensions.currency_system",
            "src.bot.extensions.fun",
            "src.bot.extensions.predictions",
            "src.games.blackjack",
            "src.games.blackjack_v2",
            "src.games.cockfight",
            "src.games.crash",
            "src.games.duel_royale",
            "src.games.highlow",
            "src.games.horse_race_engauge",
            "src.games.lottery",
            "src.games.lottery_daily",
            "src.games.poker_lite",
        ]
        only_ext ='src.bot.extensions.currency_system' # os.getenv("NUKE_LOAD_ONLY")
        if only_ext:
            exts_to_load = [only_ext]
            print(f"NUKE_LOAD_ONLY active → loading only: {only_ext}")
        for ext_path in exts_to_load:
            try:
                await bot.load_extension(ext_path)
                reloaded.append(ext_path)
                print(f"Reloaded {ext_path}")
            except Exception as e:
                print(f"Failed to reload {ext_path}: {e}")

        # Wait before syncing
        await asyncio.sleep(2)

        # Re-register admin/debug helper commands (guild-scoped) after nuking
        try:
            guild_for_admin = discord.Object(id=int(guild_id)) if guild_id else None
            # Re-add existing Command objects defined via @tree.command
            for cmd in [sync_commands, sync_nuke, debug_tc_work, debug_tc_tree]:
                if guild_for_admin:
                    tree.add_command(cmd, guild=guild_for_admin)
                else:
                    tree.add_command(cmd)
            print("Re-registered admin/debug commands")
        except Exception as e:
            print(f"Warning: failed to re-register admin/debug commands: {e}")

        # Guild sync then global sync
        guild_response = ""
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            guild_synced = await tree.sync(guild=guild)
            guild_names = [cmd.name for cmd in guild_synced]
            guild_response = f"🏠 Guild: {len(guild_synced)} commands: `{', '.join(guild_names)}`\n"
            
            # Wait between guild and global sync
            await asyncio.sleep(2)

        global_response = ""
        if os.getenv("NUKE_GLOBAL_SYNC", "0") == "1" or os.getenv("SYNC_GLOBAL_ON_STARTUP", "0") == "1":
            global_synced = await tree.sync()
            global_names = [cmd.name for cmd in global_synced]
            global_response = f"🌐 Global: {len(global_synced)} commands: `{', '.join(global_names)}`"
        else:
            global_response = "🌐 Global sync skipped"

        await interaction.followup.send(
            f"✅ Commands nuked and resynced. {guild_response}{global_response}",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Nuke failed: `{e}`", ephemeral=True)
        print("sync_nuke error:", e)
"""

# ================= Bot health =================
@tree.command(name="ping", description="Latency check.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! `{round(bot.latency*1000)}ms`", ephemeral=True)

# ================= Debug: Inspect remote schema =================
@is_admin_or_manager()
@tree.command(
    name="debug_tc_work",
    description="Show remote schema for /tc work (guild + global)",
    guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID", "0")))
)
async def debug_tc_work(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async def find_work(cmd_obj: dict) -> dict | None:
        if not cmd_obj:
            return None
        # Recursively search options for a subcommand named 'work'
        stack = [cmd_obj]
        while stack:
            node = stack.pop()
            options = node.get("options") or []
            for opt in options:
                # type 1 = SUB_COMMAND, type 2 = SUB_COMMAND_GROUP per Discord API
                if opt.get("type") in (1, 2):
                    if opt.get("name") == "work" and opt.get("type") == 1:
                        return opt
                    stack.append(opt)
        return None

    try:
        # Determine application ID robustly
        app_id = bot.application_id
        if not app_id:
            info = await bot.application_info()
            app_id = info.id

        guild_id_env = os.getenv("DISCORD_GUILD_ID")
        guild_summary = {}
        global_summary = {}
        local_summary = {}

        # Guild schema
        if guild_id_env:
            gid = int(guild_id_env)
            guild_cmds = await bot.http.get_guild_commands(app_id, gid)
            tc_guild = next((c for c in guild_cmds if c.get("name") == "tc"), None)
            work_guild = await find_work(tc_guild)
            guild_summary = {
                "tc_found": bool(tc_guild),
                "work_found": bool(work_guild),
                "work_options": work_guild.get("options") if work_guild else None,
                "work_dm_permission": work_guild.get("dm_permission") if work_guild else None,
                "work_default_member_permissions": work_guild.get("default_member_permissions") if work_guild else None,
                "work_full": work_guild,
            }

        # Global schema
        global_cmds = await bot.http.get_global_commands(app_id)
        tc_global = next((c for c in global_cmds if c.get("name") == "tc"), None)
        work_global = await find_work(tc_global)
        global_summary = {
            "tc_found": bool(tc_global),
            "work_found": bool(work_global),
            "work_options": work_global.get("options") if work_global else None,
            "work_dm_permission": work_global.get("dm_permission") if work_global else None,
            "work_default_member_permissions": work_global.get("default_member_permissions") if work_global else None,
            "work_full": work_global,
        }

        # Local schema (what our tree would send)
        try:
            tc_local = None
            work_local_dict = None
            work_local_type = None
            tc_local_children = []
            guild_obj = discord.Object(id=int(guild_id_env)) if guild_id_env else None
            local_cmds = bot.tree.get_commands(guild=guild_obj) if guild_obj else bot.tree.get_commands()
            for c in local_cmds:
                if getattr(c, "name", None) == "tc":
                    tc_local = c
                    break
            if tc_local is not None:
                # Traverse tc_local.commands to find work
                def find_work_local(group) -> object | None:
                    for child in getattr(group, "commands", []):
                        if getattr(child, "name", None) == "work" and child.__class__.__name__ == "Command":
                            return child
                        if child.__class__.__name__ == "Group":
                            res = find_work_local(child)
                            if res:
                                return res
                    return None
                # Also capture child types
                for child in getattr(tc_local, "commands", []):
                    tc_local_children.append({
                        "name": getattr(child, "name", None),
                        "class": child.__class__.__name__,
                    })
                wl = find_work_local(tc_local)
                if wl is not None:
                    work_local_dict = wl.to_dict(bot.tree)  # type: ignore[attr-defined]
                    work_local_type = wl.__class__.__name__
            local_summary = {"work_local": work_local_dict, "work_local_type": work_local_type, "tc_local_children": tc_local_children}
        except Exception as le:
            local_summary = {"error": f"{le}"}

        payload = {
            "guild": guild_summary,
            "global": global_summary,
            "local": local_summary,
        }
        await interaction.followup.send(
            content=f"```json\n{json.dumps(payload, indent=2)}\n```",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Debug failed: `{e}`", ephemeral=True)

# List the full remote /tc tree (guild + global)
@is_admin_or_manager()
@tree.command(
    name="debug_tc_tree",
    description="List all remote /tc subcommands (guild + global)",
    guild=discord.Object(id=int(os.getenv("DISCORD_GUILD_ID", "0")))
)
async def debug_tc_tree(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    def flatten_paths(root: dict | None) -> list[str]:
        if not root:
            return []
        results: list[str] = []

        def walk(node: dict, path: list[str]):
            options = node.get("options") or []
            for opt in options:
                opt_type = opt.get("type")
                name = opt.get("name")
                if opt_type == 1:  # SUB_COMMAND
                    results.append("/" + " ".join(path + [name]))
                elif opt_type == 2:  # SUB_COMMAND_GROUP
                    walk(opt, path + [name])

        walk(root, [root.get("name", "tc")])
        return results

    try:
        app_id = bot.application_id
        if not app_id:
            info = await bot.application_info()
            app_id = info.id

        guild_id_env = os.getenv("DISCORD_GUILD_ID")
        guild_paths: list[str] = []
        if guild_id_env:
            gid = int(guild_id_env)
            guild_cmds = await bot.http.get_guild_commands(app_id, gid)
            tc_guild = next((c for c in guild_cmds if c.get("name") == "tc"), None)
            guild_paths = flatten_paths(tc_guild)

        global_cmds = await bot.http.get_global_commands(app_id)
        tc_global = next((c for c in global_cmds if c.get("name") == "tc"), None)
        global_paths = flatten_paths(tc_global)

        payload = {
            "guild_paths": guild_paths,
            "global_paths": global_paths,
        }
        await interaction.followup.send(
            content=f"```json\n{json.dumps(payload, indent=2)}\n```",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Debug failed: `{e}`", ephemeral=True)

# ================= Global app command error logger =================
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        print(f"AppCommandError: {type(error).__name__}: {error}")
        data = getattr(interaction, 'data', None)
        try:
            print("Interaction data:")
            print(json.dumps(data, indent=2))
        except Exception:
            print("Interaction data (raw):", data)
    except Exception as log_e:
        print("Failed to log app command error:", log_e)

# ================= Run =================
if __name__ == "__main__":
    # Recommended Railway start: python -u bot_unified.py
    bot.run(DISCORD_BOT_TOKEN)
