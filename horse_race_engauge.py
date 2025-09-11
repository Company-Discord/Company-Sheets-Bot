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
from dotenv import load_dotenv

load_dotenv()
# ================= Currency =================
def cur() -> str:
    v = (os.getenv("CURRENCY_EMOJI") or "").strip()
    return v if v else "💰"

def fmt(n: int) -> str:
    return f"{cur()} {n:,}"

# ================= Logger =====================
class TxLog:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.path = os.getenv("TRANSACTION_LOG_PATH", "transactions.jsonl")
        ch = (os.getenv("RACE_LOG_CHANNEL_ID") or "").strip()
        self.log_channel_id: Optional[int] = int(ch) if ch.isdigit() else None

    async def write(self, kind: str, payload: dict):
        event = {"ts": datetime.now(timezone.utc).isoformat(), "type": kind, **payload}
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if self.log_channel_id:
            try:
                ch = self.bot.get_channel(self.log_channel_id) or await self.bot.fetch_channel(self.log_channel_id)
                if isinstance(ch, discord.TextChannel):
                    embed = discord.Embed(title=f"Race Log • {kind}", color=discord.Color.blurple())
                    for k, v in payload.items():
                        if k in ("amount", "pot", "prize_pool", "rake", "balance_after"):
                            try: v = fmt(int(v))
                            except: pass
                        embed.add_field(name=k, value=str(v), inline=True)
                    await ch.send(embed=embed)
            except Exception:
                pass

# ================= Engauge client ===========
class Engauge:
    def __init__(self):
        self.token = (os.getenv("ENGAUGE_TOKEN") or "").strip()
        self.server_id = (os.getenv("ENGAUGE_SERVER_ID") or "").strip()
        self.base = (os.getenv("ENGAUGE_API_BASE") or "https://engau.ge").rstrip("/")
        if not self.token or not self.server_id:
            raise RuntimeError("ENGAUGE_TOKEN and ENGAUGE_SERVER_ID must be set.")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=12),
                raise_for_status=False,
            )
        return self._session

    def _member(self, uid: int) -> str:
        return f"{self.base}/api/v1/servers/{self.server_id}/members/{uid}"

    async def _json_or_text(self, r: aiohttp.ClientResponse):
        ct = (r.headers.get("Content-Type") or "").lower()
        if "application/json" in ct:
            return await r.json()
        return {"_text": await r.text()}

    async def balance(self, uid: int) -> int:
        s = await self._s()
        async with s.get(self._member(uid)) as r:
            if r.status == 404:
                return 0
            data = await self._json_or_text(r)
            if r.status != 200:
                msg = data.get("message") if isinstance(data, dict) else str(data)
                raise RuntimeError(f"Engauge GET {r.status}: {msg}")
            return int(data.get("currency", 0))

    async def credit(self, uid: int, amount: int) -> int:
        if amount < 0:
            raise ValueError("credit amount must be >= 0")
        s = await self._s()
        url = f"{self._member(uid)}/currency"

        # Try ?amount=X, then JSON, then form
        for kwargs in ({"params": {"amount": str(amount)}},
                       {"json": {"amount": amount}},
                       {"data": {"amount": str(amount)}}):
            async with s.post(url, **kwargs) as r:
                data = await self._json_or_text(r)
                if r.status == 200:
                    return int(data.get("currency", 0))
        msg = data.get("message") if isinstance(data, dict) else data.get("_text", "")
        raise RuntimeError(f"Engauge credit {r.status}: {msg}")

    async def debit(self, uid: int, amount: int) -> int:
        if amount <= 0:
            raise ValueError("debit amount must be > 0")
        s = await self._s()
        url = f"{self._member(uid)}/currency"

        # Preferred: POST negative amount (Engauge should enforce rules)
        for kwargs in ({"params": {"amount": str(-amount)}},
                       {"json": {"amount": -amount}},
                       {"data": {"amount": str(-amount)}}):
            async with s.post(url, **kwargs) as r:
                data = await self._json_or_text(r)
                if r.status == 200:
                    return int(data.get("currency", 0))
                if r.status in (400, 409):
                    msg = data.get("message") if isinstance(data, dict) else data.get("_text", "")
                    raise RuntimeError(msg or f"Debit refused ({r.status})")

        # Fallback: PATCH replace /currency
        current = await self.balance(uid)
        if current < amount:
            raise RuntimeError(f"Insufficient funds: have {current}, need {amount}")
        new_val = current - amount
        body = [{"op": "replace", "path": "/currency", "value": new_val}]
        headers = {"Content-Type": "application/json-patch+json"}
        async with s.patch(self._member(uid), data=json.dumps(body), headers=headers) as r:
            data = await self._json_or_text(r)
            if r.status != 200:
                msg = data.get("message") if isinstance(data, dict) else data.get("_text", "")
                raise RuntimeError(f"Engauge debit PATCH {r.status}: {msg}")
            return int(data.get("currency", 0))

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

