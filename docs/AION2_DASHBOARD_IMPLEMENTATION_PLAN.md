na # Company Roster implementation plan

Status: draft. This plan extends the proposal in `docs/aion2.md`.

## Goal and first-release scope

Give company Discord members a private roster that connects their Discord identity, AION 2 characters, and existing bot balances.

The first release includes:

- Discord sign-in restricted to the company guild.
- Searchable roster with class, server, and main/alternate filters.
- Member profiles showing Discord identity, selected company roles, linked characters, and local bot balances.
- Character linking, unlinking, main-character selection, and officer confirmation.
- Imported character summary and equipment when the regional data source passes validation.
- Last-successful-refresh timestamps and useful unavailable/stale states.
- `/profile` and `/link-character` Discord commands.

Defer DPS/combat logs, automated ownership verification, group scheduling, achievements, currency transfers, and automatic rank rewards. Character lookup alone does not establish access to those features. Engauge balance display is optional after its access and caching behavior are validated; it must remain separate from local currency.

## Proposed architecture

Keep the current discord.py bot and PostgreSQL database. Add a FastAPI service and a React/TypeScript frontend. Build the frontend separately and serve its compiled files from the API service for a same-origin deployment.

Run the bot and dashboard as separate Railway services from the same repository, with separate startup commands. The dashboard must not import `bot.py`, start another Discord gateway client, or trigger command synchronization.

Use an AION adapter for regional character requests, a repository layer for new tables, and service methods for character linking and refreshes. Each process owns its own asyncpg pool. Read existing balances through explicit read-only queries rather than reusing methods that create users as a side effect.

Initially run one refresh worker inside the single dashboard instance. Claim jobs using PostgreSQL leases so that later replicas cannot refresh the same job simultaneously. Use versioned, additive SQL migrations applied once before deployment; do not depend on two processes concurrently performing schema initialization.

## Phase 1: validate the AION data source

This is the first implementation milestone, before committing to imported fields or a refresh interval.

1. Use the company's actual region/server and one known public character.
2. Inspect requests behind the official character search; use REA browser capture if available. Compare them with the open-source client references below.
3. Prove search -> region/server/character identifier -> character summary -> equipment using Python/aiohttp.
4. Record actual URLs, parameters, response fields, authentication requirements, status codes, and regional differences. Distinguish observed behavior from inferred behavior.
5. Check applicable published access guidance. Honor throttling and access restrictions; do not bypass authentication or regional blocks.
6. Save sanitized response fixtures and a supported-field mapping. Treat all upstream text and URLs as untrusted input.

Deliverable: `docs/AION2_DATA_SOURCE.md`, a small adapter prototype, and fixture-based parsing checks.

Acceptance: a known character can be resolved reliably in the target region and returns a usable summary. Missing characters, missing fields, timeouts, and throttling produce explicit outcomes. No account credentials are collected.

Fallback: launch with official profile links and clearly marked member-entered character details if automated retrieval is unavailable. Do not present member-entered values as imported data.

## Phase 2: database and integration layer

Add these tables with explicit foreign keys, constraints, and indexes:

| Table | Purpose |
|---|---|
| `member_profiles` | Guild/user identity, selected visible fields, preferences, timestamps |
| `aion_characters` | Canonical region/server/character identity, current normalized data, source/version, refresh state |
| `member_characters` | Guild/user-to-character links, main flag, self-reported/officer-confirmed status, confirming officer and time |
| `character_snapshots` | Timestamped normalized fields for future progress comparisons |
| `character_refresh_jobs` | Deduplicated pending jobs, attempts, next attempt, lease expiry |
| `dashboard_sessions` | Expiring server-side Discord login sessions |
| `dashboard_audit_log` | Link/unlink, confirmation, reassignment, and visibility changes |

Use region + server ID + character ID as the upstream identity. A name alone is insufficient. Store Discord snowflakes as PostgreSQL BIGINT and serialize them as strings in JSON to preserve JavaScript precision.

Enforce one main per guild/member and one claimant per guild/character. Officers resolve disputed claims with an audited reassignment. Confirmation means an officer approved the association; it is not NCSOFT account verification. Preserve canonical character data independently from a member's link.

Store timestamps in UTC and format them for the viewer. Index roster lookups by guild/user and snapshots by character/time. Capture daily snapshots only after collection starts; do not imply historical data exists. Proposed retention: 90 days of snapshots, configurable before launch.

Acceptance: repeated linking is idempotent, concurrent main changes preserve one main, and cross-guild or disputed claims cannot overwrite another member's association.

## Phase 3: Discord authentication and authorization

- Implement Discord's authorization-code sign-in with validated OAuth state and exact callback URLs; use minimal scopes, initially `identify`.
- Resolve company guild membership and roles on the backend through Discord's supported member lookup using the bot's server-side credentials.
- Recheck membership/roles on a short cache lifetime; require fresh authorization for officer actions. Deny access when membership cannot be established after cache expiry.
- Use expiring server-side sessions, Secure/HttpOnly/SameSite cookies, logout, CSRF protection for mutations, and restricted redirect targets.
- Derive member identity and allowed guild on the server. Never authorize using browser-supplied user IDs or role names.
- Members may edit their own profile and character links. Only configured officer/admin role IDs may confirm or reassign links.
- Default economic details to the member and authorized officers; make any roster-wide balance visibility an explicit setting.

Acceptance: nonmembers cannot access the roster, ordinary members cannot confirm links, and removed members lose access after the documented authorization cache expires.

## Phase 4: API and background refresh

Implement a guild-scoped API under `/api/v1`:

