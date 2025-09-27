# CC to TC without DB 
import os
import re
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from typing import Any, Optional, Dict
from src.bot.base_cog import BaseCog

# Emojis (set these in .env for custom server emojis)
UNB_ICON = os.getenv("CURRENCY_EMOTE", "")      # UnbelievaBoat
ENG_ICON = os.getenv("CURRENCY_EMOJI", "")      # Engauge 

# Fixed conversion rate (override via .env EXCHANGE_RATE_UNB_PER_ENG)
UNB_PER_ENG = int(os.getenv("EXCHANGE_RATE_UNB_PER_ENG", "125"))

# API endpoints
RABBIT_API_RANDOM = os.getenv("RABBIT_API_URL", "https://rabbit-api-two.vercel.app/api/random")
DOG_API_RANDOM = os.getenv("DOG_API_URL", "https://dog.ceo/api/breeds/image/random")
CAT_API_RANDOM = "https://api.thecatapi.com/v1/images/search"
CAT_API_KEY = os.getenv("CAT_API_KEY", "")
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

# COMMENTED OUT - Using unified database system instead of Unbelievaboat API
# class UnbelievaBoat:
#     """UnbelievaBoat cash updater (PATCH delta)."""
#     def __init__(self):
#         self.base = "https://unbelievaboat.com/api/v1"
#         self.token = os.getenv("UNBELIEVABOAT_TOKEN")
#         if not self.token:
#             raise RuntimeError("Set UNBELIEVABOAT_TOKEN")

#     def _headers(self):
#         return {
#             "Authorization": self.token,   # raw token
#             "Accept": "application/json",
#             "Content-Type": "application/json",
#         }

#     async def update_cash(self, guild_id: int, user_id: int, delta: int, reason: str):
#         url = f"{self.base}/guilds/{int(guild_id)}/users/{int(user_id)}"
#         payload = {"cash": int(delta), "reason": reason}
#         async with aiohttp.ClientSession() as s:
#             async with s.patch(url, json=payload, headers=self._headers()) as r:
#                 if r.status >= 400:
#                     try:
#                         data = await r.json()
#                         msg = str(data)
#                     except Exception:
#                         msg = await r.text()
#                     if "insufficient" in msg.lower():
#                         raise InsufficientFunds(msg)
#                     raise ProviderError(f"UNB HTTP {r.status}: {msg}")

#     async def credit(self, guild_id: int, user_id: int, amount: int, reason: str):
#         await self.update_cash(guild_id, user_id, abs(int(amount)), reason)

# ============================ Modal ============================
class BuyUnbModal(discord.ui.Modal, title="Buy TC"):
    eng_amount = discord.ui.TextInput(
        label="How much CC do you want to spend?",
        placeholder="e.g., 5",
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
class Fun(BaseCog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)

    @staticmethod
    def _extract_bunny_image_url(payload: Any) -> Optional[str]:
        """
        The API returns JSON; we don't rely on a fixed schema.
        Try common keys first, then fall back to 'find any URL-looking string'.
        """
        # Common simple shapes
        if isinstance(payload, dict):
            for key in ("url", "image", "img", "link", "src"):
                v = payload.get(key)
                if isinstance(v, str) and v.startswith("http"):
                    return v
            # Sometimes the image is nested one level deep
            for v in payload.values():
                if isinstance(v, dict):
                    for key in ("url", "image", "img", "link", "src"):
                        sv = v.get(key)
                        if isinstance(sv, str) and sv.startswith("http"):
                            return sv
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and item.startswith("http"):
                            return item
                        if isinstance(item, dict):
                            for key in ("url", "image", "img", "link", "src"):
                                sv = item.get(key)
                                if isinstance(sv, str) and sv.startswith("http"):
                                    return sv
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, str) and item.startswith("http"):
                    return item
                if isinstance(item, dict):
                    for key in ("url", "image", "img", "link", "src"):
                        sv = item.get(key)
                        if isinstance(sv, str) and sv.startswith("http"):
                            return sv

        # Fallback: scan for any URL in the JSON dump
        text = str(payload)
        m = re.search(r"https?://\S+\.(?:png|jpg|jpeg|gif|webp)", text, flags=re.I)
        return m.group(0) if m else None
    @staticmethod
    def _extract_dog_image_url(payload: Any) -> str:
        """
        Dog CEO API has a stable schema: { "message": <url>, "status": "success" }
        """
        if isinstance(payload, dict):
            url = payload.get("message")
            if isinstance(url, str) and url.startswith("http"):
                return url
        return ""

    @staticmethod
    def _extract_cat_image_url(payload: Any) -> Optional[str]:
        """
        The Cat API returns an array of objects with 'url' field: [{ "url": <url>, ... }]
        """
        if isinstance(payload, list) and len(payload) > 0:
            first_item = payload[0]
            if isinstance(first_item, dict):
                url = first_item.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
        return None

    # ============================ Dog ============================
    @app_commands.command(name="dog", description="Send a random dog image")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.user.id))
    async def dog(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(DOG_API_RANDOM, timeout=15) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"API returned HTTP {resp.status}")
                    data: Dict[str, Any] = await resp.json()

            img_url = self._extract_dog_image_url(data)
            if not img_url:
                raise RuntimeError("Couldn't find an image URL in the API response.")

            embed = discord.Embed(
                title="Here’s a dog! 🐶",
                color=discord.Color.random()
            )
            embed.set_image(url=img_url)
            embed.set_footer(text="Source: dog.ceo")

            await interaction.followup.send(embed=embed)

        except Exception:
            await interaction.followup.send(
                "Couldn't fetch a dog right now. Try again in a moment 🐕",
                ephemeral=True
            )

    # ============================ Bunny ============================
    @app_commands.command(name="bunny", description="Send a random bunny image")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.user.id))
    async def bunny(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RABBIT_API_RANDOM, timeout=15) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"API returned HTTP {resp.status}")
                    data: Dict[str, Any] = await resp.json(content_type=None)

            img_url = self._extract_bunny_image_url(data)
            if not img_url:
                raise RuntimeError("Couldn't find an image URL in the API response.")

            embed = discord.Embed(
                title="Here’s a bunny! 🐰",
                color=discord.Color.random()
            )
            embed.set_image(url=img_url)
            embed.set_footer(text="Source: rabbit-api-two.vercel.app")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            # Keep errors out of chat; give a clean message instead.
            await interaction.followup.send(
                "Couldn't fetch a bunny right now. Try again in a moment 🐇",
                ephemeral=True
            )
    # ============================ Cat ============================
    @app_commands.command(name="cat", description="Send a random cat image")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.user.id))
    async def cat(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            headers = {}
            if CAT_API_KEY:
                headers["x-api-key"] = CAT_API_KEY

            async with aiohttp.ClientSession() as session:
                async with session.get(CAT_API_RANDOM, headers=headers, timeout=15) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"API returned HTTP {resp.status}")
                    data: Dict[str, Any] = await resp.json()

            img_url = self._extract_cat_image_url(data)
            if not img_url:
                raise RuntimeError("Couldn't find an image URL in the API response.")

            embed = discord.Embed(
                title="Here's a cat! 🐱",
                color=discord.Color.random()
            )
            embed.set_image(url=img_url)
            embed.set_footer(text="Source: The Cat API")

            await interaction.followup.send(embed=embed)

        except Exception:
            await interaction.followup.send(
                "Couldn't fetch a cat right now. Try again in a moment 🐈",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
