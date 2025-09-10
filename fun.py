import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rat", description="Get a random rat picture 🐀")
    async def rat(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            # Unsplash random image with the query 'rat'
            url = "https://source.unsplash.com/random/?rat"

            embed = discord.Embed(title="Here’s your random rat 🐀", color=discord.Color.dark_gray())
            embed.set_image(url=url)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch rat pic: `{e}`", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
