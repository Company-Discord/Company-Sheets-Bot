# crash.py — Unified database edition (in-memory, Cash Out button, Mixture risk)
import os
import math
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
discord import app_commands
from discord.app_commands import CheckFailure

# Import unified database and base cog
from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager

# ============================ Config ============================

# Currency emoji constant
TC_EMOJI = os.getenv('TC_EMOJI', '💰')

CURRENCY_ICON = os.getenv("CURRENCY_EMOTE") 
if not CURRENCY_ICON:
    raise RuntimeError("CURRENCY_EMOTE must be set in your .env ")

# Game tuning
TICK_SECONDS = float(os.getenv("TICK_SECONDS", "0.1"))  # Default: 0.1 seconds per tick
GROWTH_PER_TICK = float(os.getenv("GROWTH_PER_TICK", "0.02"))  # Default: 2% growth per tick
# Mixture risk model (high-risk/high-reward)
RISK_MIX_P_HARSH = float(os.getenv("RISK_MIX_P_HARSH", "0.65"))  # Default: 65% harsh, 35% lucky
MEAN_HARSH = float(os.getenv("MEAN_HARSH", "0.8"))  # Default: avg crash ≈ 1.8×
MEAN_LUCKY = float(os.getenv("MEAN_LUCKY", "3.0"))  # Default: avg crash ≈ 4.0×
RNG = random.SystemRandom()

def draw_crash_multiplier() -> float:
    """Harsh vs Lucky round: 1 + Exp(mean) with mixture probabilities."""
    if RNG.random() < RISK_MIX_P_HARSH:
        return 1.0 + RNG.expovariate(1.0 / MEAN_HARSH)
    else:
        return 1.0 + RNG.expovariate(1.0 / MEAN_LUCKY)

# ============================ Custom Exceptions ============================

class InsufficientFunds(Exception):
    """Raised when user doesn't have enough funds for a transaction."""
    pass


# ============================ Round State (in-memory) ============================

@dataclass
class Bet:
    user_id: int
    amount: int
    auto_cashout: Optional[float] = None
    cashed_out: bool = False
    payout: int = 0

@dataclass
class RoundState:
    status: str = "idle"   # idle | betting | flying | crashed | paid
    open_until_ts: float = 0.0
    started_ts: float = 0.0
    crash_at_multiplier: float = 0.0
    current_mult: float = 1.0
    bets: Dict[int, Bet] = field(default_factory=dict)
    guild_id: int = 0
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    task: Optional[asyncio.Task] = None


# ============================ Cash Out Button View ============================

class CrashView(discord.ui.View):
    def __init__(self, cog: "Crash", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="💸 Cash Out", style=discord.ButtonStyle.green)
    async def cashout(self, inter: discord.Interaction, button: discord.ui.Button):
        rs = self.cog._guild_round(self.guild_id)
        if rs.status != "flying":
            return await inter.response.send_message("❌ You can only cash out while flying.", ephemeral=True)

        b = rs.bets.get(inter.user.id)
        if not b or b.cashed_out:
            return await inter.response.send_message("❌ You have no active bet to cash out.", ephemeral=True)

        payout = int(math.floor(b.amount * rs.current_mult))
        try:
            await self.cog.add_cash(inter.user.id, self.guild_id, payout, "Crash cashout")
        except Exception as e:
            return await inter.response.send_message(f"⚠️ Payout error: {e}", ephemeral=True)
        # (weekly lottery dispatch)
        net_profit = max(0, payout - b.amount)
        try:
            if net_profit > 0:
                self.cog.bot.dispatch("gamble_winnings", self.guild_id, inter.user.id, net_profit, "Crash")
        except Exception:
            pass

        b.cashed_out = True
        b.payout = payout
        await inter.response.send_message(
            f"✅ Cashed out at **{self.cog._format_mult(rs.current_mult)}** → {CURRENCY_ICON} {payout:,}",
            ephemeral=True
        )
        await self.cog._refresh_embed(self.guild_id)


# ============================ Cog ============================

