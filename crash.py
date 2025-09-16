# crash.py — UnbelievaBoat edition (in-memory, Cash Out button, Mixture risk)
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
from discord.app_commands import CheckFailure

# Import permissions from utils.py
from utils import is_admin_or_manager

# ============================ Config ============================

CURRENCY_ICON = os.getenv("CURRENCY_EMOTE") 
if not CURRENCY_ICON:
    raise RuntimeError("CURRENCY_EMOTE must be set in your .env ")

UNB_TOKEN = os.getenv("UNBELIEVABOAT_TOKEN")
if not UNB_TOKEN:
    raise RuntimeError("UNBELIEVABOAT_TOKEN must be set in your .env")

# Game tuning
TICK_SECONDS = 1.0            
GROWTH_PER_TICK = 0.08        
# Mixture risk model (high-risk/high-reward)
RISK_MIX_P_HARSH = 0.65       # 65% harsh, 35% lucky
MEAN_HARSH = 0.8              # avg crash ≈ 1.8×
MEAN_LUCKY = 3.0              # avg crash ≈ 4.0×
RNG = random.SystemRandom()

def draw_crash_multiplier() -> float:
    """Harsh vs Lucky round: 1 + Exp(mean) with mixture probabilities."""
    if RNG.random() < RISK_MIX_P_HARSH:
        return 1.0 + RNG.expovariate(1.0 / MEAN_HARSH)
    else:
        return 1.0 + RNG.expovariate(1.0 / MEAN_LUCKY)

# ============================ UnbelievaBoat Adapter ============================

class UnbAPIError(Exception):
    pass

class InsufficientFunds(UnbAPIError):
    pass

class UnbelievaBoat:
    """
    Minimal UnbelievaBoat API client for cash balance deltas.

    Docs:
      - Base URL: https://unbelievaboat.com/api/{version} (v1) :contentReference[oaicite:1]{index=1}
      - PATCH /v1/guilds/{guild_id}/users/{user_id} to add/remove cash (JSON body with 'cash'). :contentReference[oaicite:2]{index=2}
      - GET same path returns balance (not used here). :contentReference[oaicite:3]{index=3}
    """
    def __init__(self, token: str):
        self.base = "https://unbelievaboat.com/api/v1"
        self.token = token

    def _headers(self):
        # Authorization header is the raw token (no 'Bearer'/'Bot' prefix). :contentReference[oaicite:4]{index=4}
        return {
            "Authorization": self.token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def update_cash(self, guild_id: int, user_id: int, delta: int, reason: str):
        """
        Increase/decrease user's cash by delta (negative for debit).
        Endpoint: PATCH /guilds/{guild_id}/users/{user_id}
        Body: {"cash": <delta>, "reason": "..."}  (bank omitted)
        """
        url = f"{self.base}/guilds/{int(guild_id)}/users/{int(user_id)}"
        payload = {"cash": int(delta), "reason": reason}
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, json=payload, headers=self._headers()) as r:
                if r.status >= 400:
                    # Try to detect insufficient funds (common 400 message)
                    try:
                        data = await r.json()
                        msg = str(data)
                    except Exception:
                        msg = await r.text()
                    msg_lower = msg.lower()
                    if "insufficient" in msg_lower or "not enough" in msg_lower:
                        raise InsufficientFunds(msg)
                    raise UnbAPIError(f"HTTP {r.status}: {msg}")

    async def debit(self, guild_id: int, user_id: int, amount: int, reason: str):
        await self.update_cash(guild_id, user_id, -abs(int(amount)), reason)

    async def credit(self, guild_id: int, user_id: int, amount: int, reason: str):
        await self.update_cash(guild_id, user_id, abs(int(amount)), reason)


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
            await self.cog.unb.credit(self.guild_id, inter.user.id, payout, reason="Crash cashout")
        except Exception as e:
            return await inter.response.send_message(f"⚠️ UnbelievaBoat error: {e}", ephemeral=True)

        b.cashed_out = True
        b.payout = payout
        await inter.response.send_message(
            f"✅ Cashed out at **{self.cog._format_mult(rs.current_mult)}** → {CURRENCY_ICON} {payout:,}",
            ephemeral=True
        )
        await self.cog._refresh_embed(self.guild_id)


# ============================ Cog ============================

class Crash(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.unb = UnbelievaBoat(UNB_TOKEN)
        self.rounds: Dict[int, RoundState] = {}  # in-memory per-guild

    # ---- Clear message for failed permission checks ----
    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, CheckFailure):
            try:
                msg = f"❌ You must be an **Admin** or have the **{MANAGER_ROLE_NAME}** role to use this command."
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
        elif rs.status == "crashed":
            top = f"**Status:** `CRASHED`\n💥 **Crashed at:** **{self._format_mult(rs.crash_at_multiplier)}**\n"
        else:
            top = f"**Status:** `{rs.status.upper()}`\n"

        desc = (
            f"{top}\n"
            f"👥 **Bettors:** {bettors}\n"
            f"💰 **Active Pool:** {CURRENCY_ICON} {pool:,}\n"
            f"💸 **Paid so far:** {CURRENCY_ICON} {winners_pool:,}\n"
            f"🧷 **Auto-cashout set:** {a_count}\n\n"
            f"Use **/crash bet** during betting, and **/crash cashout** while flying."
        )

        emb = discord.Embed(
            title="🎰 Crash — High Risk · High Reward",
            description=desc,
            color=discord.Color.orange() if rs.status == "flying" else discord.Color.blurple()
        )

        if rs.bets:
            lines = []
            for uid, b in list(rs.bets.items())[:8]:
                u = self.bot.get_user(uid)
                name = u.name if u else str(uid)
                status = "💰 cashed" if b.cashed_out else "⏳ live"
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
                        await self.unb.credit(guild_id, uid, payout, reason="Crash auto-cashout")
                        b.cashed_out = True
                        b.payout = payout
                    except Exception as e:
                        print("auto cashout credit error:", e)

            await self._refresh_embed(guild_id)
            await asyncio.sleep(TICK_SECONDS)

        # Crash
        rs.status = "crashed"
        rs.current_mult = rs.crash_at_multiplier
        await self._refresh_embed(guild_id, footer="💥 The rocket crashed!")

        # Settle & reset
        await asyncio.sleep(2.0)
        rs.status = "paid"
        await self._refresh_embed(guild_id, footer="Round settled. Start a new one with /crash start")

        await asyncio.sleep(3.0)
        # Reset to idle; keep the message hook for continuity
        self.rounds[guild_id] = RoundState(guild_id=guild_id, channel_id=rs.channel_id, message_id=rs.message_id)

    # -------- Commands --------

    group = app_commands.Group(name="crash", description="Crash gambling game")

    @group.command(name="start", description="Start a crash round (opens betting)")
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
            if existing:
                await self.unb.credit(inter.guild_id, inter.user.id, existing.amount, reason="Crash bet replace refund")
            await self.unb.debit(inter.guild_id, inter.user.id, amount, reason="Crash bet stake")
        except InsufficientFunds:
            return await inter.followup.send("You don't have enough currency for this bet.", ephemeral=True)
        except Exception as e:
            return await inter.followup.send(f"UnbelievaBoat error: {e}", ephemeral=True)

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
            await self.unb.credit(inter.guild_id, inter.user.id, payout, reason="Crash manual cashout")
        except Exception as e:
            return await inter.followup.send(f"UnbelievaBoat error while paying out: {e}", ephemeral=True)

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
                    await self.unb.credit(inter.guild_id, uid, b.amount, reason="Crash round canceled refund")
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
