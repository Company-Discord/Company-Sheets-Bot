# fun.py
import io
import random
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from tenacity import retry, stop_after_attempt, wait_fixed

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
UNSPLASH_RANDOM = "https://source.unsplash.com/random/?rat"
LOREMFLICKR = "https://loremflickr.com/800/600/rat"

HEADERS = {
    "User-Agent": "DiscordBot-RatPics/1.0 (contact: you@example.com)"
}

class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _download_bytes(self, session: aiohttp.ClientSession, url: str) -> bytes:
        # follow redirects and read bytes
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} for {url}")
            return await resp.read()

    async def _fetch_wikimedia_candidates(self, session: aiohttp.ClientSession) -> list[str]:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": "rat -mouse filetype:bitmap",
            "gsrlimit": "50",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "origin": "*",
        }
        async with session.get(
            WIKIMEDIA_API,
            params=params,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
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
    async def _get_rat_image(self) -> tuple[bytes, str]:
        """
        Try multiple sources with retries. Returns (image_bytes, source_name).
        """
        async with aiohttp.ClientSession() as session:
            # 1) LoremFlickr (very reliable, no key)
            try:
                data = await self._download_bytes(session, LOREMFLICKR)
                return data, "LoremFlickr"
            except Exception:
                pass

            # 2) Wikimedia Commons
            try:
                candidates = await self._fetch_wikimedia_candidates(session)
                if candidates:
                    url = random.choice(candidates)
                    data = await self._download_bytes(session, url)
                    return data, "Wikimedia Commons"
            except Exception:
                pass

            # 3) Unsplash random fallback
            data = await self._download_bytes(session, UNSPLASH_RANDOM)
            return data, "Unsplash"

    @app_commands.command(name="rat", description="Get a random rat picture 🐀")
    async def rat(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            img_bytes, source = await self._get_rat_image()
            file = discord.File(io.BytesIO(img_bytes), filename="rat.jpg")
            embed = discord.Embed(title="Here’s your random rat 🐀", color=discord.Color.dark_gray())
            embed.set_image(url="attachment://rat.jpg")
            embed.set_footer(text=f"Source: {source}")
            await interaction.followup.send(embed=embed, file=file)
        except Exception as e:
            # Show a concise error to user; detailed error goes to logs
            try:
                await interaction.followup.send("❌ Failed to fetch rat pic. Try again in a bit.", ephemeral=True)
            except Exception:
                pass
            # Log full error to console for troubleshooting
            print("rat command failed:", repr(e))

async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