| Endpoint | Behavior |
|---|---|
| `GET /me` | Signed-in identity and effective permissions |
| `GET /members` | Paginated roster and filters |
| `GET /members/{user_id}` | Authorized profile view |
| `GET /aion/search` | Rate-limited regional character search |
| `POST /me/characters` | Link a resolved character |
| `PATCH /me/characters/{link_id}` | Select main/alternate |
| `DELETE /me/characters/{link_id}` | Unlink own character |
| `POST /characters/{character_id}/refresh` | Queue refresh; return accepted/cooldown state |
| `POST /character-links/{link_id}/confirm` | Officer confirmation |
| `POST /character-links/{link_id}/reassign` | Audited officer reassignment |

Start with a proposed six-hour automatic refresh and a ten-minute manual refresh cooldown, then adjust to observed upstream behavior and published limits. These are application defaults, not known upstream allowances. Limit concurrency, deduplicate jobs, honor Retry-After, and use bounded retries with backoff and jitter.

Never fetch arbitrary pasted URLs: parse only allowlisted official profile formats and construct requests using fixed regional hosts. Render text safely and validate external image/profile URLs.

Keep the last good response on refresh failure. Distinguish never loaded, refreshing, stale, not found, and unavailable. Log operational errors without tokens, session values, or unnecessary personal data.

Acceptance: roster browsing does not trigger one upstream request per row; upstream outages leave cached profiles usable and do not affect economy commands.

## Phase 5: dashboard and Discord commands

Build three screens:

1. Sign-in/access state, including clear nonmember and expired-session states.
2. Roster: search, pagination, class/server filters, main character, and confirmation badge.
3. Member profile: Discord details, character summary, equipment when supported, balances according to visibility, and link-management controls for the owner.

Label missing values as unavailable, not zero. Display source and last successful refresh. Support mobile layouts and keyboard navigation.

Add a small `member_dashboard` cog, loaded through the existing extension pattern. `/profile [member]` returns the dashboard profile link; `/link-character` returns the signed-in linking page. Configure the public dashboard URL through an environment variable. Opening a link must not grant access by itself.

Acceptance: a company member can sign in, link a main and alternate, find another member by character name, and open their own profile from Discord.

## Phase 6: validation and rollout

Required checks:

- Fixture-based adapter parsing, regional identity handling, missing fields, throttling, and malformed responses.
- PostgreSQL integration checks for unique claims, main selection, and refresh-job concurrency.
- Authentication/authorization checks for nonmembers, revoked roles, cross-user changes, CSRF, and arbitrary URL rejection.
- One end-to-end flow: sign in -> link -> officer confirms -> refresh -> profile -> unlink.
- Smoke-test existing bot startup and economy commands with the additive schema present.

Deploy to a development guild first, then invite officers and a small member group. Validate data accuracy and refresh volume before enabling the whole company.

Configuration will include Discord OAuth credentials/callback URL, allowed guild and officer role IDs, dashboard URL, database access, session secret, AION regional configuration, and refresh limits. Keep secrets server-side and out of the frontend bundle. Verify existing Railway PostgreSQL environment handling instead of assuming DATABASE_URL is already consumed by the current Database class.

Monitor login failures, refresh success/latency, upstream throttling, queue age, and database pool use. Back up PostgreSQL before migration. Roll back by disabling the dashboard service and cog; additive dashboard tables can remain while the existing bot continues operating.

## Delivery order and completion criteria

| Milestone | Reviewable result |
|---|---|
| 1 | AION lookup demonstrated for the company's region, or documented fallback |
| 2 | Migrations, adapter, and linking service with enforced identity constraints |
| 3 | Working Discord login and guild/role authorization |
| 4 | Roster/profile API, cached imports, and refresh worker |
| 5 | Usable member dashboard and Discord links |
| 6 | Pilot validated and company rollout enabled |

The first release is complete when a company member can securely access the roster, associate their character, receive officer confirmation, view supported character data and their authorized bot balances, and continue viewing cached data during an upstream outage.

## References and evidence limits

- [Official AION 2 character search](https://aion2.plaync.com/en-us/characters/index)
- [Unofficial client implementation](https://github.com/nuriland/aion2-api)
- [Client endpoint definitions](https://github.com/nuriland/aion2-api/blob/main/endpoint.go)
- [Client response models](https://github.com/nuriland/aion2-api/blob/main/types.go)

The earlier investigation identified website JSON endpoints through published client source. It did not validate a live character request, establish an official supported developer API, or verify upstream rate limits. Phase 1 resolves those dependencies before importing data into production.

## Implementation status (October 24, 2026)

The repository now contains the first-release implementation: FastAPI service, React frontend, additive migrations, website-data adapter, Discord OAuth/membership checks, character claim/main/confirmation/reassignment flows, preferences, private local balance display, queued refreshes, daily snapshots, and an optional bot roster-sync cog. The bot cog provides `/link-character`, `/my-characters`, `/aion-stats`, `/set-main`, `/unlink-character`, and `/refresh-character` for self-service character management.

The read-only NA East capability probe succeeded for servers, search, summary, and equipment. Automatic imports remain disabled by default until the company's actual region/character is validated. See `AION2_DATA_SOURCE.md` for the observed results and `DASHBOARD_SETUP.md` for local and Railway instructions.

Validation covers API access/CSRF/roles, adapter parsing and failure states, SQL workflow checks against disposable PGlite, desktop/mobile browser rendering, and browser linking/confirmation/main/unlink/logout flows with synthetic members. PGlite does not establish production PostgreSQL concurrency behavior. The live Discord authorization exchange, development-guild pilot, production database migration, and Railway deployment still require configured credentials and deployment access.
