"""Opt-in tests against a disposable DB only; never read DATABASE_URL/.env.

Set DASHBOARD_TEST_DATABASE_URL to a local ephemeral database.
"""
import asyncio
import os
import secrets
from urllib.parse import urlsplit
import asyncpg
import pytest
from src.dashboard.migrate import migrate
from src.dashboard.repository import Conflict, Missing, Repository, init_connection, public


def test_identifier_serialization():
    assert public({'user_id':9007199254740993,'data':{'name':'Test'},'confirmed_by':9007199254740994})=={
        'user_id':'9007199254740993','data':{'name':'Test'},'confirmed_by':'9007199254740994'}


@pytest.mark.skipif(not os.getenv('DASHBOARD_TEST_DATABASE_URL'),reason='Requires disposable DASHBOARD_TEST_DATABASE_URL')
def test_database_workflow():
    async def run():
        dsn=os.environ['DASHBOARD_TEST_DATABASE_URL']
        if urlsplit(dsn).hostname not in ('localhost','127.0.0.1'):
            raise RuntimeError('Integration tests require a disposable loopback database')
        await migrate(dsn)
        await migrate(dsn)  # Repeat migrations must be harmless.
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=1,init=init_connection,
                                      statement_cache_size=0,timeout=10,command_timeout=15)
        guild=secrets.randbelow(1000000000)+100
        repo=Repository(pool,guild)
        try:
            await repo.ready()
            await repo.upsert_member('9007199254740993','Alpha',None,[{'id':'123','name':'Officer'}])
            await repo.upsert_member('9007199254740994','Beta',None,[])
            first=await repo.link('9007199254740993','nae',1001,'char-'+str(guild),{'name':'Templar One','class_name':'Templar','server_name':'Test'},'manual',False)
            assert first==await repo.link('9007199254740993','nae',1001,'char-'+str(guild),{'name':'ignored'},'manual',False)
            with pytest.raises(Conflict):
                await repo.link('9007199254740994','nae',1001,'char-'+str(guild),{'name':'Test'},'manual',True)
            second=await repo.link('9007199254740993','nae',1001,'alt-'+str(guild),{'name':'Alt','class_name':'Cleric','server_name':'Test'},'manual',True)
            profile=await repo.profile('9007199254740993')
            assert profile['characters'][0]['id']==second
            assert len([x for x in profile['characters'] if x['is_main']])==1
            assert profile['balances'] is None
            roster=await repo.roster(query='Templar')
            assert roster['total']==1
            assert roster['items'][0]['user_id']=='9007199254740993'
            assert (await repo.filters())['classes']==['Cleric','Templar']
            assert (await repo.roster(class_name='Cleric',kind='main'))['total']==1
            assert (await repo.roster(class_name='Templar',kind='main'))['total']==0
            with pytest.raises(Missing):
                await repo.change_link('9007199254740994',first)
            await repo.confirm('9007199254740994',first)
            p=await repo.profile('9007199254740993')
            confirmed=next(x for x in p['characters'] if x['id']==first)
            assert confirmed['confirmed_by']=='9007199254740994'
            cid=int(confirmed['character_id'])
            await repo.queue_refresh('9007199254740993',cid,600)
            await repo.queue_refresh('9007199254740993',cid,600)
            assert await pool.fetchval('SELECT count(*) FROM character_refresh_jobs WHERE character_id=$1',cid)==1
            job=await repo.claim_job()
            assert job['id']==cid
            assert await repo.claim_job() is None
            with pytest.raises(Conflict):
                await repo.queue_refresh('9007199254740993',cid,600)
            await repo.finish_job(job,data={'name':'Imported','class_name':'Templar','server_name':'Test'})
            assert await pool.fetchval('SELECT count(*) FROM character_snapshots WHERE character_id=$1',cid)==1
            await pool.execute("UPDATE aion_characters SET last_attempt=now()-interval '1 hour' WHERE id=$1",cid)
            await repo.queue_refresh('9007199254740993',cid,600)
            retry=await repo.claim_job()
            await repo.finish_job(retry,error='throttled',retry_after=120)
            preserved=await pool.fetchrow('SELECT data,refresh_status FROM aion_characters WHERE id=$1',cid)
            assert preserved['data']['name']=='Imported'
            assert preserved['refresh_status']=='throttled'
            assert await repo.claim_job() is None
            await repo.change_link('9007199254740993',first)
            await repo.reassign('9007199254740994',first,'9007199254740994')
            assert (await repo.profile('9007199254740994'))['characters'][0]['is_main']
            assert (await repo.profile('9007199254740993'))['characters'][0]['is_main']
            await repo.change_link('9007199254740994',first,delete=True)
            assert not (await repo.profile('9007199254740994'))['characters']
            await repo.state('state-test-'+str(guild))
            assert await repo.consume_state('state-test-'+str(guild))
            assert not await repo.consume_state('state-test-'+str(guild))
            token=await repo.create_session('9007199254740993',1)
            assert (await repo.session(token))['user_id']==9007199254740993
            await repo.logout(token)
            assert not await repo.session(token)
            bucket='test-'+str(guild)
            assert await repo.rate(bucket,1)
            assert not await repo.rate(bucket,1)
            await repo.preferences('9007199254740993','Dungeons','Evenings')
            assert (await repo.profile('9007199254740993'))['availability']=='Evenings'
            await repo.cleanup()
            await repo.deactivate('9007199254740994')
            assert (await repo.roster())['total']==1
            assert await pool.fetchval('SELECT count(*) FROM dashboard_audit_log WHERE guild_id=$1',guild)>0
        finally:
            # Test IDs are isolated and the entire database is disposable.
            try:
                await asyncio.wait_for(pool.close(),timeout=5)
            except TimeoutError:
                pool.terminate()
    asyncio.run(run())
