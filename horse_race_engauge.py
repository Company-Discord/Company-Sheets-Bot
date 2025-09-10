import asyncio
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# ===================== Currency formatting =========================
def get_currency_emoji() -> str:
    # Accept Unicode (💰) or custom "<:name:id>". If blank, default to 💰.
    raw = (os.getenv("CURRENCY_EMOJI") or "").strip()
    return raw if raw else "💰"

def fmt_amt(n: int) -> str:
    return f"{get_currency_emoji()} {n:,}"

# ===================== Transaction Logger ==========================
class TransactionLogger:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.path = os.getenv("TRANSACTION_LOG_PATH", "transactions.jsonl")
        ch = (os.getenv("RACE_LOG_CHANNEL_ID") or "").strip()
        self.log_channel_id: Optional[int] = int(ch) if ch.isdigit() else None

    async def log(self, guild_id: int, channel_id: int, kind: str, payload: dict):
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "guild_id": str(guild_id) if guild_id else None,
            "channel_id": str(channel_id) if channel_id else None,
            "type": kind,
            **payload,
        }
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

        if self.log_channel_id:
            try:
                ch = self.bot.get_channel(self.log_channel_id) or await self.bot.fetch_channel(self.log_channel_id)
                if isinstance(ch, discord.TextChannel):
                    await ch.send(embed=self._pretty_embed(kind, event))
            except Exception:
                pass

    def _pretty_embed(self, kind: str, e: dict) -> discord.Embed:
        color = {
            "bet_placed": discord.Color.gold(),
            "payout": discord.Color.green(),
            "refund": discord.Color.orange(),
            "race_start": discord.Color.blurple(),
            "race_end": discord.Color.dark_teal(),
        }.get(kind, discord.Color.greyple())
        em = discord.Embed(title=f"Race Log • {kind}", color=color, timestamp=datetime.now(timezone.utc))
        for k in ["user_id", "username", "horse_idx", "horse_name", "amount",
                  "balance_after", "pot", "prize_pool", "rake", "winning_horse"]:
            if k in e:
                v = e[k]
                if k in ("amount", "pot", "prize_pool", "rake", "balance_after"):
                    v = fmt_amt(int(v))
                em.add_field(name=k, value=str(v), inline=True)
        if "bets" in e and isinstance(e["bets"], list):
            em.add_field(name="bets", value="\n".join(e["bets"])[:1000] or "—", inline=False)
        return em

