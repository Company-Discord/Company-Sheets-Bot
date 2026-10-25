"""Read-only adapter for regional website JSON services, not an official SDK."""
import asyncio
import html
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
import aiohttp

REGIONS = {'nae': 'nae', 'naw': 'naw', 'eu': 'eu', 'sa': 'la', 'asia': 'as', 'kr': None, 'tw': None}


class AionError(Exception):
    def __init__(self, kind='unavailable', retry_after=60):
        self.kind = kind
        self.retry_after = retry_after
        super().__init__(kind)


def identity(region, server_id, character_id):
    character_id = unquote(str(character_id))
    if region not in REGIONS or not 0 < int(server_id) < 2147483647 or not re.fullmatch(r'[A-Za-z0-9_=+\-]{1,256}', character_id):
        raise ValueError('Invalid region, server, or character identifier')
    return region, int(server_id), character_id


def profile_url(region, server_id, character_id):
    region, server_id, character_id = identity(region, server_id, character_id)
    origin = 'https://tw.ncsoft.com/aion2' if region == 'tw' else 'https://aion2.plaync.com'
    locale = 'zh-tw' if region == 'tw' else 'ko-kr' if region == 'kr' else 'en-us'
    query = {'serverId': server_id, 'characterId': character_id}
    if REGIONS[region]:
        query['region'] = REGIONS[region]
    return f'{origin}/{locale}/characters/detail?{urlencode(query)}'


def parse_profile_url(url, region):
    p = urlsplit(url)
    host = 'tw.ncsoft.com' if region == 'tw' else 'aion2.plaync.com'
    if p.scheme != 'https' or p.netloc != host or p.username or p.fragment:
        raise ValueError('Use an official AION 2 character profile URL')
    if not re.fullmatch(r'(?:/aion2)?/[a-z]{2}-[a-z]{2}/characters/detail/?', p.path):
        raise ValueError('Use a character detail URL')
    q = parse_qs(p.query)
    if REGIONS.get(region) and q.get('region', [None])[0] != REGIONS[region]:
        raise ValueError('The profile region does not match the selected region')
    # parse_qs has already decoded percent escapes once.
    return identity(region, int(q.get('serverId', ['0'])[0]), q.get('characterId', [''])[0])


def safe_image(value, portrait=False):
    if not isinstance(value, str) or not value:
        return None
    if portrait and value.startswith('/') and not value.startswith('//'):
        value = 'https://profileimg.plaync.com' + value
    p = urlsplit(value)
    if p.scheme == 'https' and p.netloc in {'profileimg.plaync.com', 'assets.playnccdn.com'} and not p.username:
        return value
    return None


