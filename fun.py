# CC to TC cog without DB
import os
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

# Emojis (set these in your .env for custom server emojis)
UNB_ICON = os.getenv("CURRENCY_EMOTE", "")      # UnbelievaBoat
ENG_ICON = os.getenv("CURRENCY_EMOJI", "")      # Engauge 

# Fixed conversion rate (override via .env EXCHANGE_RATE_UNB_PER_ENG)
UNB_PER_ENG = int(os.getenv("EXCHANGE_RATE_UNB_PER_ENG", "125"))

# ============================ Exceptions ============================
class ProviderError(Exception): ...
class InsufficientFunds(ProviderError): ...

# ============================ API Adapters ============================
class Engauge:
    """Server-scoped Engauge currency adjuster (POST amount delta)."""
    def __init__(self):
        self.base = "https://engau.ge/api/v1"
        self.token = os.getenv("ENGAUGE_API_TOKEN") or os.getenv("ENGAUGE_TOKEN", "")
        if not self.token:
            raise RuntimeError("Set ENGAUGE_API_TOKEN or ENGAUGE_TOKEN")

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    async def adjust(self, guild_id: int, user_id: int, amount: int):
        url = f"{self.base}/servers/{int(guild_id)}/members/{int(user_id)}/currency"
        params = {"amount": str(int(amount))}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params, headers=self._headers()) as r:
                if r.status == 402:
                    raise InsufficientFunds("Insufficient Engauge balance")
                if r.status >= 400:
                    raise ProviderError(f"Engauge HTTP {r.status}: {await r.text()}")

    async def debit(self, guild_id: int, user_id: int, amount: int):
        await self.adjust(guild_id, user_id, -abs(int(amount)))

    async def credit(self, guild_id: int, user_id: int, amount: int):
        await self.adjust(guild_id, user_id, abs(int(amount)))

class UnbelievaBoat:
    """UnbelievaBoat cash updater (PATCH delta)."""
    def __init__(self):
        self.base = "https://unbelievaboat.com/api/v1"
        self.token = os.getenv("UNBELIEVABOAT_TOKEN")
        if not self.token:
            raise RuntimeError("Set UNBELIEVABOAT_TOKEN")

    def _headers(self):
        return {
            "Authorization": self.token,   # raw token
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def update_cash(self, guild_id: int, user_id: int, delta: int, reason: str):
        url = f"{self.base}/guilds/{int(guild_id)}/users/{int(user_id)}"
        payload = {"cash": int(delta), "reason": reason}
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, json=payload, headers=self._headers()) as r:
                if r.status >= 400:
                    try:
                        data = await r.json()
                        msg = str(data)
                    except Exception:
                        msg = await r.text()
                    if "insufficient" in msg.lower():
                        raise InsufficientFunds(msg)
                    raise ProviderError(f"UNB HTTP {r.status}: {msg}")

    async def credit(self, guild_id: int, user_id: int, amount: int, reason: str):
        await self.update_cash(guild_id, user_id, abs(int(amount)), reason)

# ============================ Modal ============================
class BuyUnbModal(discord.ui.Modal, title="Buy UnbelievaBoat"):
    # Emoji is placed in the placeholder where it WILL render.
    eng_amount = discord.ui.TextInput(
        label="Amount to spend",
        placeholder=f"e.g., 5 {os.getenv('CURRENCY_EMOJI', '🪙')}",
        min_length=1,
        max_length=10
    )

    def __init__(self, cog: "Fun", inter: discord.Interaction, rate: int):
        super().__init__()
        self.cog = cog
        self.inter = inter
        self.rate = rate  # UNB granted per 1 ENG

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.inter.user.id:
            return await interaction.response.send_message("This modal isn't for you.", ephemeral=True)

        # Parse input
        try:
            eng_amt = int(str(self.eng_amount.value).strip())
            if eng_amt <= 0:
                raise ValueError
        except Exception:
            return await interaction.response.send_message("Enter a positive integer.", ephemeral=True)

        unb_gain = eng_amt * self.rate

        # Debit Engauge → then credit UNB; refund on UNB failure
        try:
            await self.cog._eng.debit(self.inter.guild_id, self.inter.user.id, eng_amt)
        except InsufficientFunds:
            return await interaction.response.send_message(
                f"You don't have enough {ENG_ICON} to spend **{eng_amt:,}**.",
                ephemeral=True
            )
        except Exception as e:
            return await interaction.response.send_message(f"Engauge error: {e}", ephemeral=True)

        try:
            await self.cog._unb.credit(
                self.inter.guild_id,
                self.inter.user.id,
                unb_gain,
                reason=f"Exchange {eng_amt} {ENG_ICON} → {unb_gain} {UNB_ICON} at {self.rate}/1"
            )
        except Exception as e:
            # Refund Engauge on failure
            try:
                await self.cog._eng.credit(self.inter.guild_id, self.inter.user.id, eng_amt)
            except Exception as e2:
                print("Refund failed after UNB error:", e2)
            return await interaction.response.send_message(
                f"UnbelievaBoat error: {e}. Refunded your {ENG_ICON}.",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"✅ Exchanged **{ENG_ICON} {eng_amt:,}** → **{UNB_ICON} {unb_gain:,}** "
            f"(Rate: **1 {ENG_ICON} → {self.rate} {UNB_ICON}**).",
            ephemeral=True
        )

# ============================ Cog ============================
class Fun(commands.Cog):
    """
    Minimal 'fun' cog containing only the exchange commands.
    Keep this filename/extension the same if your bot already loads `fun`.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._eng = Engauge()
        self._unb = UnbelievaBoat()
        self._rate = UNB_PER_ENG  # fixed at startup (env or code)

        # Optional: scope slash commands to a single guild to speed up registration
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild_obj = discord.Object(id=int(guild_id))
            for cmd in self.__cog_app_commands__:
                cmd.guild = guild_obj

    exchange = app_commands.Group(name="exchange", description="Engauge → UnbelievaBoat")

    @exchange.command(name="rate", description="Show the current fixed rate")
    async def exchange_rate(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Current rate: **1 {ENG_ICON} → {self._rate} {UNB_ICON}**.",
            ephemeral=True
        )

    @exchange.command(name="buy", description="Buy UnbelievaBoat using Engauge (opens a pop-up)")
    async def exchange_buy(self, interaction: discord.Interaction):
        modal = BuyUnbModal(self, interaction, self._rate)
        await interaction.response.send_modal(modal)

async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