class Crash(BaseCog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.rounds: Dict[int, RoundState] = {}  # in-memory per-guild
    
    async def cog_load(self):
        """Initialize the unified database when cog loads."""
        await super().cog_load()
        print("✅ Unified database initialized for Crash")

    # ---- Clear message for failed permission checks ----
    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, CheckFailure):
            try:
                msg = f"❌ You must be an **Admin** or **Manager** to use this command."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

    # -------- Utilities --------

    def _guild_round(self, guild_id: int) -> RoundState:
        return self.rounds.setdefault(guild_id, RoundState(guild_id=guild_id))

    def _format_mult(self, m: float) -> str:
        return f"{m:.2f}×"

    async def _get_channel_message(self, guild_id: int) -> Optional[Tuple[discord.TextChannel, discord.Message]]:
        rs = self._guild_round(guild_id)
        if not rs.channel_id or not rs.message_id:
            return None
        ch = self.bot.get_channel(rs.channel_id)
        if not isinstance(ch, discord.TextChannel):
            return None
        try:
            msg = await ch.fetch_message(rs.message_id)
            return ch, msg
        except Exception:
            return None

    async def _refresh_embed(self, guild_id: int, *, footer: Optional[str] = None):
        rs = self._guild_round(guild_id)
        chmsg = await self._get_channel_message(guild_id)
        if not chmsg:
            return
        ch, msg = chmsg

        pool = sum(b.amount for b in rs.bets.values() if not b.cashed_out)
        winners_pool = sum(b.payout for b in rs.bets.values() if b.cashed_out)
        a_count = sum(1 for b in rs.bets.values() if b.auto_cashout is not None)
        bettors = len(rs.bets)

        if rs.status == "betting":
            countdown = f"<t:{int(rs.open_until_ts)}:R>"
            top = f"**Status:** `BETTING`\n⏳ **Round starts** {countdown}\n🎯 **Current Mult:** 1.00×\n"
        elif rs.status == "flying":
            top = f"**Status:** `FLYING`\n🚀 **Current Mult:** **{self._format_mult(rs.current_mult)}**\n"
        elif rs.status == "COMPLETED":
            top = f"**Status:** `COMPLETED`\n💥 **Final Multiplier:** **{self._format_mult(rs.crash_at_multiplier)}**\n"
        else:
            top = f"**Status:** `{rs.status.upper()}`\n"

        desc = (
            f"{top}\n"
            f"👥 **Bettors:** {bettors}\n"
            f"{TC_EMOJI} **Active Pool:** {CURRENCY_ICON} {pool:,}\n"
            f"💸 **Paid so far:** {CURRENCY_ICON} {winners_pool:,}\n"
            f"🧷 **Auto-cashout set:** {a_count}\n\n"
            f"Use **/crash bet** during betting, and **/crash cashout** while flying."
        )

        emb = discord.Embed(
            title="🎰 Crash — High Risk · High Reward",
            description=desc,
            color=discord.Color.red() if rs.status == "COMPLETED" else (discord.Color.orange() if rs.status == "flying" else discord.Color.blurple())
        )

        if rs.bets:
            lines = []
            for uid, b in list(rs.bets.items())[:8]:
                u = self.bot.get_user(uid)
                name = u.name if u else str(uid)
                if rs.status == "COMPLETED":
                    if b.cashed_out:
                        status = "✅ cashed out"
                        val = b.payout
                    else:
                        status = "❌ crashed"
                        val = b.amount
                    ac = f" · auto {b.auto_cashout:.2f}×" if b.auto_cashout else ""
                else:
                    status = f"{TC_EMOJI} cashed" if b.cashed_out else "⏳ live"
                    ac = f" · auto {b.auto_cashout:.2f}×" if b.auto_cashout else ""
                    val = b.payout if b.cashed_out else b.amount
                lines.append(f"• **{name}** — {status}{ac} — {CURRENCY_ICON} {val:,}")
            emb.add_field(name="Players", value="\n".join(lines), inline=False)

        if footer:
            emb.set_footer(text=footer)

        view = CrashView(self, guild_id) if rs.status == "flying" else None
        try:
            await msg.edit(embed=emb, view=view)
        except Exception:
            pass

    # -------- Game Loop --------

    async def _run_round(self, guild_id: int):
        rs = self._guild_round(guild_id)

        # Wait out the betting window
        await asyncio.sleep(max(0, int(rs.open_until_ts) - int(discord.utils.utcnow().timestamp())))

        # If nobody bet, quietly end
        if not rs.bets:
            rs.status = "idle"
            await self._refresh_embed(guild_id, footer="No bets placed; round not started.")
            return

        # Launch
        rs.status = "flying"
        rs.started_ts = int(discord.utils.utcnow().timestamp())
        rs.current_mult = 1.0
        rs.crash_at_multiplier = draw_crash_multiplier()  # mixture risk
        await self._refresh_embed(guild_id)

        # Fly until crash
        while rs.current_mult < rs.crash_at_multiplier and rs.status == "flying":
            rs.current_mult *= (1.0 + GROWTH_PER_TICK)
            if rs.current_mult > 1000:  # safety clamp
                rs.current_mult = 1000.0

            # auto-cashouts
            for uid, b in list(rs.bets.items()):
                if not b.cashed_out and b.auto_cashout and rs.current_mult >= b.auto_cashout:
                    payout = int(math.floor(b.amount * rs.current_mult))
                    try:
                        await self.add_cash(uid, guild_id, payout, "Crash auto-cashout")
                        b.cashed_out = True
                        b.payout = payout
                        # (weekly lottery dispatch)
                        net_profit = max(0, payout - b.amount)
                        try:
                            if net_profit > 0:
                                self.bot.dispatch("gamble_winnings", guild_id, uid, net_profit, "Crash")
                        except Exception:
                            pass
                        # End of Lottery dispatch
                    except Exception as e:
                        print("auto cashout credit error:", e)

            await self._refresh_embed(guild_id)
            await asyncio.sleep(TICK_SECONDS)

        # Crash
        rs.status = "COMPLETED"
        rs.current_mult = rs.crash_at_multiplier
        await self._refresh_embed(guild_id, footer="💥 The rocket crashed!")

        # Settle & reset
        await asyncio.sleep(2.0)
        await self._refresh_embed(guild_id, footer="Round completed. Start a new one with /crash start")

        await asyncio.sleep(3.0)
        # Reset to idle; keep the message hook for continuity
        self.rounds[guild_id] = RoundState(guild_id=guild_id, channel_id=rs.channel_id, message_id=rs.message_id)

    # -------- Commands --------

    group = app_commands.Group(name="crash", description="Crash gambling game", parent=tc)

    @group.command(name="start", description="Start a crash round (opens betting)")
    @is_admin_or_manager()
    @app_commands.describe(open_seconds="How long to accept bets before launch")
    async def start(self, inter: discord.Interaction, open_seconds: app_commands.Range[int, 5, 120] = 20):
        await inter.response.defer(ephemeral=True)
        rs = self._guild_round(inter.guild_id)
        if rs.status in ("betting", "flying"):
            return await inter.followup.send("A round is already active in this server.", ephemeral=True)

        now = int(discord.utils.utcnow().timestamp())
        rs.status = "betting"
        rs.open_until_ts = now + open_seconds
        rs.channel_id = inter.channel_id
        rs.message_id = None
        rs.bets.clear()

        # Announce
        ch = inter.channel
        if ch and isinstance(ch, discord.TextChannel):
            embed = discord.Embed(
                title="🎰 Crash — High Risk · High Reward",
                description=(
                    f"**Status:** `BETTING`\n"
                    f"⏳ **Round starts** <t:{rs.open_until_ts}:R>\n"
                    f"🎯 **Current Mult:** 1.00×\n\n"
                    f"Place a bet with **/crash bet** (optional `auto_cashout`).\n"
                    f"Cash out with **/crash cashout** during flight!\n\n"
                    f"💡 Tip: a green **Cash Out** button will appear when the rocket is flying."
                ),
                color=discord.Color.blurple(),
            )
            msg = await ch.send(embed=embed)
            rs.message_id = msg.id

        # Spin loop
        if rs.task and not rs.task.done():
            rs.task.cancel()
        rs.task = asyncio.create_task(self._run_round(inter.guild_id))

        await inter.followup.send(f"Crash round opened for **{open_seconds}s**. Bets are live!", ephemeral=True)

    @group.command(name="bet", description="Place a bet (optionally set auto-cashout)")
    @is_admin_or_manager()
    @app_commands.describe(
        amount="Amount of currency to bet (integer)",
        auto_cashout="Auto-cashout at this multiplier (e.g., 1.50). Leave empty to cash manually."
    )
    async def bet(
        self,
        inter: discord.Interaction,
        amount: app_commands.Range[int, 1, 10_000_000],
        auto_cashout: Optional[app_commands.Range[float, 1.01, 1000.0]] = None
    ):
        await inter.response.defer(ephemeral=True)
        rs = self._guild_round(inter.guild_id)
        if rs.status != "betting":
            return await inter.followup.send("Betting is closed. Wait for the next round.", ephemeral=True)

        # single active bet (rebuy replaces: refund old → debit new)
        existing = rs.bets.get(inter.user.id)
        try:
            user_balance = await self.get_user_balance(inter.user.id, inter.guild_id)
            if user_balance.cash < amount:
                return await inter.followup.send("You don't have enough currency for this bet.", ephemeral=True)
            
            if existing:
                await self.add_cash(inter.user.id, inter.guild_id, existing.amount, "Crash bet replace refund")
            
            if not await self.deduct_cash(inter.user.id, inter.guild_id, amount, "Crash bet stake"):
                return await inter.followup.send("❌ You don't have enough currency for this bet.", ephemeral=True)
        except Exception as e:
            return await inter.followup.send(f"⚠️ Error processing bet: {e}", ephemeral=True)

        rs.bets[inter.user.id] = Bet(
            user_id=inter.user.id,
            amount=int(amount),
            auto_cashout=float(auto_cashout) if auto_cashout else None
        )

        ac_txt = f" with auto-cashout at **{auto_cashout:.2f}×**" if auto_cashout else ""
        await inter.followup.send(
            f"Bet placed for **{CURRENCY_ICON} {amount:,}**{ac_txt}. Good luck! 🚀",
            ephemeral=True
        )
        await self._refresh_embed(inter.guild_id)

    @group.command(name="cashout", description="Cash out your active bet (during flight)")
    @is_admin_or_manager()
    async def cashout(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        rs = self._guild_round(inter.guild_id)
        if rs.status != "flying":
            return await inter.followup.send("You can only cash out while the rocket is flying.", ephemeral=True)

        b = rs.bets.get(inter.user.id)
        if not b or b.cashed_out:
            return await inter.followup.send("You have no active bet to cash out.", ephemeral=True)

        payout = int(math.floor(b.amount * rs.current_mult))
        try:
            await self.add_cash(inter.user.id, inter.guild_id, payout, "Crash manual cashout")
        except Exception as e:
            return await inter.followup.send(f"⚠️ Error while paying out: {e}", ephemeral=True)
        # (weekly lottery dispatch)
        net_profit = max(0, payout - b.amount)
        try:
            if net_profit > 0:
                self.bot.dispatch("gamble_winnings", inter.guild_id, inter.user.id, net_profit, "Crash")
        except Exception:
            pass
        # End of Lottery Dispatch
        b.cashed_out = True
        b.payout = payout
        await inter.followup.send(
            f"✅ Cashed out at **{self._format_mult(rs.current_mult)}** → {CURRENCY_ICON} {payout:,}",
            ephemeral=True
        )
        await self._refresh_embed(inter.guild_id)

    @group.command(name="cancel", description="Cancel current crash round and refund live stakes")
    @is_admin_or_manager()
    async def cancel(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        rs = self._guild_round(inter.guild_id)
        if rs.status not in ("betting", "flying"):
            return await inter.followup.send("No cancellable round right now.", ephemeral=True)

        # refund only those not cashed out
        for uid, b in list(rs.bets.items()):
            if not b.cashed_out and b.amount > 0:
                try:
                    await self.add_cash(uid, inter.guild_id, b.amount, "Crash round canceled refund")
                except Exception as e:
                    print("refund error:", e)

        # reset state
        self.rounds[inter.guild_id] = RoundState(guild_id=inter.guild_id)
        await inter.followup.send("Round canceled. Refunds sent.", ephemeral=True)
        chmsg = await self._get_channel_message(inter.guild_id)
        if chmsg:
            ch, _ = chmsg
            await ch.send("❌ Crash round canceled — all active stakes refunded.")

    @group.command(name="status", description="Show current crash round status")
    @is_admin_or_manager()
    async def status(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        rs = self._guild_round(inter.guild_id)
        if rs.status == "idle":
            return await inter.followup.send("No active crash round. Start one with **/crash start**.", ephemeral=True)
        await self._refresh_embed(inter.guild_id)
        chmsg = await self._get_channel_message(inter.guild_id)
        if chmsg:
            _, msg = chmsg
            await inter.followup.send(f"Showing the latest status here: {msg.jump_url}", ephemeral=True)
        else:
            await inter.followup.send("Status refreshed.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Crash(bot))
