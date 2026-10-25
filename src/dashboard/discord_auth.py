import time
from urllib.parse import urlencode
from fastapi import HTTPException
import aiohttp

API = 'https://discord.com/api/v10'


class DiscordAuth:
    def __init__(self, session, settings, repo):
        self.http, self.settings, self.repo = session, settings, repo
        self.members = {}
        self.role_cache = (0, {})

    def authorize_url(self, state):
        return 'https://discord.com/oauth2/authorize?' + urlencode({
            'client_id': self.settings.client_id, 'redirect_uri': self.settings.callback_url,
            'response_type': 'code', 'scope': 'identify', 'state': state,
        })

    async def request(self, method, path, **kwargs):
        try:
            async with self.http.request(method, API + path, timeout=aiohttp.ClientTimeout(total=15),
                                         allow_redirects=False, **kwargs) as r:
                if r.status == 404:
                    raise HTTPException(403, 'Company server membership is required')
                if r.status != 200:
                    raise HTTPException(503, 'Discord is temporarily unavailable. Please try again.')
                return await r.json()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise HTTPException(503, 'Discord is temporarily unavailable. Please try again.') from None

    async def exchange(self, code):
        data = await self.request('POST', '/oauth2/token', data={
            'client_id': self.settings.client_id, 'client_secret': self.settings.client_secret,
            'grant_type': 'authorization_code', 'code': code,
            'redirect_uri': self.settings.callback_url,
        })
        user = await self.request('GET', '/users/@me', headers={'Authorization': 'Bearer ' + data['access_token']})
        # No Discord access or refresh token is persisted.
        return user

    async def member(self, user_id, fresh=False):
        uid = str(user_id)
        cached = self.members.get(uid)
        if not fresh and cached and cached[0] > time.monotonic():
            return cached[1]
        headers = {'Authorization': 'Bot ' + self.settings.bot_token}
        try:
            member = await self.request('GET', f'/guilds/{self.settings.guild_id}/members/{uid}', headers=headers)
        except HTTPException as e:
            self.members.pop(uid, None)
            if e.status_code == 403:
                await self.repo.deactivate(uid)
            raise
        user = member['user']
        role_ids = set(member.get('roles', []))
        roles = []
        if self.settings.visible_roles:
            if self.role_cache[0] <= time.monotonic():
                values = await self.request('GET', f'/guilds/{self.settings.guild_id}/roles', headers=headers)
                self.role_cache = (time.monotonic() + 300, {r['id']: r['name'] for r in values})
            roles = [{'id': rid, 'name': self.role_cache[1].get(rid, 'Company member')}
                     for rid in sorted(role_ids & self.settings.visible_roles)]
        avatar = user.get('avatar')
        avatar_url = f'https://cdn.discordapp.com/avatars/{uid}/{avatar}.png?size=128' if avatar else None
        display_name = member.get('nick') or user.get('global_name') or user['username']
        result = {'user_id': uid, 'display_name': display_name, 'avatar_url': avatar_url,
                  'roles': roles, 'is_officer': bool(role_ids & self.settings.officer_roles)}
        await self.repo.upsert_member(uid, display_name, avatar_url, roles)
        if len(self.members) > 5000:
            self.members = {k: v for k, v in self.members.items() if v[0] > time.monotonic()}
        self.members[uid] = (time.monotonic() + self.settings.membership_seconds, result)
        return result