def number(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize_profile(raw, region, server, cid):
    p = raw.get('profile')
    if not isinstance(p, dict):
        raise AionError('invalid_response')
    if not p.get('characterId'):
        raise AionError('not_found')
    if unquote(p['characterId']) != cid or not p.get('characterName'):
        raise AionError('invalid_response')
    stats = raw.get('stat', {}).get('statList', [])
    return {
        'name': str(p['characterName'])[:100], 'class_name': p.get('className'),
        'level': number(p.get('characterLevel')), 'combat_power': number(p.get('combatPower')),
        'server_name': p.get('serverName'), 'image_url': safe_image(p.get('profileImage'), True),
        'item_level': next((number(s.get('value')) for s in stats if s.get('type') == 'ItemLevel'), None),
        'profile_url': profile_url(region, server, cid), 'equipment': [],
    }


class AionAdapter:
    def __init__(self, session):
        self.session = session
        self.lock = asyncio.Lock()
        self.next_request = 0
        self.catalogs = {}

    def route(self, region, path, search=False, catalog=False):
        if region not in REGIONS:
            raise ValueError('Unsupported region')
        if search and REGIONS[region]:
            return 'https://api-search.plaync.com/aion2global/search/v2/character'
        base = 'https://tw.ncsoft.com/aion2' if region == 'tw' else 'https://aion2.plaync.com'
        if catalog and REGIONS[region]:
            base += '/en-us'
        return base + ('/api/search/character' if search else '/api/' + path)

    def params(self, region):
        q = {'lang': 'zh-TW' if region == 'tw' else 'ko' if region == 'kr' else 'en-US'}
        if REGIONS[region]:
            q['region'] = REGIONS[region]
        return q

    async def get(self, url, params):
        async with self.lock:
            if self.next_request - time.monotonic() > 2:
                raise AionError('throttled', self.next_request - time.monotonic())
            await asyncio.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + 1
            try:
                async with self.session.get(url, params=params, allow_redirects=False,
                                            timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 429:
                        wait = r.headers.get('Retry-After', '60')
                        try:
                            seconds = float(wait)
                        except ValueError:
                            try:
                                seconds = (parsedate_to_datetime(wait) - datetime.now(timezone.utc)).total_seconds()
                            except (ValueError, TypeError):
                                seconds = 60
                        seconds = max(1, seconds)
                        self.next_request = time.monotonic() + seconds
                        raise AionError('throttled', seconds)
                    if r.status in (403, 404):
                        raise AionError('source_unavailable')
                    if r.status != 200:
                        raise AionError()
                    body = await r.content.read(2_000_001)
                    if len(body) > 2_000_000:
                        raise AionError('invalid_response')
                    data = json.loads(body)
                    if not isinstance(data, dict):
                        raise AionError('invalid_response')
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError):
                raise AionError() from None
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise AionError('invalid_response') from None

    async def servers(self, region):
        cached = self.catalogs.get(region)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        raw = await self.get(self.route(region, 'gameinfo/servers', catalog=True), self.params(region))
        rows = raw.get('serverList')
        if not isinstance(rows, list):
            raise AionError('invalid_response')
        result = [{'id': int(r['serverId']), 'name': str(r['serverName'])} for r in rows]
        self.catalogs[region] = (time.monotonic() + 86400, result)
        return result

    async def search(self, region, keyword, server=None, race=1):
        q = {'keyword': keyword, 'page': 1, 'size': 20}
        if REGIONS[region]:
            q.update(region=REGIONS[region], localeInfo='en-US')
        else:
            q['race'] = race
        if server:
            q['serverId'] = server
        raw = await self.get(self.route(region, '', search=True), q)
        if not isinstance(raw.get('list'), list):
            raise AionError('invalid_response')
        results = []
        for r in raw['list']:
            reg, sid, cid = identity(region, r['serverId'], r['characterId'])
            if REGIONS[region] and r.get('region') not in (None, '', REGIONS[region]):
                raise AionError('invalid_response')
            results.append({'region': reg, 'server_id': sid, 'character_id': cid,
                            'name': html.unescape(str(r.get('name', r.get('characterName', ''))).replace('<strong>', '').replace('</strong>', '')),
                            'server_name': r.get('serverName'), 'level': number(r.get('level'))})
        return results

    async def character(self, region, server, cid):
        region, server, cid = identity(region, server, cid)
        q = {**self.params(region), 'serverId': server, 'characterId': cid}
        raw = await self.get(self.route(region, 'character/info'), q)
        data = normalize_profile(raw, region, server, cid)
        try:
            eq = await self.get(self.route(region, 'character/equipment'), q)
            slots = eq.get('equipment', {}).get('equipmentList')
            if not isinstance(slots, list):
                raise AionError('invalid_response')
            data['equipment'] = [{'name': str(i.get('name', 'Unknown item'))[:200],
                                  'slot': i.get('slotPosName'), 'enchant': number(i.get('enchantLevel')),
                                  'image_url': safe_image(i.get('icon'))} for i in slots]
            data['equipment_status'] = 'available'
        except AionError:
            data['equipment_status'] = 'unavailable'
        return data
