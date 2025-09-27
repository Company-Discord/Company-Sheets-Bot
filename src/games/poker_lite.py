# poker_lite.py
import os
import random
import time
import math
from collections import deque
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

# =================== Import Unified Database ===================
from src.bot.base_cog import BaseCog
from src.utils.utils import is_admin_or_manager

# =================== Config ===================
CURRENCY_EMOTE = os.getenv("CURRENCY_EMOTE", ":TC:")

def fmt_tc(n: int) -> str:
    return f"💰 {n:,}"

# ---------- card assets ----------
RANK_CHAR_MAP = {"10": "T"}  # others already single-char like 2..9,J,Q,K,A
SUIT_CHAR_MAP = {"♠": "S", "♥": "H", "♦": "D", "♣": "C"}

CARD_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "cards"))

# Card emoji mapping (same as blackjack.py)
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

def _rank_char(r: str) -> str:
    return RANK_CHAR_MAP.get(r, r)

def _suit_char(s: str) -> str:
    return SUIT_CHAR_MAP[s]

def _card_png(card: "Card") -> str:
    return os.path.join(CARD_BASE, f"{_rank_char(card.rank)}{_suit_char(card.suit)}.png")

def _back_png() -> str:
    return os.path.join(CARD_BASE, "back.png")


# =================== Cards / Deck ===================
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}  # 2..14
RANK_WORD = {
    2:"Twos",3:"Threes",4:"Fours",5:"Fives",6:"Sixes",7:"Sevens",8:"Eights",
    9:"Nines",10:"Tens",11:"Jacks",12:"Queens",13:"Kings",14:"Aces"
}
RANK_SINGLE = {
    2:"Two",3:"Three",4:"Four",5:"Five",6:"Six",7:"Seven",8:"Eight",
    9:"Nine",10:"Ten",11:"Jack",12:"Queen",13:"King",14:"Ace"
}

@dataclass(frozen=True)
class Card:
    rank: str
    suit: str
    def __str__(self) -> str: return f"{self.rank}{self.suit}"

def new_deck() -> List[Card]:
    return [Card(r, s) for s in SUITS for r in RANKS]

def deal(deck: List[Card], n: int) -> List[Card]:
    return [deck.pop() for _ in range(n)]

# =================== Hand Evaluator ===================
# Returns (class, tiebreakers). Higher tuple wins.
# 8 SF, 7 Quads, 6 FH, 5 Flush, 4 Straight, 3 Trips, 2 Two Pair, 1 One Pair, 0 High
def eval_hand(cards: List[Card]) -> Tuple[int, List[int]]:
    ranks = sorted((RANK_VAL[c.rank] for c in cards), reverse=True)
    suits = [c.suit for c in cards]
    counts: Dict[int, int] = {}
    for v in ranks:
        counts[v] = counts.get(v, 0) + 1
    groups = sorted(((cnt, v) for v, cnt in counts.items()), key=lambda x: (x[0], x[1]), reverse=True)
    is_flush = len(set(suits)) == 1

    unique_ranks = sorted(set(ranks), reverse=True)
    def is_straight(vals: List[int]) -> Tuple[bool, int]:
        if len(vals) < 5: return (False, 0)
        if max(vals) - min(vals) == 4 and len(vals) == 5: return (True, max(vals))
        if set(vals) == {14,5,4,3,2}: return (True, 5)  # wheel
        return (False, 0)

    is_str, top_st = is_straight(unique_ranks)

    if is_flush and is_str: return (8, [top_st])
    if groups[0][0] == 4:
        quad = groups[0][1]; kick = max(v for v in ranks if v != quad)
        return (7, [quad, kick])
    if groups[0][0] == 3 and groups[1][0] >= 2:
        return (6, [groups[0][1], groups[1][1]])
    if is_flush: return (5, sorted(ranks, reverse=True))
    if is_str:   return (4, [top_st])
    if groups[0][0] == 3:
        triple = groups[0][1]
        kickers = sorted([v for v in ranks if v != triple], reverse=True)
        return (3, [triple] + kickers)
    if groups[0][0] == 2 and groups[1][0] == 2:
        pair_hi = max(groups[0][1], groups[1][1])
        pair_lo = min(groups[0][1], groups[1][1])
        kicker = max(v for v in ranks if v != pair_hi and v != pair_lo)
        return (2, [pair_hi, pair_lo, kicker])
    if groups[0][0] == 2:
        pair = groups[0][1]
        kickers = sorted([v for v in ranks if v != pair], reverse=True)
        return (1, [pair] + kickers)
    return (0, sorted(ranks, reverse=True))