# ================= Game state =============+
HORSE_SETS = [
    ["Peppa Pig", "Piglet", "Ms. Piggy", "Porky Pig", "George Pig", "Charlotte"],
    ["Pumba", "Tom", "Jerry", "Bugs Bunny", "Daffy Duck", "Garfield"],
    ["Tiger Woods", "Tigger", "Shere Khan", "Tiger Jackson", "Tony the Tiger", "Tigress"],
]

TRACK_LEN = 28

@dataclass
class Bet:
    user_id: int
    username: str
    horse: int
    amount: int

class Race:
    def __init__(self, channel_id: int, host_id: int, horses: List[str],
                 rake_bps: int, min_bet: int, max_bet: int):
        self.channel_id = channel_id
        self.host_id = host_id
        self.horses = horses
        self.positions = [0.0 for _ in horses]
        self.finished: List[int] = []
        self.bets: List[Bet] = []
        self.open = True
        self.rake_bps = rake_bps
        self.min_bet = min_bet
        self.max_bet = max_bet
        self.msg: Optional[discord.Message] = None
        self.lobby: Optional[discord.Message] = None
        self.ended = False

    def pool(self) -> int:
        return sum(b.amount for b in self.bets)

    def pool_for(self, idx: int) -> int:
        return sum(b.amount for b in self.bets if b.horse == idx)

