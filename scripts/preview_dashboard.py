"""Loopback-only browser QA with synthetic members and a disposable test database.

Requires web/scripts/test-db.mjs. No .env is read, no Discord requests are made,
and this module is never imported by the production service.
"""
import asyncio
import contextlib
from contextlib import asynccontextmanager
from urllib.parse import quote
import asyncpg
import uvicorn
from src.dashboard.app import create_app
from src.dashboard.config import Settings
from src.dashboard.migrate import migrate
from src.dashboard.repository import Repository, init_connection

DSN='postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable'
settings=Settings(777,'http://localhost:8000','fixture','fixture','fixture',DSN,
                  officer_roles={'officer'},secure_cookie=False)
repo=Repository(None,777)
MEMBERS=[('9007199254741101','Aster','Officer','Templar','Asterion','nae'),
         ('9007199254741102','Mira','Company member','Cleric','Moonveil','nae'),
         ('9007199254741103','Rowan','Company member','Gladiator','Ironwake','eu'),
         ('9007199254741104','Vale','Company member','Ranger','Nightfall','nae'),
         ('9007199254741105','Juniper','Company member','Sorcerer','Emberlight','eu'),
         ('9007199254741106','Sol','Company member','Assassin','Solstice','nae')]


class FixtureDiscord:
    def authorize_url(self,state):
        return '/auth/discord/callback?code=fixture&state='+quote(state)
    async def exchange(self,code):
        return {'id':MEMBERS[0][0]}
    async def member(self,uid,fresh=False):
        return {'user_id':str(uid),'display_name':'Aster','is_officer':True,
                'avatar_url':None,'roles':[{'id':'officer','name':'Officer'}]}


app=create_app(settings,repo,FixtureDiscord(),None)
original_lifespan=app.router.lifespan_context


@asynccontextmanager
async def preview_lifespan(app):
    await migrate(DSN)
    repo.pool=await asyncpg.create_pool(DSN,min_size=1,max_size=1,init=init_connection,
                                      statement_cache_size=0,command_timeout=15)
    try:
        for uid,name,role,cls,char,region in MEMBERS:
            await repo.upsert_member(uid,name,None,[{'id':role,'name':role}])
            await repo.link(uid,region,1001,'preview-'+uid,
                            {'name':char,'class_name':cls,'server_name':'Preview world',
                             'profile_url':'https://aion2.plaync.com/en-us/characters/index',
                             'equipment':[],'combat_power':None,'level':None,'item_level':None},'manual',True)
        async with original_lifespan(app):
            yield
    finally:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(repo.pool.close(),5)


app.router.lifespan_context=preview_lifespan
if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=8000,access_log=False)
