# src/games/blackjack.py
import os, random, math, asyncio
from typing import List, Tuple, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

# ---- shared infra ----
from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager

CURRENCY_EMOTE = os.getenv("CURRENCY_EMOTE", ":TC:")

def fmt_tc(n: int) -> str:
    return f"{CURRENCY_EMOTE} {n:,}"

# ---------- card assets ----------
RANKS = ["A","2","3","4","5","6","7","8","9","T","J","Q","K"]
SUITS = ["S","H","D","C"]

CARD_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "cards"))

def card_png(rank: str, suit: str) -> str:
    return os.path.join(CARD_BASE, f"{rank}{suit}.png")

def back_png() -> str:
    return os.path.join(CARD_BASE, "back.png")

def _assert_assets():
    for name in ("AS.png", "KH.png", "2C.png", "TD.png", "back.png"):
        if not os.path.isfile(os.path.join(CARD_BASE, name)):
            raise FileNotFoundError(f"Missing card asset: {name} (expected in {CARD_BASE})")

# ---------- blackjack logic ----------
def new_shoe(num_decks: int = 6) -> List[Tuple[str,str]]:
    shoe = [(r,s) for r in RANKS for s in SUITS] * num_decks
    random.shuffle(shoe)
    return shoe

def hand_value(cards: List[Tuple[str,str]]) -> Tuple[int,bool]:
    total, aces = 0, 0
    for r,_ in cards:
        if r == "A":
            total += 11; aces += 1
        elif r in ("T","J","Q","K"):
            total += 10
        else:
            total += int(r)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    soft = (aces > 0 and total <= 21)
    return total, soft

def is_blackjack(cards: List[Tuple[str,str]]) -> bool:
    return len(cards) == 2 and hand_value(cards)[0] == 21

# ---------- View ----------
class BJView(discord.ui.View):
    def __init__(self, cog: "Blackjack", key: Tuple[int,int], timeout: int = 120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.key = key
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        st = self.cog.states.get(self.key)
        if not st: return False
        if interaction.user.id != st["user_id"]:
            await interaction.response.send_message("This isn’t your hand.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        st = self.cog.states.get(self.key)
        if st and not st["done"]:
            await self.cog.finish(st, auto_reason="Timed out — auto-stand")

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.success)
    async def hit_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        st = self.cog.states.get(self.key)
        if not st or st["done"]: return await interaction.response.defer()
        st["player"].append(st["shoe"].pop())
        await self.cog.refresh(interaction, st)
        total,_ = hand_value(st["player"])
        if total >= 21:
            await self.cog.finish(st)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.primary)
    async def stand_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        st = self.cog.states.get(self.key)
        if not st or st["done"]: return await interaction.response.defer()
        await self.cog.finish(st)

    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.danger)
    async def dd_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        st = self.cog.states.get(self.key)
        if not st or st["done"]: return await interaction.response.defer()

        async with self.cog.user_locks.setdefault(st["user_id"], asyncio.Lock()):
            bal = await self.cog.get_user_balance(st["user_id"], st["guild_id"])
            if bal.cash < st["bet"]:
                return await interaction.response.send_message("Not enough balance to double down.", ephemeral=True)
            ok = await self.cog.deduct_cash(st["user_id"], st["guild_id"], st["bet"], "Blackjack double-down escrow")
            if not ok:
                return await interaction.response.send_message("Couldn’t reserve the extra bet.", ephemeral=True)

        st["bet"] *= 2
        st["player"].append(st["shoe"].pop())
        await self.cog.refresh(interaction, st, footer="Doubled down")
        await self.cog.finish(st)

