# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Company-Sheets-Bot is a Discord bot (discord.py) implementing a full economy and game system for a company Discord server. It is hosted on Railway using PostgreSQL as the backend.

## Running the Bot

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python -u bot.py
```

Requires a `.env` file with at minimum `DISCORD_BOT_TOKEN` and `DATABASE_URL`. See [Required Environment Variables](#required-environment-variables) below.

## Architecture

### Entry Point & Extension Loading

`bot.py` is the sole entry point. On startup it:
1. Loads all cogs via `bot.load_extension(...)` in `setup_hook()`
2. Starts the background crate-drop task (random interval 2–4 hours via `EngaugeAdapter`)
3. Syncs slash commands globally (and to the dev guild if `DISCORD_GUILD_ID` is set) in `on_ready()`

All slash commands are **flat** (no nested groups). The `/tc` group was removed; commands live directly at the top level.

### Cog Hierarchy

Every game/extension inherits from `src/bot/base_cog.py:BaseCog`, which provides:
- Shared `Database` instance (stored on `bot._unified_db`, initialized once)
- Helper methods for all common DB operations (balances, transactions, game tables)
- `format_currency()` / `format_time_remaining()` utilities
- Guild emoji cache (`BaseCog.emoji_cache` class variable)

### Source Layout

```
bot.py                          # Entry point
src/
  api/
    engauge_adapter.py          # Engauge.ge currency API (crate drops, balance, adjust)
    unbelievaboat_api.py        # Legacy, no longer used
  bot/
    base_cog.py                 # BaseCog – all cogs extend this
    extensions/
      currency_system.py        # /work /slut /crime /rob /balance /leaderboard /give /deposit /withdraw
      fun.py                    # Cat/dog/rabbit image commands, misc
      predictions.py            # Binary prediction betting with persistent Discord buttons
  database/
    database.py                 # All PostgreSQL operations via asyncpg
    models.py                   # Table definitions / schema
  games/
    blackjack.py / blackjack_v2.py
    cockfight.py
    crash.py
    duel_royale.py
    highlow.py
    horse_race_engauge.py       # Uses EngaugeAdapter for payouts
    lottery.py / lottery_daily.py
    poker_lite.py
  utils/
    utils.py                    # is_admin_or_manager() decorator, role/salary parsing, card rendering (Pillow), scaled earnings
```

### Database

`src/database/database.py` wraps asyncpg. The shared instance lives at `bot._unified_db` and is initialised once by the first `BaseCog.cog_load()` call. Key tables:

| Table | Purpose |
|-------|---------|
| `user_balances` | Cash, bank, earned/spent totals, per-command cooldown timestamps |
| `transactions` | Full audit trail of every money movement |
| `guild_settings` | Per-server economy config (cooldowns, earn ranges, etc.) |
| `role_salary` | Company role hierarchy with salaries |
| Game tables | `cockfight_streaks`, `lottery_entries`, `crash_bets`, `duel_matches`, `poker_sessions` |

### External APIs

- **Engauge** (`engau.ge`) – used by `horse_race_engauge` and the crate-drop background task. `EngaugeAdapter` reads crate config from `ENGAUGE_CRATES` (JSON array with `id` and `probability` per crate).
- **Cat/Dog/Rabbit APIs** – used in `fun.py` for image commands.

### Economy Design

Earnings scale with the user's total balance (`utils.py` `scaled_earnings()`). The four income commands and their defaults:

| Command | Cooldown | Success rate |
|---------|----------|-------------|
| `/work` | 30s | 100% |
| `/slut` | 90s | 70% |
| `/crime` | 180s | 40% |
| `/rob` | 900s | 30% |

All cooldowns and earn ranges are overridable via environment variables and per-guild `guild_settings`.

## Required Environment Variables

```
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=          # Dev guild for fast slash-command sync
DATABASE_URL=              # PostgreSQL connection string (Railway provides this)
ENGAUGE_API_TOKEN=         # Required for horse_race_engauge and crate drops
ENGAUGE_CRATES=            # JSON array: [{"id":"...", "probability":0.5}, ...]
TC_EMOJI=                  # Currency emoji (default 💰)
```

Role salary data is passed as a JSON string via `ROLE_DATA` env var and parsed by `utils.py`.

## Adding a New Game

1. Create `src/games/your_game.py` with a cog that subclasses `BaseCog`.
2. Add `await bot.load_extension("src.games.your_game")` in `bot.py:setup_hook()`.
3. Use `self.db.*` for all DB access; add new table methods to `database.py` and `models.py` if needed.
4. Use `self.deduct_cash()` / `self.add_cash()` to move money; call `self.log_transaction()` for audit trail.

## Slash Command Sync

After adding or renaming commands, run `/sync_commands` (admin-only) in Discord, or restart the bot. Commands sync automatically in `on_ready()` on first start. **Never call `tree.clear_commands()`** – this will wipe all registered commands.

## Deployment (Railway)

- Start command: `python -u bot.py`
- Environment variables are set in the Railway dashboard.
- `DATABASE_URL` is injected automatically by Railway's PostgreSQL plugin.
