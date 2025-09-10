import io
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rat", description="Get a random rat picture 🐀")
    async def rat(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            # Unsplash random rat image
            src = "https://source.unsplash.com/random/?rat"

            async with aiohttp.ClientSession() as session:
                async with session.get(src) as resp:
                    if resp.status != 200:
                        raise Exception(f"Bad response {resp.status}")
                    data = await resp.read()

            file = discord.File(io.BytesIO(data), filename="rat.jpg")
            embed = discord.Embed(
                title="Here’s your random rat 🐀",
                color=discord.Color.dark_gray()
            )
            embed.set_image(url="attachment://rat.jpg")

            await interaction.followup.send(embed=embed, file=file)

        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to fetch rat pic: `{e}`",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
