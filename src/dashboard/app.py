import asyncio
import contextlib
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import aiohttp
import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .aion import AionAdapter, AionError, identity, parse_profile_url, profile_url
from .config import Settings
from .discord_auth import DiscordAuth
from .repository import Conflict, Missing, Repository, init_connection

log = logging.getLogger(__name__)
WEB_DIST = Path(__file__).resolve().parents[2] / 'web' / 'dist'
SNOWFLAKE = r'^[1-9][0-9]{0,18}$'


class LinkInput(BaseModel):
    region: Literal['nae', 'naw', 'eu', 'sa', 'asia', 'kr', 'tw']
    server_id: int | None = Field(default=None, gt=0, lt=2147483647)
    character_id: str | None = Field(default=None, max_length=256)
    profile_url: str | None = Field(default=None, max_length=2000)
    name: str = Field(default='', max_length=100)
    class_name: str = Field(default='', max_length=60)
    server_name: str = Field(default='', max_length=100)
    is_main: bool = False


class Preferences(BaseModel):
    preferences: str = Field(default='', max_length=500)
    availability: str = Field(default='', max_length=500)


class Reassignment(BaseModel):
    user_id: str = Field(pattern=SNOWFLAKE)


async def worker(app):
    while True:
        try:
            await app.state.repo.cleanup()
            if app.state.settings.aion_enabled:
                await app.state.repo.schedule(app.state.settings.refresh_seconds)
                job = await app.state.repo.claim_job()
                if job:
                    try:
                        data = await app.state.aion.character(job['region'], job['server_id'], job['character_id'])
                        await app.state.repo.finish_job(job, data=data)
                    except AionError as e:
                        await app.state.repo.finish_job(job, error=e.kind, retry_after=e.retry_after)
                    except (ValueError, KeyError, TypeError):
                        await app.state.repo.finish_job(job, error='invalid_response')
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Dashboard worker failed')
        await asyncio.sleep(15)


async def authenticated(request: Request):
    token = request.cookies.get('company_session', '')
    if not token or len(token) > 200:
        raise HTTPException(401, 'Sign in with Discord to continue')
    session = await request.app.state.repo.session(token)
    if not session:
        raise HTTPException(401, 'Your session expired. Sign in again.')
    member = await request.app.state.discord.member(session['user_id'])
    return {**member, 'csrf': session['csrf']}


async def mutation(request: Request, member=Depends(authenticated)):
    origin = request.headers.get('origin')
    csrf = request.headers.get('x-csrf-token', '')
    if origin != request.app.state.settings.public_url or not secrets.compare_digest(csrf, member['csrf']):
        raise HTTPException(403, 'This request could not be verified. Reload and try again.')
    if not await request.app.state.repo.rate('mutation:' + member['user_id'], 30):
        raise HTTPException(429, 'Too many changes. Please wait a minute.')
    return member


async def officer(request: Request, member=Depends(mutation)):
    fresh = await request.app.state.discord.member(member['user_id'], fresh=True)
    if not fresh['is_officer']:
        raise HTTPException(403, 'An officer role is required')
    return fresh