# ===================== Engauge Wallet ==============================
class EngaugeWallet:
    def __init__(self):
        self.token = (os.getenv("ENGAUGE_TOKEN") or "").strip()
        self.server_id = (os.getenv("ENGAUGE_SERVER_ID") or "").strip()
        self.base = (os.getenv("ENGAUGE_API_BASE") or "https://engau.ge").rstrip("/")
        if not self.token or not self.server_id:
            raise RuntimeError("ENGAUGE_TOKEN and ENGAUGE_SERVER_ID must be set.")
        self._session: Optional[aiohttp.ClientSession] = None

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                raise_for_status=False,
                timeout=aiohttp.ClientTimeout(total=12),
            )
        return self._session

    def _member_url(self, user_id: int) -> str:
        return f"{self.base}/api/v1/servers/{self.server_id}/members/{user_id}"

    async def _json_or_text(self, r: aiohttp.ClientResponse):
        ct = (r.headers.get("Content-Type") or "").lower()
        if "application/json" in ct:
            return await r.json()
        return {"_text": (await r.text())}

    async def get_balance(self, user_id: int) -> int:
        s = await self.session()
        async with s.get(self._member_url(user_id)) as r:
            if r.status == 404:
                return 0
            data = await self._json_or_text(r)
            if r.status != 200:
                msg = data.get("message") if isinstance(data, dict) else str(data)
                raise RuntimeError(f"Engauge GET {r.status}: {msg}")
            return int(data.get("currency", 0))

    async def credit(self, user_id: int, amount: int) -> int:
        if amount < 0:
            raise ValueError("credit amount must be >= 0")
        s = await self.session()
        url = f"{self._member_url(user_id)}/currency"

        # Try query param
        async with s.post(url, params={"amount": str(amount)}) as r:
            data = await self._json_or_text(r)
            if r.status == 200:
                return int(data.get("currency", 0))
        # Try JSON body
        async with s.post(url, json={"amount": amount}) as r:
            data = await self._json_or_text(r)
            if r.status == 200:
                return int(data.get("currency", 0))
        # Try form body
        async with s.post(url, data={"amount": str(amount)}) as r:
            data = await self._json_or_text(r)
            if r.status == 200:
                return int(data.get("currency", 0))

        msg = data.get("message") if isinstance(data, dict) else data.get("_text") if isinstance(data, dict) else str(data)
        raise RuntimeError(f"Engauge credit {r.status}: {msg}")

    async def debit(self, user_id: int, amount: int) -> int:
        if amount <= 0:
            raise ValueError("debit amount must be > 0")
        s = await self.session()
        url = f"{self._member_url(user_id)}/currency"

        # 1) Preferred: POST negative amount (Engauge enforces business rules)
        for payload in (
            {"params": {"amount": str(-amount)}},   # ?amount=-X
            {"json": {"amount": -amount}},          # JSON body
            {"data": {"amount": str(-amount)}},     # form body
        ):
            async with s.post(url, **payload) as r:
                data = await self._json_or_text(r)
                if r.status == 200:
                    return int(data.get("currency", 0))
                if r.status in (400, 409):
                    msg = data.get("message") if isinstance(data, dict) else data.get("_text", "")
                    raise RuntimeError(msg or f"Debit refused ({r.status})")

        # 2) Fallback: JSON Patch replace /currency
        current = await self.get_balance(user_id)
        if current < amount:
            raise RuntimeError(f"Insufficient funds: have {current}, need {amount}")
        new_val = current - amount
        body = [{"op": "replace", "path": "/currency", "value": new_val}]
        headers = {"Content-Type": "application/json-patch+json"}
        async with s.patch(self._member_url(user_id), data=json.dumps(body), headers=headers) as r:
            data = await self._json_or_text(r)
            if r.status != 200:
                msg = data.get("message") if isinstance(data, dict) else data.get("_text", "")
                raise RuntimeError(f"Engauge debit PATCH {r.status}: {msg}")
            return int(data.get("currency", 0))

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

# ===================== Game Data ===================================
HORSE_SETS = [
    ["Atlas", "Sable", "Valkyrie", "Onyx", "Whiplash", "Jolt"],
    ["Comet", "Blitz", "Thunder", "Nebula", "Rocket", "Shadow"],
    ["Cinnamon", "Maverick", "Aurora", "Tempest", "Bandit", "Mirage"],
]
TRACK_LEN = 28

@dataclass
class Bet:
    user_id: int
    username: str
    horse: int
    amount: int

class RaceState:
    def __init__(self, channel_id: int, host_id: int, horses: List[str],
                 rake_bps: int, min_bet: int, max_bet: int):
        self.channel_id = channel_id
        self.host_id = host_id
        self.horses = horses
        self.positions = [0.0 for _ in horses]
        self.finished_order: List[int] = []
        self.bets: List[Bet] = []
        self.open_for_bets = True
        self.rake_bps = rake_bps
        self.min_bet = min_bet
        self.max_bet = max_bet
        self.message: Optional[discord.Message] = None
        self.lobby_message: Optional[discord.Message] = None
        self.ended = False

    def total_pool(self) -> int:
        return sum(b.amount for b in self.bets)

    def horse_pool(self, horse_idx: int) -> int:
        return sum(b.amount for b in self.bets if b.horse == horse_idx)

    def add_bet(self, bet: Bet) -> None:
        self.bets.append(bet)

