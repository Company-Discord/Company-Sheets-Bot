# duel_royale.py +
# Requires: discord.py >= 2.0
import asyncio
import random
import time
import discord
from discord.ext import commands
from discord import app_commands

# ========= Tunables =========
START_HP = 100
ROUND_DELAY = 1.0  # seconds between narration lines
CHALLENGE_TIMEOUT = 60  # seconds before a duel request expires

# Exodia (special)
EXODIA_IMAGE_URL = "https://i.imgur.com/gXWD1ze.jpeg"
EXODIA_TRIGGER_CHANCE = 0.01  # 1% chance to trigger Exodia
EXODIA_DAMAGE = 1000          # fixed damage; unaffected by multipliers

# Mix probabilities for normal rolls (EXODIA is checked first; ULTRA_BUFF second)
HEAL_CHANCE = 0.15   # 15% of normal rolls try a heal
BUFF_CHANCE = 0.10   # 10% of normal rolls try a (normal) buff

# Ultra-rare global buff: 1% chance any turn; next successful action ×1000
ULTRA_BUFF = {
    "name": "divine intervention",
    "chance": 0.01,       # 1% GLOBAL, independent of normal buff/heal/attack roll
    "multiplier": 1000.0  # x1000 on next successful attack/heal (not Exodia)
}

# Shared heal: heals self and also heals every opponent for 60% of the self-heal
SHARED_HEAL = {
    "name": "casts Healing Aura",  # shared heal name
    "range": (25, 40),             # heal range before multiplier
    "chance": 0.65,                # success chance
    "splash_ratio": 0.60,          # opponents heal % of the final self-heal
    "weight": 0.20,                # 20% of heal rolls become this shared heal
}

# BOT-ONLY nuke in /duel
GODLIKE_ATTACK_NAME = "GOD SMITE"
GODLIKE_DAMAGE = 1_000_000
BOT_TAUNT = "You queued into divinity. Kneel, mortal—behold **true damage**."

# ========= Move Pools =========
# (Higher damage version)
NORMAL_ATTACKS = [
    ("bar fight haymaker", (20, 34), 0.75),
    ("cheap tequila uppercut", (22, 36), 0.70),
    ("walk of shame kick", (18, 32), 0.80),
    ("toxic ex slap", (16, 30), 0.85),
    ("credit card decline strike", (21, 35), 0.75),
    ("hangover headbutt", (24, 40), 0.65),
    ("midlife crisis spin kick", (26, 46), 0.60),
    ("tax season chokehold", (28, 50), 0.55),
    ("paternity test slam", (25, 42), 0.65),
    ("gas station burrito gut punch", (18, 34), 0.80),

    ("WiFi disconnect strike", (20, 36), 0.75),
    ("Blue Screen of Death kick", (22, 42), 0.70),
    ("404 Not Found jab", (16, 32), 0.85),
    ("Pay-to-Win wallet smack", (24, 44), 0.65),
    ("Patch Notes Nerf hammer", (18, 38), 0.80),
    ("Loot Box sucker punch", (21, 45), 0.70),
    ("Lag Spike headbutt", (22, 40), 0.70),
    ("Controller Disconnect throw", (20, 38), 0.75),
    ("Rage Quit slam", (24, 48), 0.60),
    ("Keyboard Smash flurry", (18, 36), 0.80),

    ("Netflix and Kill elbow", (28, 52), 0.55),
    ("Office chair spin attack", (20, 38), 0.75),
    ("Group Chat left hook", (18, 36), 0.80),
    ("Passive-Aggressive Email blast", (16, 34), 0.85),
    ("Sunday Scaries stomp", (22, 44), 0.70),
    ("Silent Treatment choke", (22, 46), 0.65),
    ("Overdraft Fee jab", (18, 36), 0.80),
    ("Blackout Friday brawl", (24, 46), 0.65),
    ("Spam Call sucker punch", (16, 32), 0.90),
    ("PowerPoint presentation slam", (20, 42), 0.70),
]

# 5 iconic game-related heals
HEALS = [
    ("drinks a Health Potion", (15, 25), 0.80),   # classic RPG
    ("casts a Healing Spell", (18, 30), 0.70),    # fantasy spell
    ("uses a Medkit", (20, 35), 0.65),            # shooter staple
    ("eats a Red Mushroom", (12, 22), 0.85),      # platformer vibe
    ("rests at a Bonfire", (25, 40), 0.50),       # soulslike
]

