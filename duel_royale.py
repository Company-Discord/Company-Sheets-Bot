# duel_royale.py
# Requires: discord.py >= 2.0
import asyncio
import random
import time
import discord
from discord.ext import commands
from discord import app_commands

# ========= Tunables =========
START_HP = 100
ROUND_DELAY = 1.0              # seconds between narration lines
DUELBET_TIMEOUT = 60           # seconds to accept a /duelbet

# Exodia (special)
EXODIA_IMAGE_URL = "https://i.imgur.com/gXWD1ze.jpeg"
EXODIA_TRIGGER_CHANCE = 0.01   # 1% chance to trigger Exodia
EXODIA_DAMAGE = 1000           # fixed damage; unaffected by multipliers

# Mix probabilities for normal rolls (EXODIA is checked first; ULTRA_BUFF second)
HEAL_CHANCE = 0.15
BUFF_CHANCE = 0.10

# Ultra-rare global buff: 1% chance any turn; next successful action ×1000
ULTRA_BUFF = {
    "name": "divine intervention",
    "chance": 0.01,
    "multiplier": 1000.0
}

# Shared heal: heals self and also heals every opponent for 60% of the self-heal
SHARED_HEAL = {
    "name": "casts Healing Aura",
    "range": (25, 40),
    "chance": 0.65,
    "splash_ratio": 0.60,
    "weight": 0.20,
}

# BOT-ONLY nuke in /duel
GODLIKE_ATTACK_NAME = "GOD SMITE"
GODLIKE_DAMAGE = 1_000_000
BOT_TAUNT = "You queued into divinity. Kneel, mortal—behold **true damage**."

# ========= Move Pools (higher damage) =========
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

HEALS = [
    ("drinks a Health Potion", (15, 25), 0.80),
    ("casts a Healing Spell", (18, 30), 0.70),
    ("uses a Medkit", (20, 35), 0.65),
    ("eats a Red Mushroom", (12, 22), 0.85),
    ("rests at a Bonfire", (25, 40), 0.50),
]

BUFFS = [
    ("focus stance", (1.25, 1.50), 0.85),
    ("adrenaline surge", (1.40, 1.60), 0.75),
    ("battle rhythm", (1.20, 1.40), 0.90),
    ("berserker’s edge", (1.50, 1.75), 0.65),
    ("blessing of vitality", (1.30, 1.60), 0.70),
]

# ========= Helpers =========
def roll_from_pool(pool):
    name, (lo, hi), chance = random.choice(pool)
    success = (random.random() <= chance)
    amount = random.uniform(lo, hi) if success else 0.0
    return name, success, amount

def pick_action():
    # 1) Exodia (1%)
    if random.random() < EXODIA_TRIGGER_CHANCE:
        return {'kind': 'exodia', 'name': "**summon all cards of EXODIA**",
                'success': True, 'amount': EXODIA_DAMAGE, 'shared': False}
    # 2) Global ultra buff (1%)
    if random.random() < ULTRA_BUFF["chance"]:
        return {'kind': 'ultra_buff', 'name': ULTRA_BUFF["name"],
                'success': True, 'amount': ULTRA_BUFF["multiplier"], 'shared': False}
    # 3) Normal decision
    r = random.random()
    if r < BUFF_CHANCE:
        name, success, mult = roll_from_pool(BUFFS)
        return {'kind': 'buff', 'name': name, 'success': success, 'amount': mult, 'shared': False}
    elif r < BUFF_CHANCE + HEAL_CHANCE:
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
    mult = mult_state.get(attacker_id)
    if not mult or base_amount <= 0:
        return int(base_amount), None
    final = int(round(base_amount * mult))
    mult_state.pop(attacker_id, None)
    return final, mult

def fmt_hp(name: str, val: int) -> str:
    return f"{name}: **{val}**" + (" ☠️" if val <= 0 else "")