# ---------- Cog ----------
class Blackjack(BaseCog):
    """Blackjack using your unified currency system (no negative balances)."""
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        _assert_assets()
        self.shoes: Dict[int, List[Tuple[str,str]]] = {}
        self.states: Dict[Tuple[int,int], Dict] = {}
        self.user_locks: Dict[int, asyncio.Lock] = {}

    # --- helpers ---
    def shoe_for(self, guild_id: int) -> List[Tuple[str,str]]:
        shoe = self.shoes.get(guild_id)
        if not shoe or len(shoe) < 52:
            shoe = new_shoe(6)
            self.shoes[guild_id] = shoe
        return shoe

    async def build_embed(self, st: Dict, *, reveal: bool, footer: Optional[str]=None) -> discord.Embed:
        bet = st["bet"]
        p_total,_ = hand_value(st["player"])
        e = discord.Embed(title=f"Blackjack — Bet {fmt_tc(bet)}", color=discord.Color.blurple())

        if reveal:
            d_total,_ = hand_value(st["dealer"])
            dealer_line = " ".join(f"**{r}**" for r,_ in st["dealer"]) + f" (**{d_total}**)"
        else:
            up = st["dealer"][0]
            dealer_line = f"**{up[0]}** and ?"
        e.add_field(name="Dealer's Cards", value=dealer_line, inline=False)

        player_line = " ".join(f"**{r}**" for r,_ in st["player"]) + f" (**{p_total}**)"
        e.add_field(name="Your Cards" if not reveal else "You", value=player_line, inline=False)

        if footer: e.set_footer(text=footer)
        return e

    def files_for(self, st: Dict, *, reveal: bool) -> List[discord.File]:
        files: List[discord.File] = []
        shown = st["dealer"] if reveal else [st["dealer"][0], ("?","?")]
        for i,(r,s) in enumerate(shown):
            path = back_png() if r == "?" else card_png(r,s)
            files.append(discord.File(path, filename=f"dealer_{i}.png"))
        for i,(r,s) in enumerate(st["player"]):
            files.append(discord.File(card_png(r,s), filename=f"player_{i}.png"))
        return files

    async def refresh(self, interaction: discord.Interaction, st: Dict, footer: Optional[str]=None):
        emb = await self.build_embed(st, reveal=False, footer=footer)
        files = self.files_for(st, reveal=False)
        await interaction.response.edit_message(embed=emb, attachments=files, view=st["view"])

    async def finish(self, st: Dict, auto_reason: Optional[str]=None):
        if st["done"]: return
        st["done"] = True
        for child in st["view"].children:
            if isinstance(child, discord.ui.Button): child.disabled = True

        while True:
            d_total, d_soft = hand_value(st["dealer"])
            if d_total < 17 or (d_total == 17 and d_soft):
                st["dealer"].append(st["shoe"].pop())
            else:
                break

        p_total,_ = hand_value(st["player"])
        d_total,_ = hand_value(st["dealer"])
        bet = st["bet"]

        payout = 0
        result = ""
        color = discord.Color.gold()

        if p_total > 21:
            result = f"Dealer wins. You lose {fmt_tc(bet)}."
            color = discord.Color.red()
        elif d_total > 21:
            payout = bet * 2
            result = f"You win! Payout {fmt_tc(payout)}."
            color = discord.Color.green()
        elif is_blackjack(st["player"]) and not is_blackjack(st["dealer"]):
            payout = math.floor(bet * 2.5)
            result = f"Blackjack! Payout {fmt_tc(payout)}."
            color = discord.Color.green()
        elif p_total > d_total:
            payout = bet * 2
            result = f"You win! Payout {fmt_tc(payout)}."
            color = discord.Color.green()
        elif p_total < d_total:
            result = f"Dealer wins. You lose {fmt_tc(bet)}."
            color = discord.Color.red()
        else:
            payout = bet
            result = f"Push. Your bet {fmt_tc(bet)} is returned."
            color = discord.Color.gold()

        if payout:
            try:
                await self.add_cash(st["user_id"], st["guild_id"], payout, "Blackjack payout")
            except Exception as e:
                result += f"\n⚠️ Payout error: {e}"

        # --- Weekly Lottery: award tickets on net-positive winnings (Blackjack) ---
        try:
            net_profit = int(payout) - int(bet)
            if net_profit > 0:
                self.bot.dispatch(
                    "gamble_winnings",
                    st["guild_id"],
                    st["user_id"],
                    net_profit,
                    "Blackjack",
                )
        except Exception:
            pass
        # --- end weekly lottery block ---

        emb = discord.Embed(title="Blackjack — Result", color=color)
        emb.add_field(
            name="Dealer's Cards",
            value=" ".join(f"**{r}**" for r,_ in st["dealer"]) + f" (**{d_total}**)",
            inline=False
        )
        emb.add_field(
            name="You",
            value=" ".join(f"**{r}**" for r,_ in st["player"]) + f" (**{p_total}**)",
            inline=False
        )
        emb.add_field(name="Result", value=result, inline=False)
        if auto_reason: emb.set_footer(text=auto_reason)

        files = self.files_for(st, reveal=True)
        await st["message"].edit(embed=emb, attachments=files, view=st["view"])
        self.states.pop(st["key"], None)

    # ---------- shared logic ----------
    async def _start_blackjack(self, interaction: discord.Interaction, bet: int):
        if interaction.guild_id is None:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if bet <= 0:
            return await interaction.response.send_message(f"Invalid bet. Minimum {fmt_tc(1)}.", ephemeral=True)
        if not self.db:
            return await interaction.response.send_message("Database not ready.", ephemeral=True)

        gid = interaction.guild_id
        uid = interaction.user.id
        key = (gid, uid)

        if key in self.states:
            return await interaction.response.send_message(
                "You already have a Blackjack hand in progress.", ephemeral=True
            )

        async with self.user_locks.setdefault(uid, asyncio.Lock()):
            bal = await self.get_user_balance(uid, gid)
            if bal.cash < bet:
                settings = await self.get_guild_settings(gid)
                return await interaction.response.send_message(
                    f"You don't have enough cash. You have {self.format_currency(bal.cash, settings.currency_symbol)}.",
                    ephemeral=True
                )
            ok = await self.deduct_cash(uid, gid, bet, "Blackjack bet escrow")
            if not ok:
                return await interaction.response.send_message("Failed to place bet. Try again.", ephemeral=True)

        shoe = self.shoe_for(gid)
        player = [shoe.pop(), shoe.pop()]
        dealer = [shoe.pop(), shoe.pop()]

        view = BJView(self, key)
        st = {
            "key": key,
            "guild_id": gid,
            "user_id": uid,
            "bet": bet,
            "player": player,
            "dealer": dealer,
            "shoe": shoe,
            "view": view,
            "done": False,
        }
        self.states[key] = st

        emb = await self.build_embed(st, reveal=False)
        files = self.files_for(st, reveal=False)
        await interaction.response.send_message(embed=emb, files=files, view=view)
        msg = await interaction.original_response()
        st["message"] = msg
        view.message = msg

    # ---------- /blackjack ----------
    @app_commands.command(name="blackjack", description="Play Blackjack with your balance.")
    @app_commands.describe(bet=f"Bet amount in {CURRENCY_EMOTE}")
    @is_admin_or_manager()
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        await self._start_blackjack(interaction, bet)

    # ---------- /bj (alias) ----------
    @app_commands.command(name="bj", description="Play Blackjack (shortcut).")
    @app_commands.describe(bet=f"Bet amount in {CURRENCY_EMOTE}")
    @is_admin_or_manager()
    async def blackjack_alias(self, interaction: discord.Interaction, bet: int):
        await self._start_blackjack(interaction, bet)

async def setup(bot: commands.Bot):
    await bot.add_cog(Blackjack(bot))