# Normal buffs: apply a multiplier to the user's NEXT successful attack or heal (not Exodia)
BUFFS = [
    ("focus stance", (1.25, 1.50), 0.85),
    ("adrenaline surge", (1.40, 1.60), 0.75),
    ("battle rhythm", (1.20, 1.40), 0.90),
    ("berserker’s edge", (1.50, 1.75), 0.65),
    ("blessing of vitality", (1.30, 1.60), 0.70),
]

# ========= Helpers =========
def roll_from_pool(pool):
    """Pick (name, value_range, chance) and resolve success & magnitude."""
    name, (lo, hi), chance = random.choice(pool)
    success = (random.random() <= chance)
    amount = random.uniform(lo, hi) if success else 0.0
    return name, success, amount

def pick_action():
    """
    Decide the action for this turn.
    Returns a dict with keys:
      kind ('exodia'|'ultra_buff'|'buff'|'heal'|'attack'), name, success, amount, shared
    """
    # 1) Exodia (exact 1%)
    if random.random() < EXODIA_TRIGGER_CHANCE:
        return {'kind': 'exodia', 'name': "**summon all cards of EXODIA**",
                'success': True, 'amount': EXODIA_DAMAGE, 'shared': False}

    # 2) Global ultra-buff (exact 1% each turn)
    if random.random() < ULTRA_BUFF["chance"]:
        return {'kind': 'ultra_buff', 'name': ULTRA_BUFF["name"],
                'success': True, 'amount': ULTRA_BUFF["multiplier"], 'shared': False}

    # 3) Otherwise proceed with normal roll between buff/heal/attack
    r = random.random()
    if r < BUFF_CHANCE:
        name, success, mult = roll_from_pool(BUFFS)
        return {'kind': 'buff', 'name': name, 'success': success, 'amount': mult, 'shared': False}

    elif r < BUFF_CHANCE + HEAL_CHANCE:
        # Decide between normal heal and shared heal
        if random.random() < SHARED_HEAL["weight"]:
            lo, hi = SHARED_HEAL["range"]
            success = (random.random() <= SHARED_HEAL["chance"])
            heal = random.randint(lo, hi) if success else 0
            return {'kind': 'heal', 'name': SHARED_HEAL["name"], 'success': success,
                    'amount': int(heal), 'shared': True}
        else:
            name, success, heal = roll_from_pool(HEALS)
            return {'kind': 'heal', 'name': name, 'success': success,
                    'amount': int(round(heal)), 'shared': False}

    else:
        name, success, dmg = roll_from_pool(NORMAL_ATTACKS)
        return {'kind': 'attack', 'name': name, 'success': success,
                'amount': int(round(dmg)), 'shared': False}

def apply_multiplier_if_any(mult_state, attacker_id, base_amount):
    """
    If attacker has a stored multiplier, apply it and clear it.
    Returns (final_amount, consumed_mult or None).
    Only applies to positive base_amount (i.e., successful damage/heal).
    """
    mult = mult_state.get(attacker_id)
    if not mult or base_amount <= 0:
        return int(base_amount), None
    final = int(round(base_amount * mult))
    mult_state.pop(attacker_id, None)
    return final, mult

def fmt_hp(name: str, val: int) -> str:
    """Pretty HP display with KO marker when <= 0."""
    return f"{name}: **{val}**" + (" ☠️" if val <= 0 else "")