# ================= Views ==================
class BetModal(discord.ui.Modal, title="Place Your Bet"):
    amount = discord.ui.TextInput(label="Bet amount", placeholder="e.g., 250",
                                  min_length=1, max_length=10)
    def __init__(self, cog: "HorseRace", race: Race, horse_idx: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.race = race
        self.horse_idx = horse_idx

    async def on_submit(self, interaction: discord.Interaction):
        if self.race.ended or not self.race.open:
            return await interaction.response.send_message("Betting is closed.", ephemeral=True)
        try:
            amt = int(str(self.amount.value).strip())
        except Exception:
            return await interaction.response.send_message("Enter a whole number.", ephemeral=True)
        if amt < self.race.min_bet:
            return await interaction.response.send_message(f"Minimum bet is {fmt(self.race.min_bet)}.", ephemeral=True)
        if self.race.max_bet and amt > self.race.max_bet:
            return await interaction.response.send_message(f"Maximum bet is {fmt(self.race.max_bet)}.", ephemeral=True)
        try:
            bal_after = await self.cog.wallet.debit(interaction.user.id, amt)
        except Exception as e:
            return await interaction.response.send_message(f"Couldn't place bet: {e}", ephemeral=True)

        self.race.bets.append(Bet(interaction.user.id, interaction.user.display_name, self.horse_idx, amt))
        await self.cog.tx.write("bet_placed", {
            "user_id": str(interaction.user.id), "username": interaction.user.display_name,
            "horse_idx": self.horse_idx, "horse_name": self.race.horses[self.horse_idx],
            "amount": amt, "balance_after": bal_after
        })
        await interaction.response.send_message(f"Bet placed: **{fmt(amt)}** on **{self.race.horses[self.horse_idx]}**.", ephemeral=True)
        try:
            if self.race.lobby:
                await self.race.lobby.edit(embed=self.cog.lobby_embed(self.race),
                                           view=LobbyView(self.cog, self.race))
        except Exception:
            pass

class HorseSelect(discord.ui.Select):
    def __init__(self, cog: "HorseRace", race: Race):
        self.cog = cog
        self.race = race
        opts = [discord.SelectOption(label=name, value=str(i), description=f"Horse #{i+1}")
                for i, name in enumerate(race.horses)]
        super().__init__(placeholder="Pick a horse…", min_values=1, max_values=1, options=opts)
    async def callback(self, interaction: discord.Interaction):
        if self.race.ended or not self.race.open:
            return await interaction.response.send_message("Betting is closed.", ephemeral=True)
        await interaction.response.send_modal(BetModal(self.cog, self.race, int(self.values[0])))

class LobbyView(discord.ui.View):
    def __init__(self, cog: "HorseRace", race: Race):
        super().__init__(timeout=600)
        self.cog = cog
        self.race = race
        self.add_item(HorseSelect(cog, race))

    @discord.ui.button(label="Close Betting", style=discord.ButtonStyle.primary)
    async def close_bets(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.race.host_id and not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Only the host/mods can close betting.", ephemeral=True)
        if not self.race.open:
            return await interaction.response.send_message("Betting is already closed.", ephemeral=True)
        self.race.open = False
        await interaction.response.send_message("Betting closed! Race is starting…")
        try:
            await self.race.lobby.edit(embed=self.cog.lobby_embed(self.race), view=None)
        except Exception:
            pass
        await self.cog.start_race(interaction)

# ================= Cog =====================
class HorseRace(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.wallet = Engauge()            # keep eager – you already had it working
        self.tx = TxLog(bot)
        self.active: Dict[int, Race] = {}  # channel_id -> race
        
        # Set all commands in this cog to be guild-specific
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            print(f"[HorseRace] Setting guild-specific commands for {guild_id}")
            guild_obj = discord.Object(id=int(guild_id))
            for command in self.__cog_app_commands__:
                command.guild = guild_obj

    # ---- UI helpers ----
    def _odds(self, r: Race) -> List[str]:
        pot = r.pool()
        if pot <= 0:
            return []
        rake = math.floor(pot * r.rake_bps / 10000)
        prize = pot - rake
        out = []
        for i, name in enumerate(r.horses):
            hp = r.pool_for(i)
            if hp > 0 and prize > 0:
                per100 = math.floor(prize * 100 / hp)
                out.append(f"**{name}** — pays {fmt(per100)} per {fmt(100)} (pool: {fmt(hp)})")
            else:
                out.append(f"**{name}** — no bets yet")
        return out

    def lobby_embed(self, r: Race) -> discord.Embed:
        e = discord.Embed(
            title="🏁 Horse Race — Place Your Bets!",
            description="Pick a horse from the dropdown or use `/bet horse:<name> amount:<n>`.",
            color=discord.Color.gold(),
        )
        e.add_field(name="Horses", value="\n".join([f"**{i+1}. {n}**" for i, n in enumerate(r.horses)]), inline=True)
        e.add_field(name="Pool", value=f"Total: **{fmt(r.pool())}**\nRake: **{r.rake_bps/100:.2f}%**", inline=True)
        if r.bets:
            by = []
            for i, n in enumerate(r.horses):
                hp = r.pool_for(i)
                if hp > 0:
                    by.append(f"**{n}** — {fmt(hp)}")
            if by:
                e.add_field(name="By Horse", value="\n".join(by), inline=False)
        odds = self._odds(r)
        if odds:
            e.add_field(name="Current Odds (projected payouts)", value="\n".join(odds)[:1024], inline=False)
        e.set_footer(text=f"Min: {fmt(r.min_bet)} | Max: {fmt(r.max_bet) if r.max_bet else '∞'}")
        return e

    def track(self, r: Race) -> str:
        lines = []
        for i, (name, pos) in enumerate(zip(r.horses, r.positions)):
            p = min(int(pos), TRACK_LEN)
            bar = "‖" + ("■" * p).ljust(TRACK_LEN, "·") + "‖"
            flag = " 🏁" if p >= TRACK_LEN else ""
            lines.append(f"{i+1:>2}. {name:<12} {bar}{flag}")
        return "```\n" + "\n".join(lines) + "\n```"

    # ---- Commands ----
    @app_commands.command(name="race", description="Start a horse race betting lobby (Engauge currency).")
    @app_commands.describe(
        bet_window="Seconds betting stays open (default 60).",
        rake="House rake in basis points (500=5%).",
        min_bet="Minimum bet (default 50).",
        max_bet="Maximum bet (0=no max).",
        horses="Number of horses (2-8, default 6).",
    )
    async def race_cmd(self, interaction: discord.Interaction,
                       bet_window: Optional[int] = 60,
                       rake: Optional[int] = 500,
                       min_bet: Optional[int] = 50,
                       max_bet: Optional[int] = 0,
                       horses: Optional[int] = 6):
        # ACK quickly to avoid timeouts
        await interaction.response.defer(thinking=True)

        ch_id = interaction.channel_id
        if ch_id in self.active and not self.active[ch_id].ended:
            return await interaction.followup.send("A race is already active in this channel.", ephemeral=True)

        horses = max(2, min(8, horses or 6))
        names = random.choice(HORSE_SETS)[:horses]
        rake_bps = max(0, min(2000, rake or 500))
        min_bet = max(1, min_bet or 50)
        max_bet = max(0, max_bet or 0)

        r = Race(ch_id, interaction.user.id, names, rake_bps, min_bet, max_bet)
        self.active[ch_id] = r

        await self.tx.write("race_start", {
            "guild_id": str(interaction.guild_id or 0),
            "channel_id": str(ch_id or 0),
            "horses": names, "rake_bps": rake_bps, "min_bet": min_bet, "max_bet": max_bet
        })

        msg = await interaction.followup.send(embed=self.lobby_embed(r), view=LobbyView(self, r))
        r.lobby = msg

        await asyncio.sleep(max(5, bet_window or 60))
        if not r.ended and r.open:
            r.open = False
            try:
                await r.lobby.edit(embed=self.lobby_embed(r), view=None)
            except Exception:
                pass
            await self.start_race(interaction)

    # Bet by NAME (with autocomplete)
    @app_commands.command(name="bet", description="Place a bet by horse NAME for the current race.")
    @app_commands.describe(horse="Horse name", amount="Bet amount")
    async def bet_cmd(self, interaction: discord.Interaction, horse: str, amount: int):
        r = self.active.get(interaction.channel_id or 0)
        if not r or r.ended or not r.open:
            return await interaction.response.send_message("No active betting lobby in this channel.", ephemeral=True)
        if amount < r.min_bet:
            return await interaction.response.send_message(f"Minimum bet is {fmt(r.min_bet)}.", ephemeral=True)
        if r.max_bet and amount > r.max_bet:
            return await interaction.response.send_message(f"Maximum bet is {fmt(r.max_bet)}.", ephemeral=True)

        target = (horse or "").strip().lower()
        idx = None
        for i, n in enumerate(r.horses):
            if n.lower() == target:
                idx = i; break
        if idx is None:
            matches = [i for i, n in enumerate(r.horses) if target and target in n.lower()]
            if matches: idx = matches[0]
        if idx is None:
            return await interaction.response.send_message(
                f"Couldn't find **{horse}**. Options: {', '.join(r.horses)}", ephemeral=True)

        try:
            bal_after = await self.wallet.debit(interaction.user.id, amount)
        except Exception as e:
            return await interaction.response.send_message(f"Couldn't place bet: {e}", ephemeral=True)

        r.bets.append(Bet(interaction.user.id, interaction.user.display_name, idx, amount))
        await self.tx.write("bet_placed", {
            "user_id": str(interaction.user.id), "username": interaction.user.display_name,
            "horse_idx": idx, "horse_name": r.horses[idx], "amount": amount, "balance_after": bal_after
        })
        try:
            if r.lobby:
                await r.lobby.edit(embed=self.lobby_embed(r), view=LobbyView(self, r))
        except Exception:
            pass
        await interaction.response.send_message(
            f"Bet placed: **{fmt(amount)}** on **{r.horses[idx]}**.", ephemeral=True)

    @bet_cmd.autocomplete("horse")
    async def bet_autocomplete(self, interaction: discord.Interaction, current: str):
        r = self.active.get(interaction.channel_id or 0)
        if not r:
            return []
        cur = (current or "").lower()
        scored = []
        for name in r.horses:
            n = name.lower()
            score = 0 if cur and n.startswith(cur) else (1 if cur and cur in n else 2)
            scored.append((score, name))
        scored.sort()
        return [app_commands.Choice(name=n, value=n) for _, n in scored[:25]]

    wallet = app_commands.Group(name="wallet", description="Engauge wallet")

    @wallet.command(name="balance", description="Show your Engauge balance.")
    async def wallet_balance(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        m = member or interaction.user
        try:
            b = await self.wallet.balance(m.id)
            await interaction.response.send_message(f"**{m.display_name}** has **{fmt(b)}**.")
        except Exception as e:
            await interaction.response.send_message(f"Wallet error: {e}", ephemeral=True)

    # ---- Engine ----
    async def start_race(self, interaction: discord.Interaction):
        r = self.active.get(interaction.channel_id)
        if not r or r.ended:
            return
        msg = await interaction.channel.send(content=self.track(r),
                                             embed=discord.Embed(title="🏁 The Race Begins!", color=discord.Color.blurple()).add_field(name="Pot", value=fmt(r.pool())))
        r.msg = msg
        if r.pool() <= 0:
            await self.sim(r, 1.0); await self.finish(interaction, r, payout=False); return
        await self.sim(r, 1.0); await self.finish(interaction, r, payout=True)

    async def sim(self, r: Race, tick: float):
        base = [random.uniform(2.6, 3.2) for _ in r.horses]
        burst = [random.uniform(0.10, 0.25) for _ in r.horses]
        fatigue = [random.uniform(0.01, 0.03) for _ in r.horses]
        winners = set()
        for t in range(40):
            for i in range(len(r.horses)):
                v = base[i] * (1.0 - fatigue[i] * t)
                if random.random() < burst[i]: v *= random.uniform(1.25, 1.6)
                delta = max(0.2, v + random.uniform(-0.4, 0.6))
                r.positions[i] += delta
                if r.positions[i] >= TRACK_LEN and i not in winners:
                    winners.add(i); r.finished.append(i)
            try:
                await r.msg.edit(content=self.track(r),
                                 embed=discord.Embed(title="🏁 Racing…", color=discord.Color.blurple()).add_field(name="Pot", value=fmt(r.pool())))
            except Exception:
                pass
            if r.finished and t >= 3 + r.finished.index(r.finished[0]): break
            await asyncio.sleep(tick)
        if not r.finished:
            r.finished = sorted(range(len(r.horses)), key=lambda i: -r.positions[i])

    async def finish(self, interaction: discord.Interaction, r: Race, payout: bool):
        r.ended = True
        try:
            if r.lobby: await r.lobby.edit(view=None)
        except Exception:
            pass

        podium = r.finished[:3]
        medals = ["🥇", "🥈", "🥉"]
        results = "\n".join([f"{medals[i]} **{r.horses[h]}**" for i, h in enumerate(podium)]) or "—"

        lines = []
        footer = ""
        if payout:
            pot = r.pool()
            rake = math.floor(pot * r.rake_bps / 10000)
            prize = pot - rake
            win = r.finished[0]
            winners = [b for b in r.bets if b.horse == win]
            win_pool = sum(b.amount for b in winners)
            if win_pool > 0 and prize > 0:
                for b in winners:
                    share = b.amount / win_pool
                    pay = math.floor(prize * share)
                    try:
                        newb = await self.wallet.credit(b.user_id, pay)
                        lines.append(f"• <@{b.user_id}> wins **{fmt(pay)}**")
                        await self.tx.write("payout", {"user_id": str(b.user_id), "username": b.username,
                                                       "horse_idx": b.horse, "horse_name": r.horses[b.horse],
                                                       "amount": pay, "balance_after": newb,
                                                       "pot": pot, "prize_pool": prize, "rake": rake,
                                                       "winning_horse": r.horses[win]})
                    except Exception as e:
                        lines.append(f"• <@{b.user_id}> payout error: {e}")
                footer = f"House rake: **{fmt(rake)}**"
            else:
                refund_pool = math.floor(pot * 0.90)
                for b in r.bets:
                    refund = math.floor(refund_pool * (b.amount / pot)) if pot else 0
                    try:
                        newb = await self.wallet.credit(b.user_id, refund)
                        lines.append(f"• <@{b.user_id}> refunded **{fmt(refund)}**")
                        await self.tx.write("refund", {"user_id": str(b.user_id), "username": b.username,
                                                       "horse_idx": b.horse, "horse_name": r.horses[b.horse],
                                                       "amount": refund, "balance_after": newb,
                                                       "pot": pot, "prize_pool": 0, "rake": rake,
                                                       "winning_horse": r.horses[win]})
                    except Exception as e:
                        lines.append(f"• <@{b.user_id}> refund error: {e}")
                footer = f"No winning bets — refunded 90% of pot. Burned **{fmt(pot - refund_pool)}**."

        embed = discord.Embed(title="🏆 Race Results", color=discord.Color.green())
        embed.add_field(name="Podium", value=results, inline=False)
        if payout and r.bets:
            embed.add_field(name="Payouts", value="\n".join(lines) or "—", inline=False)
            if footer: embed.set_footer(text=footer)
        else:
            embed.set_footer(text="(No bets were placed.)")

        try:
            await r.msg.edit(content=self.track(r), embed=embed)
        except Exception:
            await interaction.channel.send(self.track(r), embed=embed)

        self.active.pop(r.channel_id, None)

    def cog_unload(self):
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self.wallet.close())
        except Exception:
            pass

async def setup(bot: commands.Bot):
    cog = HorseRace(bot)  
    await bot.add_cog(cog)


