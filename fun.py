# fun.py
import io
import random
import asyncio
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from tenacity import retry, stop_after_attempt, wait_fixed

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
UNSPLASH_RANDOM = "https://source.unsplash.com/random/?rat"

HEADERS = {
    "User-Agent": "DiscordBot (rat pics) - contact: example@example.com"
}

class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------- HTTP helpers -------
    async def _download(self, session: aiohttp.ClientSession, url: str) -> bytes:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Bad response {resp.status}")
            return await resp.read()

    async def _fetch_wikimedia_candidates(self, session: aiohttp.ClientSession) -> list[str]:
        """
        Query Wikimedia Commons for rat images and return a list of image URLs.
        """
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            # bias toward photos; exclude "mouse" to reduce false positives
            "gsrsearch": "rat -mouse filetype:bitmap",
            "gsrlimit": "50",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": "2000",
            "origin": "*",
        }
        async with session.get(WIKIMEDIA_API, params=params, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        pages = (data.get("query", {}).get("pages", {}) or {}).values()
        urls = []
        for p in pages:
            infos = p.get("imageinfo", [])
            if not infos:
                continue
            url = infos[0].get("url")
            mime = infos[0].get("mime", "")
            if url and mime.startswith("image/"):
                urls.append(url)
        return urls

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1.5))
    async def _get_rat_bytes(self) -> tuple[bytes, str]:
        """
        Try Wikimedia first, then Unsplash. Returns (image_bytes, attribution_source).
        Retries on network/server errors (tenacity).
        """
        async with aiohttp.ClientSession() as session:
            # 1) Wikimedia
            try:
                candidates = await self._fetch_wikimedia_candidates(session)
                if candidates:
                    url = random.choice(candidates)
                    data = await self._download(session, url)
                    return data, "Wikimedia Commons"
            except Exception:
                # let it fall back silently
                pass

            # 2) Unsplash random (may redirect; still fine)
            data = await self._download(session, UNSPLASH_RANDOM)
            return data, "Unsplash"

    # ------- /rat command -------
    @app_commands.command(name="rat", description="Get a random rat picture 🐀")
    async def rat(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            img_bytes, source = await self._get_rat_bytes()
            file = discord.File(io.BytesIO(img_bytes), filename="rat.jpg")
            embed = discord.Embed(title="Here’s your random rat 🐀", color=discord.Color.dark_gray())
            embed.set_footer(text=f"Source: {source}")
            embed.set_image(url="attachment://rat.jpg")
            await interaction.followup.send(embed=embed, file=file)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch rat pic: `{e}`", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