# ========= Cog =========
class DuelRoyale(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Concurrency/state
        self.active_players: set[int] = set()        # users in any active duel/royale
        self.pending_by_target: dict[int, dict] = {} # target_id -> pending request data
        self.pending_by_challenger: dict[int, int] = {} # challenger_id -> target_id

    # ----- Internal state helpers -----
    def _is_busy(self, user_id: int) -> bool:
        """True if user is in an active duel/royale or has an open (sent/received) duel request."""
        return (
            user_id in self.active_players or
            user_id in self.pending_by_target or
            user_id in self.pending_by_challenger
        )

    def _expire_if_needed(self, user_id: int):
        """Expire target's pending request if timed out."""
        data = self.pending_by_target.get(user_id)
        if not data:
            return
        if time.time() >= data['expires']:
            ch = data['challenger']
            self.pending_by_target.pop(user_id, None)
            if self.pending_by_challenger.get(ch) == user_id:
                self.pending_by_challenger.pop(ch, None)

    async def _start_duel_runtime(self, interaction: discord.Interaction, p1: discord.Member, p2: discord.Member):
        """Runs a locked 1v1 duel with all features."""
        followup = interaction.followup

        names = {p1.id: p1.display_name, p2.id: p2.display_name}
        hp = {p1.id: START_HP, p2.id: START_HP}
        next_multiplier = {}

        await followup.send(f"⚔️ **Duel begins!** {names[p1.id]} vs {names[p2.id]}")
        await followup.send(f"Both fighters start at {START_HP} HP.")

        bot_id = self.bot.user.id
        attacker, defender = p1.id, p2.id
        round_no = 1

        # lock participants
        self.active_players.add(p1.id)
        self.active_players.add(p2.id)
        try:
            while hp[attacker] > 0 and hp[defender] > 0:
                # Bot-only GOD SMITE
                if attacker == bot_id:
                    await followup.send(f"🗣️ **{names[attacker]}**: You queued into divinity. Kneel, mortal—behold **true damage**.")
                    act = {'kind': 'attack','name': GODLIKE_ATTACK_NAME,'success': True,'amount': GODLIKE_DAMAGE,'shared': False}
                else:
                    act = pick_action()

                header = f"__Round {round_no}__ — **{names[attacker]}** uses {act['name']}!"

                if act['kind'] == 'exodia':
                    embed = discord.Embed(title="💀 EXODIA OBLITERATE!!! 💀",
                                          description=f"{names[attacker]} unleashes the forbidden one!",
                                          color=discord.Color.dark_red())
                    embed.set_image(url=EXODIA_IMAGE_URL)
                    await followup.send(embed=embed)
                    hp[defender] = hp[defender] - EXODIA_DAMAGE
                    body = f"It deals **{EXODIA_DAMAGE}** damage!"

                elif act['kind'] == 'ultra_buff':
                    next_multiplier[attacker] = float(act['amount'])
                    body = f"{names[attacker]} is blessed with **{act['name']}**! Next move ×{act['amount']:.0f}!"

                elif act['kind'] == 'buff':
                    if act['success']:
                        next_multiplier[attacker] = float(act['amount'])
                        body = f"{names[attacker]}'s next move is empowered ×**{act['amount']:.2f}**!"
                    else:
                        body = f"{names[attacker]}'s attempt to power up **fails**."

                elif act['kind'] == 'heal':
                    if act['success']:
                        heal_amount, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                        hp[attacker] = hp[attacker] + heal_amount
                        suff = f" (buff ×{consumed:.2f})" if consumed else ""
                        extra = ""
                        if act.get('shared'):
                            splash = int(round(heal_amount * SHARED_HEAL["splash_ratio"]))
                            hp[defender] = hp[defender] + splash
                            extra = f" | {names[defender]} also heals **{splash} HP**."
                        body = f"Restores **{heal_amount} HP**{suff}.{extra}"
                    else:
                        body = "…but the recovery **fails**!"

                else:  # attack
                    if act['success']:
                        dmg, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                        hp[defender] = hp[defender] - dmg
                        suff = f" (buff ×{consumed:.2f})" if consumed else ""
                        body = f"Hit for **{dmg}** damage{suff}."
                    else:
                        body = "…but it **misses**!"

                bars = f"HP — {fmt_hp(names[p1.id], hp[p1.id])} | {fmt_hp(names[p2.id], hp[p2.id])}"
                await followup.send(header)
                await followup.send(body)
                await followup.send(bars)
                await asyncio.sleep(ROUND_DELAY)

                attacker, defender = defender, attacker
                round_no += 1

            winner_id = attacker if hp[attacker] > 0 else defender
            await followup.send(f"🏆 **{names[winner_id]}** wins the duel!")
        finally:
            self.active_players.discard(p1.id)
            self.active_players.discard(p2.id)

    async def narrate(self, followup: discord.Webhook, lines: list[str]):
        for line in lines:
            await followup.send(line, allowed_mentions=discord.AllowedMentions.none())
            await asyncio.sleep(ROUND_DELAY)

    # -------- /duel (creates a challenge) --------
    @app_commands.command(name="duel", description="Challenge someone to a 1v1 duel (they must accept).")
    @app_commands.describe(opponent="Who do you want to challenge?")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        author = interaction.user

        if opponent.id == author.id:
            return await interaction.response.send_message("You can’t duel yourself.", ephemeral=True)
        if opponent.bot and opponent.id != self.bot.user.id:
            return await interaction.response.send_message("You can’t duel that bot.", ephemeral=True)

        # Expire stale pendings
        self._expire_if_needed(author.id)
        self._expire_if_needed(opponent.id)

        # Busy checks (block also for Royale participation)
        if self._is_busy(author.id):
            return await interaction.response.send_message(
                "You already have an active duel/royale or a pending duel request. Finish or cancel it first.",
                ephemeral=True
            )
        if self._is_busy(opponent.id):
            return await interaction.response.send_message(
                f"{opponent.display_name} is already in a duel/royale or has a pending duel request.",
                ephemeral=True
            )

        # Create pending challenge
        now = time.time()
        self.pending_by_target[opponent.id] = {
            'challenger': author.id,
            'guild': interaction.guild_id,
            'channel': interaction.channel_id,
            'expires': now + CHALLENGE_TIMEOUT
        }
        self.pending_by_challenger[author.id] = opponent.id

        await interaction.response.send_message(
            f"📨 **Challenge sent!** {opponent.mention}, type `/duel_accept` to accept or `/duel_decline` to decline "
            f"(expires in {CHALLENGE_TIMEOUT}s).",
            allowed_mentions=discord.AllowedMentions(users=True)
        )

    # -------- /duel_accept --------
    @app_commands.command(name="duel_accept", description="Accept your pending duel challenge.")
    async def duel_accept(self, interaction: discord.Interaction):
        target = interaction.user
        self._expire_if_needed(target.id)
        data = self.pending_by_target.get(target.id)
        if not data:
            return await interaction.response.send_message("You have no pending duel requests.", ephemeral=True)

        if data['guild'] != interaction.guild_id or data['channel'] != interaction.channel_id:
            return await interaction.response.send_message("This request was not created in this channel/server.", ephemeral=True)

        challenger_id = data['challenger']

        # If either party got busy (duel/royale/pending), bail
        if self._is_busy(challenger_id) and self.pending_by_challenger.get(challenger_id) != target.id:
            self.pending_by_target.pop(target.id, None)
            if self.pending_by_challenger.get(challenger_id) == target.id:
                self.pending_by_challenger.pop(challenger_id, None)
            return await interaction.response.send_message("The challenge is no longer valid.", ephemeral=True)
        if self._is_busy(target.id):
            # (Shouldn’t happen since we're looking at their own pending, but be safe)
            return await interaction.response.send_message("You’re currently busy.", ephemeral=True)

        challenger = interaction.guild.get_member(challenger_id)
        if not challenger:
            self.pending_by_target.pop(target.id, None)
            self.pending_by_challenger.pop(challenger_id, None)
            return await interaction.response.send_message("Challenger is no longer here.", ephemeral=True)

        # Clear pending, start duel runtime
        self.pending_by_target.pop(target.id, None)
        self.pending_by_challenger.pop(challenger_id, None)

        await interaction.response.defer(thinking=False)
        await self._start_duel_runtime(interaction, challenger, target)

    # -------- /duel_decline --------
    @app_commands.command(name="duel_decline", description="Decline your pending duel challenge.")
    async def duel_decline(self, interaction: discord.Interaction):
        target = interaction.user
        self._expire_if_needed(target.id)
        data = self.pending_by_target.get(target.id)
        if not data:
            return await interaction.response.send_message("You have no pending duel requests.", ephemeral=True)

        challenger_id = data['challenger']
        self.pending_by_target.pop(target.id, None)
        if self.pending_by_challenger.get(challenger_id) == target.id:
            self.pending_by_challenger.pop(challenger_id, None)

        await interaction.response.send_message("You declined the duel request.")

    # -------- /royale (now also blocked by busy-state and locks participants) --------
    @app_commands.command(name="royale", description="Start a multi-player battle royale (blocked if anyone is busy).")
    @app_commands.describe(
        player1="Optional player", player2="Optional player", player3="Optional player",
        player4="Optional player", player5="Optional player", player6="Optional player",
        player7="Optional player",
    )
    async def royale(
        self,
        interaction: discord.Interaction,
        player1: discord.Member | None = None,
        player2: discord.Member | None = None,
        player3: discord.Member | None = None,
        player4: discord.Member | None = None,
        player5: discord.Member | None = None,
        player6: discord.Member | None = None,
        player7: discord.Member | None = None,
    ):
        author = interaction.user
        candidates = [author, player1, player2, player3, player4, player5, player6, player7]
        roster: list[discord.Member] = []
        seen = set()

        for m in candidates:
            if m and not m.bot and m.id not in seen:
                seen.add(m.id)
                roster.append(m)

        if len(roster) < 2:
            return await interaction.response.send_message(
                "You need at least 2 human players. Add folks with the options (author auto-included).",
                ephemeral=True
            )

        # Busy checks for Royale: block if ANY participant is busy (active duel/royale or pending duel request)
        busy_users = [m.display_name for m in roster if self._is_busy(m.id)]
        if busy_users:
            pretty = ", ".join(f"**{n}**" for n in busy_users)
            return await interaction.response.send_message(
                f"Cannot start Royale. These users are busy (duel/royale/pending request): {pretty}",
                ephemeral=True
            )

        await interaction.response.defer(thinking=False)
        followup = interaction.followup

        names = {m.id: m.display_name for m in roster}
        hp = {m.id: START_HP for m in roster}
        alive = [m.id for m in roster]
        next_multiplier = {}

        await self.narrate(followup, [
            f"👑 **Battle Royale begins!** ({len(roster)} players)",
            ", ".join(f"**{m.display_name}**" for m in roster),
            f"All start at {START_HP} HP. Last one standing wins!"
        ])

        # lock everyone for the duration of the Royale
        for m in roster:
            self.active_players.add(m.id)

        round_no = 1
        def fmt(name, pid): return fmt_hp(name, hp[pid])

        try:
            while len(alive) > 1:
                await followup.send(f"— **Round {round_no}** —")
                random.shuffle(alive)

                for attacker in list(alive):
                    if attacker not in alive:
                        continue
                    targets = [pid for pid in alive if pid != attacker]
                    if not targets:
                        break
                    defender = random.choice(targets)

                    act = pick_action()

                    if act['kind'] == 'exodia':
                        embed = discord.Embed(
                            title="💀 EXODIA OBLITERATE!!! 💀",
                            description=f"**{names[attacker]}** summons the forbidden one and wipes the arena!",
                            color=discord.Color.dark_red()
                        )
                        embed.set_image(url=EXODIA_IMAGE_URL)
                        await followup.send(embed=embed)

                        for pid in list(alive):
                            if pid != attacker:
                                hp[pid] = hp[pid] - EXODIA_DAMAGE
                        eliminated_names = [names[pid] for pid in alive if pid != attacker]
                        if eliminated_names:
                            await followup.send("💥 " + ", ".join(f"**{n}**" for n in eliminated_names) + " are obliterated!")
                        alive = [attacker]
                        break

                    elif act['kind'] == 'ultra_buff':
                        next_multiplier[attacker] = float(act['amount'])
                        l1 = f"{names[attacker]} is blessed with **{act['name']}**!"
                        l2 = f"Next move ×{act['amount']:.0f}."
                        l3 = f"{fmt(names[attacker], attacker)}"

                    elif act['kind'] == 'buff':
                        if act['success']:
                            next_multiplier[attacker] = float(act['amount'])
                            l1 = f"{names[attacker]} enters {act['name']}!"
                            l2 = f"Their next move is empowered ×**{act['amount']:.2f}**."
                        else:
                            l1 = f"{names[attacker]} attempts {act['name']}…"
                            l2 = "but it **fails**."
                        l3 = f"{fmt(names[attacker], attacker)}"

                    elif act['kind'] == 'heal':
                        if act['success']:
                            heal, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                            hp[attacker] = hp[attacker] + heal
                            if act.get('shared'):
                                splash = int(round(heal * SHARED_HEAL["splash_ratio"]))
                                for pid in alive:
                                    if pid != attacker:
                                        hp[pid] = hp[pid] + splash
                                l1 = f"{names[attacker]} {act['name']}!"
                                l2 = f"Restores **{heal} HP** to self" + (f" (buff ×{consumed:.2f})" if consumed else "")
                                l2 += f" and **{splash} HP** to everyone else!"
                            else:
                                l1 = f"{names[attacker]} {act['name']}!"
                                l2 = f"Restores **{heal} HP**" + (f" (buff ×{consumed:.2f})" if consumed else "")
                            l3 = f"{fmt(names[attacker], attacker)}"
                        else:
                            l1 = f"{names[attacker]} tries to {act['name']}…"
                            l2 = "but it **fails**."
                            l3 = f"{fmt(names[attacker], attacker)}"

                    else:  # attack
                        if act['success']:
                            dmg, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                            hp[defender] = hp[defender] - dmg
                            l1 = f"{names[attacker]} uses {act['name']} on {names[defender]}!"
                            l2 = f"It hits for **{dmg}**!" + (f" (buff ×{consumed:.2f})" if consumed else "")
                        else:
                            l1 = f"{names[attacker]} uses {act['name']} on {names[defender]}!"
                            l2 = "It **misses**!"
                        l3 = f"{fmt(names[defender], defender)}"

                    await self.narrate(followup, [l1, l2, l3])

                    if hp[defender] <= 0 and defender in alive:
                        alive.remove(defender)
                        await followup.send(f"💀 **{names[defender]}** has been eliminated! ({len(alive)} remaining)")
                    await asyncio.sleep(ROUND_DELAY)

                if len(alive) == 1:
                    break

                round_no += 1

            winner_id = alive[0]
            await followup.send(f"🏆 **{names[winner_id]}** wins the Royale!")
        finally:
            # unlock everyone
            for m in roster:
                self.active_players.discard(m.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(DuelRoyale(bot))