# ===================== UI ==========================================
class BetModal(discord.ui.Modal, title="Place Your Bet"):
    amount = discord.ui.TextInput(label="Bet amount", placeholder="e.g., 250",
                                  min_length=1, max_length=10)
    def __init__(self, cog: "HorseRaceEngauge", race: RaceState, selected_horse_idx: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.race = race
        self.selected_horse_idx = selected_horse_idx

    async def on_submit(self, interaction: discord.Interaction):
        if self.race.ended or not self.race.open_for_bets:
            return await interaction.response.send_message("Betting is closed.", ephemeral=True)
        try:
            amt = int(str(self.amount.value).strip())
        except Exception:
            return await interaction.response.send_message("Enter a whole number.", ephemeral=True)
        if amt < self.race.min_bet:
            return await interaction.response.send_message(f"Minimum bet is {fmt_amt(self.race.min_bet)}.", ephemeral=True)
        if self.race.max_bet and amt > self.race.max_bet:
            return await interaction.response.send_message(f"Maximum bet is {fmt_amt(self.race.max_bet)}.", ephemeral=True)

        try:
            bal_after = await self.cog.get_wallet().debit(interaction.user.id, amt)
        except Exception as e:
            return await interaction.response.send_message(f"Couldn't place bet: {e}", ephemeral=True)

        bet = Bet(interaction.user.id, interaction.user.display_name, self.selected_horse_idx, amt)
        self.race.add_bet(bet)
        await self.cog.tx.log(interaction.guild_id or 0, interaction.channel_id or 0, "bet_placed", {
            "user_id": str(interaction.user.id), "username": bet.username,
            "horse_idx": bet.horse, "horse_name": self.race.horses[bet.horse],
            "amount": amt, "balance_after": bal_after
        })

        await interaction.response.send_message(
            f"Bet placed: **{fmt_amt(amt)}** on **{self.race.horses[self.selected_horse_idx]}**. Good luck!",
            ephemeral=True
        )
        try:
            if self.race.lobby_message:
                await self.race.lobby_message.edit(embed=self.cog.make_lobby_embed(self.race),
                                                   view=self.cog.make_lobby_view(self.race))
        except Exception:
            pass

class HorseSelect(discord.ui.Select):
    def __init__(self, cog: "HorseRaceEngauge", race: RaceState):
        self.cog = cog
        self.race = race
        opts = [discord.SelectOption(label=name, value=str(i), description=f"Horse #{i+1}")
                for i, name in enumerate(race.horses)]
        super().__init__(placeholder="Pick a horse…", min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        if self.race.ended or not self.race.open_for_bets:
            return await interaction.response.send_message("Betting is closed.", ephemeral=True)
        idx = int(self.values[0])
        await interaction.response.send_modal(BetModal(self.cog, self.race, idx))

class LobbyView(discord.ui.View):
    def __init__(self, cog: "HorseRaceEngauge", race: RaceState, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.race = race
        self.add_item(HorseSelect(cog, race))

    @discord.ui.button(label="Close Betting", style=discord.ButtonStyle.primary)
    async def close_bets(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.race.host_id and not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Only the host/mods can close betting.", ephemeral=True)
        if not self.race.open_for_bets:
            return await interaction.response.send_message("Betting is already closed.", ephemeral=True)

        self.race.open_for_bets = False
        await interaction.response.send_message("Betting closed! Race will start…", ephemeral=True)
        try:
            await self.race.lobby_message.edit(embed=self.cog.make_lobby_embed(self.race), view=None)
        except Exception:
            pass
        await self.cog.start_race(interaction)

# ===================== The Cog =====================================
class HorseRaceEngauge(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_races: Dict[int, RaceState] = {}
        self.wallet: Optional[EngaugeWallet] = None  # LAZY
        self.tx = TransactionLogger(bot)

    def get_wallet(self) -> EngaugeWallet:
        if self.wallet is None:
            token = (os.getenv("ENGAUGE_TOKEN") or "").strip()
            sid = (os.getenv("ENGAUGE_SERVER_ID") or "").strip()
            if not token or not sid:
                raise RuntimeError("ENGAUGE_TOKEN or ENGAUGE_SERVER_ID is not set in the environment.")
            self.wallet = EngaugeWallet()
        return self.wallet

    # ---------- Odds helper ----------
    def _project_odds_lines(self, race: RaceState) -> List[str]:
        pot = race.total_pool()
        if pot <= 0:
            return []
        rake = math.floor(pot * race.rake_bps / 10000)
        prize_pool = pot - rake
        lines = []
        for i, name in enumerate(race.horses):
            hp = race.horse_pool(i)
            if hp > 0 and prize_pool > 0:
                per100 = max(0, math.floor(prize_pool * 100 / hp))
                lines.append(f"**{name}** — pays {fmt_amt(per100)} per {fmt_amt(100)} (pool: {fmt_amt(hp)})")
            else:
                lines.append(f"**{name}** — no bets yet")
        return lines

    # ---------- Embeds ----------
    def make_lobby_embed(self, race: RaceState) -> discord.Embed:
        e = discord.Embed(
            title="🏁 Horse Race — Place Your Bets!",
            description="Pick a horse from the dropdown or use `/bet horse:<name> amount:<n>`.",
            color=discord.Color.gold(),
        )
        e.add_field(name="Horses", value="\n".join([f"**{i+1}. {name}**" for i, name in enumerate(race.horses)]), inline=True)
        e.add_field(name="Pool",
                    value=f"Total: **{fmt_amt(race.total_pool())}**\nRake: **{race.rake_bps/100:.2f}%**",
                    inline=True)
        if race.bets:
            by_horse = []
            for i, name in enumerate(race.horses):
                hp = race.horse_pool(i)
                if hp > 0:
                    by_horse.append(f"**{name}** — {fmt_amt(hp)}")
            if by_horse:
                e.add_field(name="By Horse", value="\n".join(by_horse), inline=False)
        odds = self._project_odds_lines(race)
        if odds:
            e.add_field(name="Current Odds (projected payouts)", value="\n".join(odds)[:1024], inline=False)
        e.set_footer(text=f"Min: {fmt_amt(race.min_bet)} | Max: {fmt_amt(race.max_bet) if race.max_bet else '∞'}")
        return e

    def render_track(self, race: RaceState) -> str:
        lines = []
        for i, (name, pos) in enumerate(zip(race.horses, race.positions)):
            p = min(int(pos), TRACK_LEN)
            bar = "‖" + ("■" * p).ljust(TRACK_LEN, "·") + "‖"
            flag = " 🏁" if p >= TRACK_LEN else ""
            lines.append(f"{i+1:>2}. {name:<12} {bar}{flag}")
        return "```\n" + "\n".join(lines) + "\n```"

    def make_race_embed(self, race: RaceState, title: str) -> discord.Embed:
        e = discord.Embed(title=title, color=discord.Color.blurple())
        e.add_field(name="Pot", value=f"{fmt_amt(race.total_pool())}", inline=True)
        return e

    def make_lobby_view(self, race: RaceState) -> LobbyView:
        return LobbyView(self, race, timeout=600)

    # ---------- Commands ----------
    @app_commands.command(name="race", description="Start a horse race betting lobby that uses Engauge currency.")
    @app_commands.describe(
        bet_window="Seconds to keep betting open (default 60).",
        rake="House rake in basis points (e.g., 500 = 5%).",
        min_bet="Minimum bet (default 50).",
        max_bet="Maximum bet (0 = no max, default 0).",
        horses="Number of horses (2-8, default 6).",
    )
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
    async def race_cmd(self, interaction: discord.Interaction,
                       bet_window: Optional[int] = 60,
                       rake: Optional[int] = 500,
                       min_bet: Optional[int] = 50,
                       max_bet: Optional[int] = 0,
                       horses: Optional[int] = 6):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(thinking=True)
            channel_id = interaction.channel_id
            if channel_id in self.active_races and not self.active_races[channel_id].ended:
                return await interaction.followup.send("A race is already active in this channel.", ephemeral=True)

            horses = max(2, min(8, horses or 6))
            horse_names = random.choice(HORSE_SETS)[:horses]
            rake_bps = max(0, min(2000, rake or 500))
            min_bet = max(1, min_bet or 50)
            max_bet = max(0, max_bet or 0)

            race = RaceState(channel_id, interaction.user.id, horse_names, rake_bps, min_bet, max_bet)
            self.active_races[channel_id] = race

            await self.tx.log(interaction.guild_id or 0, interaction.channel_id or 0, "race_start",
                              {"horses": horse_names, "rake_bps": rake_bps, "min_bet": min_bet, "max_bet": max_bet})

            msg = await interaction.followup.send(embed=self.make_lobby_embed(race), view=self.make_lobby_view(race))
            race.lobby_message = msg

            await asyncio.sleep(max(5, bet_window or 60))
            if not race.ended and race.open_for_bets:
                race.open_for_bets = False
                try:
                    await race.lobby_message.edit(embed=self.make_lobby_embed(race), view=None)
                except Exception:
                    pass
                await self.start_race(interaction)
        except Exception as e:
            print(f"/race error: {e}")
            try:
                await interaction.followup.send(f"Error starting race: `{e}`", ephemeral=True)
            except Exception:
                pass

    # Bet by name (with autocomplete)
    @app_commands.command(name="bet", description="Place a bet by horse NAME for the current race.")
    @app_commands.describe(horse="Horse name (autocomplete)", amount="Bet amount")
    async def bet_cmd(self, interaction: discord.Interaction, horse: str, amount: int):
        race = self.active_races.get(interaction.channel_id or 0)
        if not race or race.ended or not race.open_for_bets:
            return await interaction.response.send_message("No active betting lobby in this channel.", ephemeral=True)
        if amount < race.min_bet:
            return await interaction.response.send_message(f"Minimum bet is {fmt_amt(race.min_bet)}.", ephemeral=True)
        if race.max_bet and amount > race.max_bet:
            return await interaction.response.send_message(f"Maximum bet is {fmt_amt(race.max_bet)}.", ephemeral=True)

        names = race.horses
        target = (horse or "").strip().lower()
        idx = None
        for i, n in enumerate(names):
            if n.lower() == target:
                idx = i
                break
        if idx is None:
            matches = [i for i, n in enumerate(names) if target and target in n.lower()]
            if matches:
                idx = matches[0]
        if idx is None:
            return await interaction.response.send_message(
                f"Couldn't find a horse named **{horse}**. Options: {', '.join(names)}", ephemeral=True)

        try:
            bal_after = await self.get_wallet().debit(interaction.user.id, amount)
        except Exception as e:
            return await interaction.response.send_message(f"Couldn't place bet: {e}", ephemeral=True)

        bet = Bet(interaction.user.id, interaction.user.display_name, idx, amount)
        race.add_bet(bet)
        await self.tx.log(interaction.guild_id or 0, interaction.channel_id or 0, "bet_placed", {
            "user_id": str(interaction.user.id), "username": bet.username,
            "horse_idx": bet.horse, "horse_name": race.horses[bet.horse],
            "amount": amount, "balance_after": bal_after
        })
        try:
            if race.lobby_message:
                await race.lobby_message.edit(embed=self.make_lobby_embed(race), view=self.make_lobby_view(race))
        except Exception:
            pass
        await interaction.response.send_message(
            f"Bet placed: **{fmt_amt(amount)}** on **{race.horses[idx]}**. Good luck!", ephemeral=True
        )

    @bet_cmd.autocomplete("horse")
    async def bet_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        race = self.active_races.get(interaction.channel_id or 0)
        if not race:
            return []
        cur = (current or "").lower()
        scored = []
        for name in race.horses:
            n = name.lower()
            if cur and n.startswith(cur):
                score = 0
            elif cur and cur in n:
                score = 1
            else:
                score = 2
            scored.append((score, name))
        scored.sort()
        return [app_commands.Choice(name=n, value=n) for _, n in scored[:25]]

    wallet_group = app_commands.Group(name="wallet", description="Engauge wallet")

    @wallet_group.command(name="balance", description="Show your Engauge balance.")
    async def wallet_balance(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        member = member or interaction.user
        try:
            bal = await self.get_wallet().get_balance(member.id)
            await interaction.response.send_message(f"**{member.display_name}** has **{fmt_amt(bal)}**.")
        except Exception as e:
            await interaction.response.send_message(f"Wallet error: {e}", ephemeral=True)

    # Health command to debug env quickly
    @app_commands.command(name="race_health", description="Show Engauge env (admin only).")
    @app_commands.default_permissions(administrator=True)
    async def race_health(self, interaction: discord.Interaction):
        token_set = bool((os.getenv("ENGAUGE_TOKEN") or "").strip())
        sid = (os.getenv("ENGAUGE_SERVER_ID") or "").strip()
        base = (os.getenv("ENGAUGE_API_BASE") or "https://engau.ge").strip()
        msg = [
            f"ENGAUGE_TOKEN set: {'yes' if token_set else 'no'}",
            f"ENGAUGE_SERVER_ID: {sid or '(missing)'}",
            f"ENGAUGE_API_BASE: {base}",
        ]
        try:
            _ = self.get_wallet()
            msg.append("Wallet init: ✅")
        except Exception as e:
            msg.append(f"Wallet init: ❌ {e}")
        await interaction.response.send_message("\n".join(msg), ephemeral=True)

    # ---------- Engine ----------
    async def start_race(self, interaction: discord.Interaction):
        race = self.active_races.get(interaction.channel_id)
        if not race or race.ended:
            return
        desc = self.render_track(race)
        embed = self.make_race_embed(race, "🏁 The Race Begins!")
        race.message = await interaction.channel.send(embed=embed, content=desc)

        if race.total_pool() <= 0:
            await self.run_simulation(race, tick=1.0)
            await self.finish_race(interaction, race, payout=False)
            return

        await self.run_simulation(race, tick=1.0)
        await self.finish_race(interaction, race, payout=True)

    async def run_simulation(self, race: RaceState, tick: float = 1.0):
        base_speeds = [random.uniform(2.6, 3.2) for _ in race.horses]
        burst_chance = [random.uniform(0.10, 0.25) for _ in race.horses]
        fatigue = [random.uniform(0.01, 0.03) for _ in race.horses]
        winners_set = set()
        max_ticks = 40
        for t in range(max_ticks):
            for i in range(len(race.horses)):
                speed = base_speeds[i] * (1.0 - fatigue[i] * t)
                if random.random() < burst_chance[i]:
                    speed *= random.uniform(1.25, 1.6)
                jitter = random.uniform(-0.4, 0.6)
                delta = max(0.2, speed + jitter)
                race.positions[i] += delta
                if race.positions[i] >= TRACK_LEN and i not in winners_set:
                    winners_set.add(i)
                    race.finished_order.append(i)
            try:
                await race.message.edit(content=self.render_track(race),
                                        embed=self.make_race_embed(race, "🏁 Racing…"))
            except Exception:
                pass
            if race.finished_order:
                if t >= 3 + race.finished_order.index(race.finished_order[0]):
                    break
            await asyncio.sleep(tick)
        if not race.finished_order:
            race.finished_order = sorted(range(len(race.horses)), key=lambda i: -race.positions[i])

    async def finish_race(self, interaction: discord.Interaction, race: RaceState, payout: bool):
        race.ended = True
        try:
            await race.lobby_message.edit(view=None)
        except Exception:
            pass

        podium = race.finished_order[:3]
        medals = ["🥇", "🥈", "🥉"]
        results_header = "\n".join([f"{medals[i]} **{race.horses[h]}**" for i, h in enumerate(podium)]) or "—"

        payout_lines: List[str] = []
        rake_text = ""
        if payout:
            pot = race.total_pool()
            rake = math.floor(pot * race.rake_bps / 10000)
            prize_pool = pot - rake
            winning_horse = race.finished_order[0]
            winners = [b for b in race.bets if b.horse == winning_horse]
            win_pool = sum(b.amount for b in winners)

            bet_summaries = [f"<@{b.user_id}> {fmt_amt(b.amount)} on {race.horses[b.horse]}" for b in race.bets]

            if win_pool > 0 and prize_pool > 0:
                for b in winners:
                    share = b.amount / win_pool
                    winnings = math.floor(prize_pool * share)
                    try:
                        bal_after = await self.get_wallet().credit(b.user_id, winnings)
                        payout_lines.append(f"• <@{b.user_id}> wins **{fmt_amt(winnings)}**")
                        await self.tx.log(interaction.guild_id or 0, interaction.channel_id or 0, "payout", {
                            "user_id": str(b.user_id), "username": b.username, "horse_idx": b.horse,
                            "horse_name": race.horses[b.horse], "amount": winnings, "balance_after": bal_after,
                            "pot": pot, "prize_pool": prize_pool, "rake": rake,
                            "winning_horse": race.horses[winning_horse], "bets": bet_summaries
                        })
                    except Exception as e:
                        payout_lines.append(f"• <@{b.user_id}> payout error: {e}")
                rake_text = f"House rake: **{fmt_amt(rake)}**"
            else:
                refund_pool = math.floor(pot * 0.90)
                for b in race.bets:
                    share = b.amount / pot
                    refund = math.floor(refund_pool * share)
                    try:
                        bal_after = await self.get_wallet().credit(b.user_id, refund)
                        payout_lines.append(f"• <@{b.user_id}> refunded **{fmt_amt(refund)}**")
                        await self.tx.log(interaction.guild_id or 0, interaction.channel_id or 0, "refund", {
                            "user_id": str(b.user_id), "username": b.username, "horse_idx": b.horse,
                            "horse_name": race.horses[b.horse], "amount": refund, "balance_after": bal_after,
                            "pot": pot, "prize_pool": 0, "rake": rake,
                            "winning_horse": race.horses[winning_horse]
                        })
                    except Exception as e:
                        payout_lines.append(f"• <@{b.user_id}> refund error: {e}")
                rake_text = f"No winning bets — refunded 90% of pot. Burned **{fmt_amt(pot - refund_pool)}**."

        embed = discord.Embed(title="🏆 Race Results", color=discord.Color.green())
        embed.add_field(name="Podium", value=results_header, inline=False)
        if payout and race.bets:
            embed.add_field(name="Payouts", value="\n".join(payout_lines) or "—", inline=False)
            if rake_text:
                embed.set_footer(text=rake_text)
        else:
            embed.set_footer(text="(No bets were placed.)")

        try:
            await race.message.edit(content=self.render_track(race), embed=embed)
        except Exception:
            await interaction.channel.send(self.render_track(race), embed=embed)

        await self.tx.log(interaction.guild_id or 0, interaction.channel_id or 0, "race_end", {
            "podium": [race.horses[i] for i in race.finished_order[:3]],
            "pot": race.total_pool(),
            "rake_bps": race.rake_bps,
        })
        self.active_races.pop(race.channel_id, None)

    def cog_unload(self):
        try:
            loop = asyncio.get_event_loop()
            if self.wallet:
                loop.create_task(self.wallet.close())
        except Exception:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(HorseRaceEngauge(bot))
