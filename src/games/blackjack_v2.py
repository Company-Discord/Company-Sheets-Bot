#
#  src/games/blackjack.py
import os, random, math, asyncio, tempfile, io
from typing import List, Tuple, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

# ---- shared infra ----
from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager, render_hand

CURRENCY_EMOTE = os.getenv("CURRENCY_EMOTE", ":TC:")

def fmt_tc(n: int) -> str:
    return f"{CURRENCY_EMOTE} {n:,}"

# ---------- card assets ----------
RANKS = ["A","2","3","4","5","6","7","8","9","T","J","Q","K"]
SUITS = ["S","H","D","C"]

CARD_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "cards"))

def card_png(rank: str, suit: str) -> str:
    """Get the full path to a card PNG file"""
    return os.path.join(CARD_BASE, f"{rank}{suit}.png")

def back_png() -> str:
    """Get the full path to the back card PNG file"""
    return os.path.join(CARD_BASE, "back.png")

# Card emoji mapping
CARD_EMOJIS = {
    # Hearts (Red)
    "AH": "🂱", "2H": "🂲", "3H": "🂳", "4H": "🂴", "5H": "🂵", 
    "6H": "🂶", "7H": "🂷", "8H": "🂸", "9H": "🂹", "TH": "🂺", 
    "JH": "🂻", "QH": "🂽", "KH": "🂾",
    
    # Diamonds (Red) 
    "AD": "🃁", "2D": "🃂", "3D": "🃃", "4D": "🃄", "5D": "🃅",
    "6D": "🃆", "7D": "🃇", "8D": "🃈", "9D": "🃉", "TD": "🃊",
    "JD": "🃋", "QD": "🃍", "KD": "🃎",
    
    # Clubs (Black)
    "AC": "🃑", "2C": "🃒", "3C": "🃓", "4C": "🃔", "5C": "🃕",
    "6C": "🃖", "7C": "🃗", "8C": "🃘", "9C": "🃙", "TC": "🃚",
    "JC": "🃛", "QC": "🃝", "KC": "🃞",
    
    # Spades (Black)
    "AS": "🂡", "2S": "🂢", "3S": "🂣", "4S": "🂤", "5S": "🂥",
    "6S": "🂦", "7S": "🂧", "8S": "🂨", "9S": "🂩", "TS": "🂪",
    "JS": "🂫", "QS": "🂭", "KS": "🂮",
    
    # Special cards
    "back": "🂠"  # Card back for hidden dealer cards
}



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
    def __init__(self, cog: "BlackjackV2", key: Tuple[int,int], timeout: int = 120):
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
class BlackjackV2(BaseCog):
    """Blackjack using your unified currency system (no negative balances)."""
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        # _assert_assets()
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


    def format_hand_display(self, cards: List[Tuple[str,str]], show_hidden: bool = True) -> str:
        """Format a hand display text (for embed fields)"""
        if show_hidden:
            total, _ = hand_value(cards)
            return f"**{total}**"
        else:
            return "?"

    def create_card_files(self, st: Dict, *, reveal: bool) -> List[discord.File]:
        """Create rendered card images as Discord files using render_hand"""
        files: List[discord.File] = []
        
        # Create temporary files for the rendered images
        with tempfile.TemporaryDirectory() as temp_dir:
            dealer_path = os.path.join(temp_dir, "dealer.png")
            player_path = os.path.join(temp_dir, "player.png")
            
            # Dealer cards
            dealer_card_paths = [card_png(r, s) for (r, s) in st["dealer"]]
            render_hand(
                dealer_card_paths,
                dealer_path,
                show_all=reveal,
                back_path=back_png(),
                angle_step=4,
                overlap_px=45,
                scale=0.2
            )
            # Read the file content into memory before the temp directory is cleaned up
            with open(dealer_path, 'rb') as f:
                dealer_data = f.read()
            files.append(discord.File(io.BytesIO(dealer_data), filename="dealer.png"))
            
            # Player cards
            player_card_paths = [card_png(r, s) for (r, s) in st["player"]]
            render_hand(
                player_card_paths,
                player_path,
                show_all=True,
                angle_step=4,
                overlap_px=45,
                scale=0.2
            )
            # Read the file content into memory before the temp directory is cleaned up
            with open(player_path, 'rb') as f:
                player_data = f.read()
            files.append(discord.File(io.BytesIO(player_data), filename="player.png"))
        
        return files

    def build_dealer_embed(self, st: Dict, *, reveal: bool, footer: Optional[str]=None) -> discord.Embed:
        """Build embed for dealer cards"""
        bet = st["bet"]
        d_total,_ = hand_value(st["dealer"])
        
        if reveal:
            dealer_line = self.format_hand_display(st["dealer"], show_hidden=True)
            title = f"Dealer's Hand — {dealer_line}"
            color = discord.Color.green() if d_total == 21 else discord.Color.blue()
        else:
            dealer_line = self.format_hand_display(st["dealer"], show_hidden=False) + " (?)"
            title = f"Dealer's Hand — {dealer_line}"
            color = discord.Color.blue()
        
        e = discord.Embed(title=title, color=color)
        
        # Add card information as text since we can't update attachments
        if reveal:
            card_names = [f"{r}{s}" for (r, s) in st["dealer"]]
            e.add_field(name="Cards", value=" • ".join(card_names), inline=False)
        else:
            first_card = f"{st['dealer'][0][0]}{st['dealer'][0][1]}"
            e.add_field(name="Cards", value=f"{first_card} • [Hidden]", inline=False)
        
        if footer: e.set_footer(text=footer)
        return e

    def build_player_embed(self, st: Dict, *, footer: Optional[str]=None) -> discord.Embed:
        """Build embed for player cards"""
        bet = st["bet"]
        p_total,_ = hand_value(st["player"])
        player_line = self.format_hand_display(st["player"], show_hidden=True)
        
        # Determine color based on hand value
        if p_total > 21:
            color = discord.Color.red()
            status = "BUST!"
        elif p_total == 21:
            color = discord.Color.green()
            status = "BLACKJACK!"
        else:
            color = discord.Color.blue()
            status = "Playing..."
        
        title = f"Your Hand — {player_line} ({status})"
        e = discord.Embed(title=title, color=color)
        
        # Add card information as text since we can't update attachments
        card_names = [f"{r}{s}" for (r, s) in st["player"]]
        e.add_field(name="Cards", value=" • ".join(card_names), inline=False)
        
        if footer: e.set_footer(text=footer)
        return e


    async def refresh(self, interaction: discord.Interaction, st: Dict, footer: Optional[str]=None):
        dealer_emb = self.build_dealer_embed(st, reveal=False, footer=footer)
        player_emb = self.build_player_embed(st, footer=footer)
        
        # Edit existing messages (without files - Discord doesn't support editing attachments)
        await st["dealer_message"].edit(embed=dealer_emb)
        await st["player_message"].edit(embed=player_emb, view=st["view"])
        
        # Defer the interaction to prevent timeout
        await interaction.response.defer()

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

        # Create final result embeds
        dealer_emb = self.build_dealer_embed(st, reveal=True, footer=f"Final Result: {result}")
        player_emb = self.build_player_embed(st, footer=f"Final Result: {result}")
        
        # Update colors based on result
        if "win" in result.lower():
            dealer_emb.color = discord.Color.red()
            player_emb.color = discord.Color.green()
        elif "lose" in result.lower():
            dealer_emb.color = discord.Color.green()
            player_emb.color = discord.Color.red()
        else:
            dealer_emb.color = discord.Color.gold()
            player_emb.color = discord.Color.gold()

        files = self.create_card_files(st, reveal=True)
        
        # Edit the original messages with final results (without files - Discord doesn't support editing attachments)
        await st["dealer_message"].edit(embed=dealer_emb)
        await st["player_message"].edit(embed=player_emb, view=st["view"])
        
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

        dealer_emb = self.build_dealer_embed(st, reveal=False)
        player_emb = self.build_player_embed(st)
        files = self.create_card_files(st, reveal=False)
        
        # Send dealer embed first
        await interaction.response.send_message(embed=dealer_emb, files=[f for f in files if f.filename == "dealer.png"])
        dealer_msg = await interaction.original_response()
        
        # Send player embed with controls
        player_msg = await interaction.followup.send(embed=player_emb, files=[f for f in files if f.filename == "player.png"], view=view)
        
        # Store both message references
        st["dealer_message"] = dealer_msg
        st["player_message"] = player_msg
        st["message"] = player_msg  # Keep for compatibility
        view.message = player_msg

    # ---------- /blackjack ----------
    @app_commands.command(name="blackjackv2", description="Play Blackjack with your balance.")
    @app_commands.describe(bet=f"Bet amount in {CURRENCY_EMOTE}")
    @is_admin_or_manager()
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        await self._start_blackjack(interaction, bet)

    # ---------- /bj (alias) ----------
    @app_commands.command(name="bjv2", description="Play Blackjack (shortcut).")
    @app_commands.describe(bet=f"Bet amount in {CURRENCY_EMOTE}")
    @is_admin_or_manager()
    async def blackjack_alias(self, interaction: discord.Interaction, bet: int):
        await self._start_blackjack(interaction, bet)

async def setup(bot: commands.Bot):
    await bot.add_cog(BlackjackV2(bot))