def create_app(settings=None, repo=None, discord=None, aion=None):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env()
        app.state.settings = config
        if repo is not None:
            app.state.repo, app.state.discord, app.state.aion = repo, discord, aion
            yield
            return
        pool = await asyncpg.create_pool(config.database_url, min_size=1, max_size=5, init=init_connection, command_timeout=20)
        try:
            repository = Repository(pool, config.guild_id)
            await repository.ready()
            async with aiohttp.ClientSession(headers={'User-Agent': 'CompanyRoster/1.0'}) as http:
                app.state.repo = repository
                app.state.discord = DiscordAuth(http, config, repository)
                app.state.aion = AionAdapter(http)
                task = asyncio.create_task(worker(app))
                try:
                    yield
                finally:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
        finally:
            await pool.close()

    app = FastAPI(title='Company Roster', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' https://cdn.discordapp.com https://profileimg.plaync.com https://assets.playnccdn.com; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        return JSONResponse({'detail': str(error)}, status_code=409)

    @app.exception_handler(Missing)
    async def missing(request, error):
        return JSONResponse({'detail': 'This profile or character link is unavailable'}, status_code=404)

    @app.exception_handler(AionError)
    async def upstream(request, error):
        return JSONResponse({'detail': 'AION 2 data is temporarily unavailable. Cached profiles are still available.', 'reason': error.kind},
                            status_code=503, headers={'Retry-After': str(int(error.retry_after))})

    @app.get('/health')
    async def health():
        return {'status': 'ok'}

    @app.get('/auth/discord')
    async def login(request: Request):
        # Fixed shared bucket bounds unauthenticated state creation across replicas.
        if not await app.state.repo.rate('oauth-start', 120):
            raise HTTPException(429, 'Please wait before signing in again')
        state = secrets.token_urlsafe(32)
        await app.state.repo.state(state)
        response = RedirectResponse(app.state.discord.authorize_url(state), status_code=303)
        response.set_cookie('company_oauth', state, max_age=600, httponly=True, secure=app.state.settings.secure_cookie, samesite='lax', path='/auth')
        return response

    @app.get('/auth/discord/callback')
    async def callback(request: Request, state: str = '', code: str = ''):
        cookie = request.cookies.get('company_oauth', '')
        if not state or len(state) > 200 or not cookie or not secrets.compare_digest(state, cookie) or not code or len(code) > 2000:
            raise HTTPException(400, 'Sign-in could not be verified. Please start again.')
        if not await app.state.repo.consume_state(state):
            raise HTTPException(400, 'Sign-in expired. Please start again.')
        user = await app.state.discord.exchange(code)
        await app.state.discord.member(user['id'], fresh=True)
        token = await app.state.repo.create_session(user['id'], app.state.settings.session_hours)
        previous = request.cookies.get('company_session')
        if previous:
            await app.state.repo.logout(previous)
        response = RedirectResponse('/', status_code=303)
        response.delete_cookie('company_oauth', path='/auth')
        response.set_cookie('company_session', token, httponly=True, secure=app.state.settings.secure_cookie,
                            samesite='lax', max_age=app.state.settings.session_hours * 3600, path='/')
        return response

    @app.post('/auth/logout')
    async def logout(request: Request, member=Depends(mutation)):
        await app.state.repo.logout(request.cookies['company_session'])
        response = JSONResponse({'ok': True})
        response.delete_cookie('company_session', path='/')
        return response

    @app.get('/api/v1/me')
    async def me(member=Depends(authenticated)):
        return {**member, 'imports_enabled': app.state.settings.aion_enabled}

    @app.get('/api/v1/members')
    async def members(q: str = Query('', max_length=100), region: str = Query('', max_length=10),
                      class_name: str = Query('', max_length=60), server: str = Query('', max_length=100),
                      kind: Literal['', 'main', 'alternate'] = '', offset: int = Query(0, ge=0, le=100000),
                      limit: int = Query(24, ge=1, le=100), member=Depends(authenticated)):
        return await app.state.repo.roster(q, region, class_name, server, kind, offset, limit)

    @app.get('/api/v1/filters')
    async def filters(member=Depends(authenticated)):
        return await app.state.repo.filters()

    @app.get('/api/v1/members/{user_id}')
    async def profile(user_id: str, member=Depends(authenticated)):
        import re
        if not re.fullmatch(SNOWFLAKE, user_id) or int(user_id) > 9223372036854775807:
            raise HTTPException(422, 'Invalid member ID')
        return await app.state.repo.profile(user_id, balances=member['user_id'] == user_id or member['is_officer'])

    @app.patch('/api/v1/me/preferences')
    async def preferences(body: Preferences, member=Depends(mutation)):
        await app.state.repo.preferences(member['user_id'], body.preferences, body.availability)
        return {'ok': True}

    @app.get('/api/v1/aion/servers')
    async def servers(region: Literal['nae', 'naw', 'eu', 'sa', 'asia', 'kr', 'tw'], member=Depends(authenticated)):
        if not app.state.settings.aion_enabled:
            raise HTTPException(409, 'Character imports are not enabled yet. Link an official profile instead.')
        if not await app.state.repo.rate('aion:' + member['user_id'], 10):
            raise HTTPException(429, 'Please wait before searching again')
        return await app.state.aion.servers(region)

    @app.get('/api/v1/aion/search')
    async def search(region: Literal['nae', 'naw', 'eu', 'sa', 'asia', 'kr', 'tw'],
                     q: str = Query(min_length=2, max_length=50), server_id: int | None = Query(None, gt=0),
                     race: int = Query(1, ge=1, le=2), member=Depends(authenticated)):
        if not app.state.settings.aion_enabled:
            raise HTTPException(409, 'Character imports are not enabled yet. Link an official profile instead.')
        if not await app.state.repo.rate('aion:' + member['user_id'], 10) or not await app.state.repo.rate('aion-global', 60):
            raise HTTPException(429, 'Please wait before searching again')
        return await app.state.aion.search(region, q, server_id, race)

    @app.post('/api/v1/me/characters', status_code=201)
    async def link(body: LinkInput, member=Depends(mutation)):
        try:
            if body.profile_url:
                region, sid, cid = parse_profile_url(body.profile_url, body.region)
            else:
                region, sid, cid = identity(body.region, body.server_id or 0, body.character_id or '')
        except (ValueError, KeyError):
            raise HTTPException(422, 'Provide a matching official profile URL or valid region, server ID and character ID') from None
        source = 'manual'
        if app.state.settings.aion_enabled:
            if not await app.state.repo.rate('import:' + member['user_id'], 5) or not await app.state.repo.rate('aion-global', 60):
                raise HTTPException(429, 'Please wait before importing another character')
            data = await app.state.aion.character(region, sid, cid)
            source = 'imported'
        else:
            if not body.name.strip():
                raise HTTPException(422, 'Enter a character name for the self-reported profile')
            data = {'name': body.name.strip(), 'class_name': body.class_name.strip() or None,
                    'server_name': body.server_name.strip() or None, 'profile_url': profile_url(region, sid, cid),
                    'equipment': [], 'combat_power': None, 'level': None, 'item_level': None}
        link_id = await app.state.repo.link(member['user_id'], region, sid, cid, data, source, body.is_main)
        return {'id': link_id}

    @app.patch('/api/v1/me/characters/{link_id}')
    async def main(link_id: int = PathParam(gt=0, le=9223372036854775807), member=Depends(mutation)):
        await app.state.repo.change_link(member['user_id'], link_id)
        return {'ok': True}

    @app.delete('/api/v1/me/characters/{link_id}')
    async def unlink(link_id: int = PathParam(gt=0, le=9223372036854775807), member=Depends(mutation)):
        await app.state.repo.change_link(member['user_id'], link_id, delete=True)
        return {'ok': True}

    @app.post('/api/v1/characters/{character_id}/refresh', status_code=202)
    async def refresh(character_id: int = PathParam(gt=0, le=9223372036854775807), member=Depends(mutation)):
        if not app.state.settings.aion_enabled:
            raise HTTPException(409, 'Automatic character imports are not enabled')
        await app.state.repo.queue_refresh(member['user_id'], character_id, app.state.settings.refresh_cooldown)
        return {'status': 'queued'}

    @app.post('/api/v1/character-links/{link_id}/confirm')
    async def confirm(link_id: int = PathParam(gt=0, le=9223372036854775807), member=Depends(officer)):
        await app.state.repo.confirm(member['user_id'], link_id)
        return {'ok': True}

    @app.post('/api/v1/character-links/{link_id}/reassign')
    async def reassign(body: Reassignment, link_id: int = PathParam(gt=0, le=9223372036854775807), member=Depends(officer)):
        if int(body.user_id) > 9223372036854775807:
            raise HTTPException(422, 'Invalid member ID')
        await app.state.discord.member(body.user_id, fresh=True)
        await app.state.repo.reassign(member['user_id'], link_id, body.user_id)
        return {'ok': True}

    if (WEB_DIST / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=WEB_DIST / 'assets'), name='assets')

    @app.get('/')
    async def index():
        if not (WEB_DIST / 'index.html').exists():
            return JSONResponse({'detail': 'Build the frontend first: cd web; npm ci; npm run build'}, status_code=503)
        return FileResponse(WEB_DIST / 'index.html')

    return app


app = create_app()