HAND_NAMES = {
    8:"Straight Flush",7:"Four of a Kind",6:"Full House",5:"Flush",
    4:"Straight",3:"Three of a Kind",2:"Two Pair",1:"One Pair",0:"High Card"
}

def hand_label(cards: List[Card]) -> str:
    """Human-friendly label like 'One Pair (Sevens)' or 'High Card (Ace)'."""
    cls, tb = eval_hand(cards)
    name = HAND_NAMES[cls]
    if cls == 1:
        return f"{name} ({RANK_WORD[tb[0]]})"
    if cls == 2:
        hi, lo, _ = tb
        return f"{name} ({RANK_WORD[hi]} & {RANK_WORD[lo]})"
    if cls == 3:
        return f"{name} ({RANK_WORD[tb[0]]})"
    if cls in (4, 8):
        hi = tb[0]
        return f"{name} ({'Five' if hi==5 else RANK_SINGLE[hi]}-high)"
    if cls in (5, 0):
        hi = max(RANK_VAL[c.rank] for c in cards)
        return f"{name} ({RANK_SINGLE[hi]}-high)"
    if cls == 7:
        return f"{name} ({RANK_WORD[tb[0]]})"
    return name

# =================== Beginner helpers ===================

def suggested_discards_for_player(cards: List[Card]) -> List[int]:
    """
    Simple heuristic (1-based indices):
    - Keep Two Pair+ (discard none)
    - One Pair: keep pair, discard the other 3
    - 4-to-Flush: discard the off-suit
    - 4-to-Straight (naive): drop 1 card outside the run
    - Otherwise keep highest card, discard up to 3
    """
    cls, _ = eval_hand(cards)
    if cls >= 2:
        return []
    counts: Dict[int, int] = {}
    for c in cards:
        v = RANK_VAL[c.rank]; counts[v] = counts.get(v, 0) + 1
    pair_val = next((v for v, cnt in counts.items() if cnt == 2), None)
    if pair_val:
        return [i+1 for i, c in enumerate(cards) if RANK_VAL[c.rank] != pair_val][:3]
    suit_counts: Dict[str, int] = {}
    for c in cards:
        suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1
    tgt = next((s for s, cnt in suit_counts.items() if cnt == 4), None)
    if tgt:
        return [i+1 for i, c in enumerate(cards) if c.suit != tgt]
    vals = sorted({RANK_VAL[c.rank] for c in cards})
    for start in range(2, 11):
        need = set(range(start, start + 5))
        if len(need - set(vals)) == 1:
            out = [i for i, c in enumerate(cards) if RANK_VAL[c.rank] not in need][:1]
            return [i+1 for i in out]
    keep = max(range(5), key=lambda i: RANK_VAL[cards[i].rank])
    return [i+1 for i in range(5) if i != keep][:3]

def fmt_indices(idxs_1based: List[int]) -> str:
    return "none" if not idxs_1based else ", ".join(str(i) for i in idxs_1based)

