# AION 2 data source

## Validation result

On October 24, 2026, the read-only Python probe successfully queried NA East:

- 18 server entries returned.
- A broad character search returned 20 results.
- The first result resolved to a character summary and 16 equipment items.
- Name, class, level, combat power, server name, portrait URL, and item level were present.

This was a public-service capability check, not validation of a company member or ownership. Other regions are configured from published client source but remain unverified here. Imports default to disabled. Validate the company's own region and character before enabling them.

A subsequent lookup using the requested name `Duck` in NA East returned 17 exact-name matches across different servers. Character summaries resolved for all 17; equipment resolved for 16, with one unavailable response correctly preserving its summary. The intended company character still needs a specific server selection. The probe now requires one exact-name match before choosing a character.

The user subsequently selected **Duck on Nezekan (NA East / Global)**. A server-specific probe using server ID **1102** found one exact match and successfully retrieved the level-45 Gladiator profile and 25 equipment entries. Supported summary fields included class, level, combat power, item level, server, portrait, and official profile URL. One initial invalid upstream response was transient; the diagnostic and final probe succeeded. No Discord character association or production configuration was changed.

Repeat this validated company target with:

```powershell
.venv-dashboard/Scripts/python -m scripts.probe_aion2 --region nae --name Duck --server 1102
```

## Requests

Global search uses `https://api-search.plaync.com/aion2global/search/v2/character` with keyword, page, size, region, and localeInfo. Global shards are nae, naw, eu, la, and as. Server ID is omitted for an all-server search.

Character summary and equipment requests use `/api/character/info` and `/api/character/equipment` at `https://aion2.plaync.com`, with lang, region, serverId, and characterId. Global server catalogs use `/en-us/api/gameinfo/servers`.

TW uses the fixed `https://tw.ncsoft.com/aion2` prefix. KR uses the main site without the Global region parameter. KR/TW search requires a faction choice. No alternate hosts, proxy bypasses, credentials, or game-client inspection are used.

The adapter normalizes already encoded character IDs to avoid double encoding. Official character URLs are constructed from validated identity fields; pasted URLs are parsed against an exact host/path allowlist and are never fetched directly.

## Operational behavior

The adapter uses one request at a time, with one second between requests. This is our conservative default, not a published provider allowance. It honors Retry-After, refuses redirects, caps response bytes, checks identity fields, and rejects invalid JSON. The refresh worker uses cached data, leased jobs, retries, and daily snapshots. Equipment failure does not discard a valid summary.

There is no proven official supported developer API contract, ownership authentication, combat-log feed, or published rate limit in this implementation. Website endpoints may change. Source labels and last-successful-refresh timestamps must remain visible.

## Reproduce for the company

```powershell
.venv-dashboard/Scripts/python -m scripts.probe_aion2 --region nae --name YourCharacter --server 1001
```

Use the actual server ID, or omit `--server`. For KR/TW add `--race 1` (Elyos) or `--race 2` (Asmodian). The probe imports only when exactly one exact-name match is present in the first search page. Otherwise it reports candidates; narrow by server rather than assuming the first partial-name result is the intended character. Its output reports capabilities rather than full player data.

The checked-in character fixture is synthetic and tests the observed response shape. No real player's response is retained in the repository.

## References

- [Official character search](https://aion2.plaync.com/en-us/characters/index)
- [Unofficial client regional routing](https://github.com/nuriland/aion2-api/blob/main/config.go)
- [Request and normalization reference](https://github.com/nuriland/aion2-api/blob/main/client.go)
- [Upstream response shapes](https://github.com/nuriland/aion2-api/blob/main/responses.go)
