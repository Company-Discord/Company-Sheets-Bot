# Company roster setup

The dashboard is a separate FastAPI service with a React/TypeScript frontend. It reads existing local economy balances; it cannot spend money or change economy settings. Dashboard tables are additive and independent from the bot's schema initializer.

## Local setup

1. Create an isolated Python environment and install `requirements-dashboard-dev.txt`.
2. Copy `.env.dashboard.example` to `.env.dashboard` and fill in the credentials and company guild ID. Use a development guild/database first.
3. Register the exact callback URL `http://localhost:8000/auth/discord/callback` on your Discord developer application's OAuth2 page. The bot must already belong to the configured guild. Enable Server Members Intent for full bot roster synchronization.
4. Run migrations once, then build and start the dashboard:

```powershell
python -m src.dashboard.migrate
cd web
npm ci
npm run build
cd ..
python -m src.dashboard.serve
```

Open `http://localhost:8000`. Serve the compiled frontend from FastAPI for the complete sign-in flow. Vite's separate dev origin is useful for UI development, but mutations require the configured DASHBOARD_URL Origin and a fresh CSRF token; use the same-origin build for authentication testing.

The service fails startup if required configuration or migrations are missing. It does not import the bot entry point or create economy tables. If `user_balances` is absent, profiles omit the balance panel. With no bot roster sync, members appear when they first sign in.

## Connect the bot

After migration, set `AION2_DISCORD_COMMANDS=true`, `DASHBOARD_GUILD_ID` (or existing `DISCORD_GUILD_ID`), `DATABASE_URL`, and optional `AION2_REGION=nae` in the bot service. `DATABASE_URL` must target the same PostgreSQL database as the bot economy. Restart the bot to register the optional `member_dashboard` cog. This enables the AION character commands without OAuth or a hosted website. Existing deployments with both `DASHBOARD_URL` unset and `AION2_DISCORD_COMMANDS` false behave as before.

To enable `/profile` dashboard links and roster synchronization, also set `DASHBOARD_URL` and the dashboard visibility/officer role IDs. The web service separately needs Discord OAuth credentials. AION commands require the additive dashboard migrations even when the website is not deployed.

The cog maintains the full nonbot roster every 15 minutes, updates member changes, and marks departing members inactive. `/profile [member]` opens a profile. Members can use `/link-character` to type at least three characters and select a suggested AION 2 character. Suggestions search all supported regions and identify each result by region and server; the command only accepts a selected result. `/my-characters` lists their links; `/aion-stats` shows main-character stats and equipment; `/set-main`, `/unlink-character`, and `/refresh-character` manage their own characters. Character commands and stat embeds are visible only to the member. Global import works after migration, and `/refresh-character` has a ten-minute cooldown. First-time links remain self-reported until an officer confirms them through the dashboard.

The bot's existing economy Database class uses POSTGRES_* variables, whereas the dashboard and optional roster cog use DATABASE_URL. Point both at the same database explicitly; setting DATABASE_URL alone does not reconfigure the existing economy code.

## Roles and privacy

- `DASHBOARD_OFFICER_ROLE_IDS`: comma-separated role IDs allowed to confirm/reassign character links and view member balances. No role names are trusted for authorization.
- `DASHBOARD_VISIBLE_ROLE_IDS`: role names that may appear on member profiles; blank hides all roles.
- Balances are visible only to the owner and officers. Engauge currency is not imported or combined with local balances.
- Ordinary guild membership is revalidated within 60 seconds; officer actions require a fresh Discord lookup. If Discord is unavailable after cache expiry, requests fail closed.
- Sessions expire after 24 hours. Session tokens are stored as hashes; Discord access/refresh tokens are not stored. A random database-backed session does not require a signing secret.
- Character links start self-reported. Officer confirmation approves the association, not game-account ownership. Members may link up to ten characters. Unlinking removes the association; canonical character snapshots remain under the retention policy.

## Enable AION imports

Use the read-only probe documented in `AION2_DATA_SOURCE.md` against the company's own region and character. After successful validation, set `AION2_IMPORTS_ENABLED=true` on the dashboard service.

Website character search/import remains off until `AION2_IMPORTS_ENABLED=true` on the dashboard service; members can paste an official profile URL and enter name/class/server while the website import is off. The bot's `/link-character` separately imports public character data after `AION2_DISCORD_COMMANDS=true` and its migration is applied. Automatic dashboard refresh is approximately six hours; manual refresh has a ten-minute cooldown. Search and imports are rate limited. A failed refresh retains the previous profile. Five failed attempts back off until the next six-hour retry cycle. Daily snapshots are retained for 90 days; historical charts are deferred.

## Railway deployment

Create a separate service from this repo using `Dockerfile.dashboard`. This preserves the existing bot's Nixpacks startup command. Set the Dockerfile path in that service's settings; do not change the bot service to use it.

- Build: the Dockerfile compiles the React app and installs dashboard-only Python requirements.
- Pre-deploy command: `python -m src.dashboard.migrate`.
- Start command: image default, `python -m src.dashboard.serve`.
- Health check: `/health`.
- Set DASHBOARD_URL to the final HTTPS origin and register its exact `/auth/discord/callback` with Discord.
- Set all required credentials through Railway secrets. Never embed them in frontend variables.

Take a database backup before migration. Initially run one dashboard replica. Jobs use PostgreSQL leases; each web process owns a pool of up to five connections, and the bot roster cog adds up to two. The worker runs inside the dashboard service.

The current checkout has not been deployed or connected to production credentials. Live Discord OAuth and company-specific permissions must be validated during the development-guild pilot. Disable the dashboard service and remove DASHBOARD_URL from the bot to roll back; existing economy tables are unaffected.

## Tests

```powershell
python -m pytest tests/dashboard -q
cd web
npm run build
```

For database integration checks without company credentials, start the ephemeral PGlite server in a separate terminal:

```powershell
cd web
node scripts/test-db.mjs
```

Then run tests from the repository root:

```powershell
$env:DASHBOARD_TEST_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable'
python -m pytest tests/dashboard -q
```

This is a disposable, loopback-only test database; it is lost when stopped. PGlite verifies PostgreSQL SQL behavior but multiplexes connections, so real PostgreSQL concurrency and Railway migration/startup still need pilot verification. Tests never read DATABASE_URL or load .env for integration database selection.

## Verified in this checkout

- Production TypeScript/Vite build completed successfully.
- Automated adapter, API authorization, CSRF, session, configuration, serialization, and disposable-database workflow checks passed.
- REA browser scenarios verified desktop roster and mobile profile rendering without page errors.
- Synthetic-member browser flows exercised linking, officer confirmation, main selection, unlinking, logout, and restoring a profile destination after sign-in.
- A live read-only NA East probe returned a character summary and equipment; see `AION2_DATA_SOURCE.md`.

For a local synthetic preview without credentials, start the disposable database, then run `python -m scripts.preview_dashboard`. Open `http://localhost:8000`. That script uses a fake Discord exchange and a fixed disposable loopback database; it is separate from production and is not copied into the deployment image. It does not prove the real Discord OAuth exchange or production guild permissions.