# =================== Dealer AI ===================
def dealer_discards(hand: List[Card]) -> List[int]:
    cls, _ = eval_hand(hand)
    if cls >= 2: return []
    counts = {}
    for c in hand:
        v = RANK_VAL[c.rank]; counts[v] = counts.get(v, 0) + 1
    pair_val = next((v for v, cnt in counts.items() if cnt == 2), None)
    if pair_val:
        return [i for i, c in enumerate(hand) if RANK_VAL[c.rank] != pair_val][:3]
    suit_counts: Dict[str, int] = {}
    for c in hand:
        suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1
    tgt = next((s for s, cnt in suit_counts.items() if cnt == 4), None)
    if tgt:
        return [i for i, c in enumerate(hand) if c.suit != tgt]
    vals = sorted({RANK_VAL[c.rank] for c in hand})
    for start in range(2, 11):
        need = set(range(start, start + 5))
        if len(need - set(vals)) == 1:
            return [i for i, c in enumerate(hand) if RANK_VAL[c.rank] not in need][:1]
    keep = max(range(5), key=lambda i: RANK_VAL[hand[i].rank])
    return [i for i in range(5) if i != keep][:3]

# =================== State ===================
class PokerState:
    def __init__(self, user_id: int, bet: int, deck: List[Card]):
        self.user_id = user_id
        self.bet = bet
        self.deck = deck
        self.player = deal(deck, 5)
        self.dealer = deal(deck, 5)
        self.locked = False
        self.done = False
    def player_discard(self, idxs: List[int]):
        for i in sorted(idxs): self.player[i] = self.deck.pop()
    def dealer_draw(self):
        for i in sorted(dealer_discards(self.dealer)): self.dealer[i] = self.deck.pop()
    def showdown(self) -> int:
        a, b = eval_hand(self.player), eval_hand(self.dealer)
        return 1 if a > b else (-1 if a < b else 0)