# ========= Cog =========
class DuelRoyale(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Active users in a live duel/royale
        self.active_players: set[int] = set()
        # Pending /duelbet: target_id -> {'challenger': int, 'message_id': int, 'expires': float}
        self.pending_bets: dict[int, dict] = {}

    # ----- core fight runner -----
    async def _run_duel(self, interaction: discord.Interaction, p1: discord.Member, p2: discord.Member):
        followup = interaction.followup
        names = {p1.id: p1.display_name, p2.id: p2.display_name}
        hp = {p1.id: START_HP, p2.id: START_HP}
        next_multiplier = {}

        await followup.send(f"⚔️ **Duel begins!** {names[p1.id]} vs {names[p2.id]}")
        await followup.send(f"Both fighters start at {START_HP} HP.")

        bot_id = self.bot.user.id
        attacker, defender = p1.id, p2.id
        round_no = 1

        self.active_players.add(p1.id)
        self.active_players.add(p2.id)
        try:
            while hp[attacker] > 0 and hp[defender] > 0:
                if attacker == bot_id:
                    await followup.send(f"🗣️ **{names[attacker]}**: {BOT_TAUNT}")
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

    # ----- Instant /duel -----
    @app_commands.command(name="duel", description="Start a 1v1 duel immediately.")
    @app_commands.describe(opponent="Who do you want to duel?")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        author = interaction.user
        if opponent.id == author.id:
            return await interaction.response.send_message("You can’t duel yourself.", ephemeral=True)
        if opponent.bot and opponent.id != self.bot.user.id:
            return await interaction.response.send_message("You can’t duel that bot.", ephemeral=True)

        # Busy checks (active duels/royales OR pending duelbet)
        if author.id in self.active_players or opponent.id in self.active_players:
            return await interaction.response.send_message("Someone is already in a fight.", ephemeral=True)
        if author.id in self.pending_bets or opponent.id in self.pending_bets:
            return await interaction.response.send_message("Someone has a pending /duelbet.", ephemeral=True)

        await interaction.response.defer(thinking=False)
        await self._run_duel(interaction, author, opponent)

    # ----- Button-based /duelbet (requires accept/decline) -----
    class BetView(discord.ui.View):
        def __init__(self, cog: "DuelRoyale", challenger_id: int, target_id: int, note: str | None):
            super().__init__(timeout=DUELBET_TIMEOUT)
            self.cog = cog
            self.challenger_id = challenger_id
            self.target_id = target_id
            self.note = note

        async def interaction_check(self, itx: discord.Interaction) -> bool:
            # Only the target can press buttons
            if itx.user.id != self.target_id:
                await itx.response.send_message("Only the challenged user can respond.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
        async def accept(self, itx: discord.Interaction, button: discord.ui.Button):
            # Remove pending
            self.cog.pending_bets.pop(self.target_id, None)
            # Busy checks again right before starting
            if self.challenger_id in self.cog.active_players or self.target_id in self.cog.active_players:
                return await itx.response.edit_message(content="Fight can’t start; someone is already busy.", view=None)
            await itx.response.edit_message(content="✅ Bet accepted! Starting duel…", view=None)
            # Start duel
            challenger = itx.guild.get_member(self.challenger_id)
            target = itx.guild.get_member(self.target_id)
            fake_interaction = itx  # reuse followup pipe
            await self.cog._run_duel(fake_interaction, challenger, target)

        @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
        async def decline(self, itx: discord.Interaction, button: discord.ui.Button):
            self.cog.pending_bets.pop(self.target_id, None)
            await itx.response.edit_message(content="❌ Bet declined.", view=None)

        async def on_timeout(self):
            # Clean up if still pending
            self.cog.pending_bets.pop(self.target_id, None)
            # Try to edit the original message if we can
            try:
                for child in self.children:
                    child.disabled = True
            except Exception:
                pass

    @app_commands.command(name="duelbet", description="Challenge someone to a duel that requires their acceptance (with buttons).")
    @app_commands.describe(opponent="Who do you want to challenge?", note="Optional note (e.g., what you're betting)")
    async def duelbet(self, interaction: discord.Interaction, opponent: discord.Member, note: str | None = None):
        author = interaction.user
        if opponent.id == author.id:
            return await interaction.response.send_message("You can’t duel yourself.", ephemeral=True)
        if opponent.bot and opponent.id != self.bot.user.id:
            return await interaction.response.send_message("You can’t duel that bot.", ephemeral=True)

        # Busy checks
        if author.id in self.active_players or opponent.id in self.active_players:
            return await interaction.response.send_message("Someone is already in a fight.", ephemeral=True)
        if author.id in self.pending_bets or opponent.id in self.pending_bets:
            return await interaction.response.send_message("Someone already has a pending /duelbet.", ephemeral=True)

        view = DuelRoyale.BetView(self, author.id, opponent.id, note)
        msg = f"📨 **{author.mention}** challenged {opponent.mention} to a **bet duel**!"
        if note:
            msg += f"  _({note})_"
        await interaction.response.send_message(msg, view=view, allowed_mentions=discord.AllowedMentions(users=True))
        # mark pending
        sent = await interaction.original_response()
        self.pending_bets[opponent.id] = {
            'challenger': author.id,
            'message_id': sent.id,
            'expires': time.time() + DUELBET_TIMEOUT
        }

    # ----- Instant /royale -----
    @app_commands.command(name="royale", description="Start a multi-player battle royale immediately.")
    @app_commands.describe(
        player1="Optional player", player2="Optional player", player3="Optional player",
        player4="Optional player", player5="Optional player", player6="Optional player", player7="Optional player",
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

        # Busy blocks: active fight or pending duelbet
        busy = [m.display_name for m in roster if (m.id in self.active_players or m.id in self.pending_bets)]
        if busy:
            pretty = ", ".join(f"**{n}**" for n in busy)
            return await interaction.response.send_message(
                f"Cannot start Royale. Busy users (duel/royale/pending /duelbet): {pretty}", ephemeral=True
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

        # lock everyone
        for m in roster:
            self.active_players.add(m.id)

        round_no = 1
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
                        l3 = f"{fmt_hp(names[attacker], hp[attacker])}"

                    elif act['kind'] == 'buff':
                        if act['success']:
                            next_multiplier[attacker] = float(act['amount'])
                            l1 = f"{names[attacker]} enters {act['name']}!"
                            l2 = f"Their next move is empowered ×**{act['amount']:.2f}**."
                        else:
                            l1 = f"{names[attacker]} attempts {act['name']}…"
                            l2 = "but it **fails**."
                        l3 = f"{fmt_hp(names[attacker], hp[attacker])}"

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
                            l3 = f"{fmt_hp(names[attacker], hp[attacker])}"
                        else:
                            l1 = f"{names[attacker]} tries to {act['name']}…"
                            l2 = "but it **fails**."
                            l3 = f"{fmt_hp(names[attacker], hp[attacker])}"

                    else:  # attack
                        if act['success']:
                            dmg, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                            hp[defender] = hp[defender] - dmg
                            l1 = f"{names[attacker]} uses {act['name']} on {names[defender]}!"
                            l2 = f"It hits for **{dmg}**!" + (f" (buff ×{consumed:.2f})" if consumed else "")
                        else:
                            l1 = f"{names[attacker]} uses {act['name']} on {names[defender]}!"
                            l2 = "It **misses**!"
                        l3 = f"{fmt_hp(names[defender], hp[defender])}"

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
            for m in roster:
                self.active_players.discard(m.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(DuelRoyale(bot))