# =================== UI ===================
class DiscardSelect(discord.ui.Select):
    def __init__(self, cards: List[Card]):
        # Show actual card faces; keep 0–4 as values for internal use
        options = [
            discord.SelectOption(
                label=str(cards[i]),
                value=str(i),
                description=f"Discard card #{i+1}"
            )
            for i in range(5)
        ]
        super().__init__(
            placeholder="Select up to 3 cards to discard…",
            min_values=0,
            max_values=3,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "PokerView" = self.view  # type: ignore
        if interaction.user.id != view.state.user_id:
            return await interaction.response.send_message("This isn’t your hand.", ephemeral=True)
        view.selected = [int(v) for v in self.values]
        await interaction.response.defer()

class PokerView(discord.ui.View):
    def __init__(self, state: PokerState, cog: "PokerLite", timeout: int = 60):
        super().__init__(timeout=timeout)
        self.state = state
        self.cog = cog
        self.selected: List[int] = []
        self.result_text: Optional[str] = None
        self.outcome: int = 0
        self.select = DiscardSelect(state.player)  # show card faces
        self.add_item(self.select)
        self.message: Optional[discord.Message] = None  # set after send

    async def on_timeout(self):
        if not self.state.done:
            try:
                await self.finish(None)
            except:
                pass
        self.stop()  # ensure view.wait() unblocks

    @discord.ui.button(label="Draw & Showdown", style=discord.ButtonStyle.primary)
    async def draw_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.state.user_id:
            return await interaction.response.send_message("This isn’t your hand.", ephemeral=True)
        await self.finish(interaction)

    @discord.ui.button(label="Stand Pat", style=discord.ButtonStyle.secondary)
    async def stand_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.state.user_id:
            return await interaction.response.send_message("This isn’t your hand.", ephemeral=True)
        self.selected = []
        await self.finish(interaction)

    @discord.ui.button(label="Fold", style=discord.ButtonStyle.danger)
    async def fold_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.state.user_id:
            return await interaction.response.send_message("This isn’t your hand.", ephemeral=True)
        if self.state.locked or self.state.done: return await interaction.response.defer()
        self.state.done = True; self.state.locked = True
        self.outcome = -1
        self.clear_items()
        self.result_text = f"**You folded.** You lose {fmt_tc(self.state.bet)}."
        await interaction.response.edit_message(
            view=self,
            embed=self._showdown_embed()
        )
        self.stop()  # stop the view so wait() returns

        # record fold as a loss
        try:
            await self.cog._update_poker_stats(
                guild_id=self.message.guild.id,
                user_id=self.state.user_id,
                bet=self.state.bet,
                outcome=-1
            )
        except Exception:
            pass

    async def finish(self, interaction: Optional[discord.Interaction]):
        if self.state.locked or self.state.done:
            if interaction: await interaction.response.defer()
            return
        self.state.locked = True

        # Draws
        self.state.player_discard(self.selected)
        self.state.dealer_draw()
        outcome = self.state.showdown()
        self.state.done = True
        self.outcome = outcome

        # Payouts (escrow: bet was already debited)
        bet = self.state.bet
        guild_id = self.message.guild.id  
        user_id = self.state.user_id

        try:
            if outcome > 0:
                await self.cog.add_cash(user_id, guild_id, bet * 2, "Poker-Lite win")
                self.result_text = f"**You win!** Payout {fmt_tc(bet * 2)}."
            elif outcome == 0:
                await self.cog.add_cash(user_id, guild_id, bet, "Poker-Lite push")
                self.result_text = f"**Push.** Your bet {fmt_tc(bet)} is returned."
            else:
                self.result_text = f"**Dealer wins.** You lose {fmt_tc(bet)}."
        except Exception as e:
            self.result_text = f"⚠️ Payout error: {e}"

        # --- Weekly Lottery: award tickets on net-positive winnings (Poker-Lite) ---
        try:
            if outcome > 0:
                net_profit = int(bet)  # even-money win => profit == original bet
                if net_profit > 0:
                    self.cog.bot.dispatch(
                        "gamble_winnings",
                        guild_id,
                        user_id,
                        net_profit,
                        "Poker-Lite",
                    )
        except Exception:
            pass
        # --- end weekly lottery block ---

        # Record stats
        try:
            await self.cog._update_poker_stats(
                guild_id=guild_id, user_id=user_id, bet=bet, outcome=outcome
            )
        except Exception:
            pass

        self.clear_items()
        if interaction and not interaction.response.is_done():
            await interaction.response.edit_message(
                view=self,
                embed=self._showdown_embed()
            )
        else:
            if self.message is not None:
                await self.message.edit(
                    view=self,
                    embed=self._showdown_embed()
                )
        self.stop()  # stop the view so wait() returns

    def _showdown_embed(self) -> discord.Embed:
        # Color by outcome: green win, red loss, gold push/fold
        color = discord.Color.gold()
        if self.outcome > 0:
            color = discord.Color.green()
        elif self.outcome < 0:
            color = discord.Color.red()

        e = discord.Embed(title="Poker-Lite — Showdown", color=color)
        e.add_field(
            name=f"Your Hand — {hand_label(self.state.player)}",
            value=self.cog.render_hand_inline(self.state.player),
            inline=False
        )
        e.add_field(
            name=f"Dealer — {hand_label(self.state.dealer)}",
            value=self.cog.render_hand_inline(self.state.dealer),
            inline=False
        )
        e.add_field(name="Bet", value=fmt_tc(self.state.bet))
        if self.result_text:
            e.add_field(name="Result", value=self.result_text, inline=False)
        # e.set_footer(text=self.result_text or "")
        return e

# =================== Cog ===================
class PokerLite(BaseCog):
    """Heads-up 5-card draw vs dealer using unified database, with stats & leaderboard."""
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.active_by_user: Dict[int, int] = {}   # per-user lock only

        # ---- Rate limit (3 games / 60s) ----
        self._starts: Dict[int, deque[float]] = {}
        self._MAX_PER = 3
        self._WINDOW = 60.0

    def format_cards_as_emojis(self, cards: List["Card"]) -> str:
        """Convert card objects to emoji string using BaseCog emoji cache"""
        emoji_cards = []
        for card in cards:
            # Convert card to the format expected by CARD_EMOJIS
            rank_char = _rank_char(card.rank)
            suit_char = _suit_char(card.suit)
            card_key = f"{rank_char}{suit_char}"
            
            # Try to get Discord server emoji from BaseCog cache first, fallback to Unicode emoji
            discord_emoji = self.get_cached_emoji(card_key)
            if discord_emoji:
                emoji_cards.append(discord_emoji)
            else:
                emoji_cards.append(CARD_EMOJIS.get(card_key, '🂠'))
        return " ".join(emoji_cards)

    def render_hand_inline(self, cards: List[Card]) -> str:
        """Clean one-line view for both draw phase and showdown."""
        return self.format_cards_as_emojis(cards)

    # ----- image helpers for sending attachments -----
    def _files_draw_phase(self, state: "PokerState") -> List[discord.File]:
        files: List[discord.File] = []
        for i, c in enumerate(state.player):
            files.append(discord.File(_card_png(c), filename=f"p{i}.png"))
        back = _back_png()
        for i in range(5):
            files.append(discord.File(back, filename=f"d{i}.png"))
        return files

    def _files_showdown(self, state: "PokerState") -> List[discord.File]:
        files: List[discord.File] = []
        for i, c in enumerate(state.player):
            files.append(discord.File(_card_png(c), filename=f"p{i}.png"))
        for i, c in enumerate(state.dealer):
            files.append(discord.File(_card_png(c), filename=f"d{i}.png"))
        return files

    # ----- rate limit helpers -----
    def _rl_deque(self, user_id: int) -> deque:
        dq = self._starts.get(user_id)
        if dq is None:
            dq = deque()
            self._starts[user_id] = dq
        return dq

    def _rate_limit_check_and_mark(self, user_id: int) -> tuple[bool, int]:
        """
        Return (allowed, wait_seconds). If allowed, we also record this start time.
        Limit: self._MAX_PER starts in the past self._WINDOW seconds (rolling).
        """
        now = time.time()
        dq = self._rl_deque(user_id)

        # evict old starts
        while dq and now - dq[0] > self._WINDOW:
            dq.popleft()

        if len(dq) >= self._MAX_PER:
            wait = int(math.ceil(self._WINDOW - (now - dq[0])))
            return (False, max(wait, 1))

        dq.append(now)   # record this start
        return (True, 0)

    # ----- Poker Stats Methods -----
    async def _get_poker_stats(self, guild_id: int, user_id: int) -> Dict:
        """Get poker stats for a user."""
        if not self.db:
            raise RuntimeError("Database not initialized")
        
        async with self.db._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT hands, wins, losses, pushes, wagered, net
                FROM poker_stats
                WHERE guild_id = $1 AND user_id = $2
            """, guild_id, user_id)
            
            if row:
                return {
                    'hands': row['hands'],
                    'wins': row['wins'],
                    'losses': row['losses'],
                    'pushes': row['pushes'],
                    'wagered': row['wagered'],
                    'net': row['net']
                }
            else:
                return {
                    'hands': 0,
                    'wins': 0,
                    'losses': 0,
                    'pushes': 0,
                    'wagered': 0,
                    'net': 0
                }

    async def _update_poker_stats(self, guild_id: int, user_id: int, bet: int, outcome: int):
        """
        outcome: 1=win, 0=push, -1=loss
        net change: +bet / 0 / -bet
        """
        if not self.db:
            raise RuntimeError("Database not initialized")
        
        async with self.db._pool.acquire() as conn:
            # Ensure user exists in poker_stats table
            await conn.execute("""
                INSERT INTO poker_stats (guild_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT(guild_id, user_id) DO NOTHING
            """, guild_id, user_id)
            
            # Update stats
            hands = 1
            wins = 1 if outcome > 0 else 0
            losses = 1 if outcome < 0 else 0
            pushes = 1 if outcome == 0 else 0
            net = bet if outcome > 0 else (-bet if outcome < 0 else 0)
            wager = bet
            
            await conn.execute("""
                UPDATE poker_stats
                SET hands = hands + $1,
                    wins = wins + $2,
                    losses = losses + $3,
                    pushes = pushes + $4,
                    wagered = wagered + $5,
                    net = net + $6
                WHERE guild_id = $7 AND user_id = $8
            """, hands, wins, losses, pushes, wager, net, guild_id, user_id)

    # ----- per-user lock helpers -----
    def _locked(self, user_id: int) -> Optional[str]:
        if user_id in self.active_by_user:
            return "You already have a Poker-Lite hand in progress."
        return None

    def _unlock(self, user_id: int):
        self.active_by_user.pop(user_id, None)

    # ----- Commands -----
    @app_commands.command(name="poker", description="Play Poker-Lite (5-card draw vs dealer).")
    @app_commands.describe(bet=f"Bet amount in 💰")
    @is_admin_or_manager()
    async def poker(self, interaction: discord.Interaction, bet: int):
        """Main game command — bet is required, no max, must be > 0."""
        if interaction.guild_id is None:
            return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)

        # Ensure database is initialized
        if not self.db:
            return await interaction.response.send_message(
                "⚠️ Database not ready. Please try again.", ephemeral=True
            )

        user = interaction.user
        channel = interaction.channel
        if channel is None:
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        msg = self._locked(user.id)
        if msg:
            return await interaction.response.send_message(msg, ephemeral=True)

        if bet <= 0:
            return await interaction.response.send_message(
                f"❌ Invalid bet. You must bet at least {fmt_tc(1)}.",
                ephemeral=True
            )

        # Rate limit: at most 3 games per rolling 60s
        ok, wait_s = self._rate_limit_check_and_mark(interaction.user.id)
        if not ok:
            return await interaction.response.send_message(
                f"⏳ Rate limit: you’ve started **{self._MAX_PER}** Poker-Lite games in the last minute. "
                f"Try again in **{wait_s}s**.",
                ephemeral=True
            )

        # Balance check
        user_balance = await self.get_user_balance(user.id, interaction.guild_id)
        if user_balance.cash < bet:
            settings = await self.get_guild_settings(interaction.guild_id)
            return await interaction.response.send_message(
                f"You don't have enough cash! You have {self.format_currency(user_balance.cash, settings.currency_symbol)}.",
                ephemeral=True
            )

        # Escrow — debit bet
        if not await self.deduct_cash(user.id, interaction.guild_id, bet, "Poker-Lite bet escrow"):
            return await interaction.response.send_message(
                "Failed to place bet. Please try again.", ephemeral=True
            )

        # Start game
        deck = new_deck(); random.shuffle(deck)
        state = PokerState(user.id, bet, deck)

        # Beginner tips
        label = hand_label(state.player)
        sugg = suggested_discards_for_player(state.player)  # 1-based indices
        tips = (
            f"**Hand strength:** {label}\n"
            f"**Suggested discards:** {fmt_indices(sugg)} (optional)\n"
            f"Use the dropdown to select up to 3 cards by face, then press **Draw & Showdown**."
        )

        back_card = self.get_cached_emoji("back")
        e = discord.Embed(title="Poker-Lite — Draw Phase", color=0x3498DB)
        e.add_field(name="Your Hand", value=self.render_hand_inline(state.player), inline=False)
        e.add_field(name="Dealer Hand", value=f"{back_card} {back_card} {back_card} {back_card} {back_card}", inline=False)
        e.add_field(name="Bet", value=fmt_tc(bet))
        e.add_field(name="Tips", value=tips, inline=False)
        e.set_footer(text="You have 60s to act.")

        view = PokerView(state, self, timeout=60)
        await interaction.response.send_message(embed=e, view=view)
        sent = await interaction.original_response()
        self.active_by_user[user.id] = sent.id      # per-user lock only
        view.message = sent                          

        try:
            await view.wait()
        finally:
            self._unlock(user.id)

    @app_commands.command(name="poker_stats", description="Show Poker-Lite lifetime stats for you or another user.")
    @app_commands.describe(user="User to inspect (defaults to you)")
    @is_admin_or_manager()
    async def poker_stats(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if interaction.guild_id is None:
            return await interaction.response.send_message("Server-only command.", ephemeral=True)
        
        if not self.db:
            return await interaction.response.send_message(
                "⚠️ Database not ready. Please try again.", ephemeral=True
            )
        
        uid = (user or interaction.user).id
        stats = await self._get_poker_stats(interaction.guild_id, uid)
        
        if stats['hands'] == 0:
            return await interaction.response.send_message(
                f"📝 No Poker-Lite history for {(user or interaction.user).mention} yet.",
                ephemeral=True
            )
        
        hands = stats['hands']
        wins = stats['wins']
        losses = stats['losses']
        pushes = stats['pushes']
        wagered = stats['wagered']
        net = stats['net']
        
        winrate = (wins / hands * 100) if hands else 0.0
        avg_bet = (wagered / hands) if hands else 0
        emb = discord.Embed(
            title=f"Poker-Lite Stats — {(user or interaction.user).display_name}",
            color=discord.Color.blurple()
        )
        emb.add_field(name="Hands", value=f"{hands}", inline=True)
        emb.add_field(name="Wins / Losses / Pushes", value=f"{wins} / {losses} / {pushes}", inline=True)
        emb.add_field(name="Win Rate", value=f"{winrate:.1f}%", inline=True)
        emb.add_field(name="Total Wagered", value=fmt_tc(wagered), inline=True)
        emb.add_field(name="Net", value=("+" if net>=0 else "") + fmt_tc(net), inline=True)
        emb.add_field(name="Avg Bet", value=fmt_tc(int(avg_bet)), inline=True)
        await interaction.response.send_message(embed=emb, ephemeral=False)

    @app_commands.command(name="poker_leaderboard", description="Show the Poker-Lite leaderboard for this server.")
    @app_commands.describe(
        metric="Rank by 'net' (profit) or 'wins' (default: net)",
        limit="Number of players to show (1–25, default 10)"
    )
    @app_commands.choices(metric=[
        app_commands.Choice(name="net", value="net"),
        app_commands.Choice(name="wins", value="wins")
    ])
    @is_admin_or_manager()
    async def poker_leaderboard(
        self,
        interaction: discord.Interaction,
        metric: Optional[app_commands.Choice[str]] = None,
        limit: Optional[int] = 10
    ):
        if interaction.guild_id is None:
            return await interaction.response.send_message("Server-only command.", ephemeral=True)
        
        if not self.db:
            return await interaction.response.send_message(
                "⚠️ Database not ready. Please try again.", ephemeral=True
            )
        
        limit = max(1, min(int(limit or 10), 25))
        order_col = "net" if (not metric or metric.value == "net") else "wins"
        
        async with self.db._pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT user_id, hands, wins, losses, pushes, wagered, net
                FROM poker_stats
                WHERE guild_id = $1
                ORDER BY {order_col} DESC, wins DESC, hands DESC
                LIMIT $2
            """, interaction.guild_id, limit)
        
        if not rows:
            return await interaction.response.send_message("No Poker-Lite games have been recorded here yet.", ephemeral=True)

        lines = []
        for idx, row in enumerate(rows, start=1):
            uid = row['user_id']
            hands = row['hands']
            wins = row['wins']
            net = row['net']
            mention = f"<@{uid}>"
            if order_col == "net":
                lines.append(f"**{idx}.** {mention} — Net {('+' if net>=0 else '')}{fmt_tc(net)} • Hands {hands}, Wins {wins}")
            else:
                lines.append(f"**{idx}.** {mention} — Wins {wins} • Net {('+' if net>=0 else '')}{fmt_tc(net)} • Hands {hands}")
        title = f"Poker-Lite Leaderboard — {interaction.guild.name} (by {order_col})"
        emb = discord.Embed(title=title, description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=emb, ephemeral=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(PokerLite(bot))
