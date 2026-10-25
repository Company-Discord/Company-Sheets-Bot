import hashlib
import json
import secrets
from datetime import date, datetime
import asyncpg


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public(value):
    """Serialize identifiers without losing snowflake precision in the browser."""
    if isinstance(value, (dict, asyncpg.Record)):
        return {k: str(v) if v is not None and (k.endswith('_id') or k in ('id', 'confirmed_by')) else public(v)
                for k, v in dict(value).items()}
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


async def init_connection(conn):
    await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')


class Repository:
    def __init__(self, pool, guild_id):
        self.pool = pool
        self.guild = guild_id

    async def ready(self):
        if not await self.pool.fetchval("SELECT to_regclass('member_profiles')"):
            raise RuntimeError('Run python -m src.dashboard.migrate before starting the dashboard')

    async def audit(self, conn, actor, action, details):
        await conn.execute('INSERT INTO dashboard_audit_log(guild_id,actor_id,action,details) VALUES($1,$2,$3,$4)',
                           self.guild, int(actor), action, details)

    async def upsert_member(self, user_id, name, avatar, roles):
        await self.pool.execute('''INSERT INTO member_profiles(guild_id,user_id,display_name,avatar_url,roles)
            VALUES($1,$2,$3,$4,$5) ON CONFLICT(guild_id,user_id) DO UPDATE SET
            display_name=excluded.display_name,avatar_url=excluded.avatar_url,roles=excluded.roles,
            active=true,updated_at=now()''', self.guild, int(user_id), name, avatar, roles)

    async def deactivate(self, user_id):
        await self.pool.execute('UPDATE member_profiles SET active=false WHERE guild_id=$1 AND user_id=$2', self.guild, int(user_id))

    async def roster(self, query='', region='', class_name='', server='', kind='', offset=0, limit=24):
        args = (self.guild, query, region, class_name, server, kind, offset, limit)
        where = '''m.guild_id=$1 AND m.active AND ($2='' OR m.display_name ILIKE '%'||$2||'%' OR EXISTS(
            SELECT 1 FROM member_characters x JOIN aion_characters a ON a.id=x.character_id
            WHERE x.guild_id=m.guild_id AND x.user_id=m.user_id AND a.data->>'name' ILIKE '%'||$2||'%'))
            AND (($3='' AND $4='' AND $5='' AND $6='') OR EXISTS(
              SELECT 1 FROM member_characters x JOIN aion_characters a ON a.id=x.character_id
              WHERE x.guild_id=m.guild_id AND x.user_id=m.user_id
              AND ($3='' OR a.region=$3) AND ($4='' OR a.data->>'class_name'=$4)
              AND ($5='' OR a.data->>'server_name'=$5)
              AND ($6='' OR ($6='main' AND x.is_main) OR ($6='alternate' AND NOT x.is_main))))'''
        rows = await self.pool.fetch(f'''SELECT m.*, (SELECT jsonb_build_object(
            'name',a.data->>'name','class_name',a.data->>'class_name','server_name',a.data->>'server_name',
            'region',a.region,'image_url',a.data->>'image_url','confirmed',x.confirmed_at IS NOT NULL)
            FROM member_characters x JOIN aion_characters a ON a.id=x.character_id
            WHERE x.guild_id=m.guild_id AND x.user_id=m.user_id AND x.is_main) AS main_character,
            (SELECT count(*) FROM member_characters x WHERE x.guild_id=m.guild_id AND x.user_id=m.user_id) AS character_count
            FROM member_profiles m WHERE {where} ORDER BY lower(m.display_name),m.user_id OFFSET $7 LIMIT $8''', *args)
        total = await self.pool.fetchval(f'SELECT count(*) FROM member_profiles m WHERE {where}', *args[:6])
        return {'items': public(list(rows)), 'total': total}

    async def filters(self):
        rows = await self.pool.fetch('''SELECT DISTINCT a.data->>'class_name' AS class_name,
            a.data->>'server_name' AS server FROM member_characters l
            JOIN aion_characters a ON a.id=l.character_id JOIN member_profiles m USING(guild_id,user_id)
            WHERE l.guild_id=$1 AND m.active''', self.guild)
        return {'classes': sorted({r['class_name'] for r in rows if r['class_name']}),
                'servers': sorted({r['server'] for r in rows if r['server']})}

    async def profile(self, user_id, balances=False):
        row = await self.pool.fetchrow('SELECT * FROM member_profiles WHERE guild_id=$1 AND user_id=$2 AND active', self.guild, int(user_id))
        if not row:
            raise Missing()
        links = await self.pool.fetch('''SELECT l.id,l.is_main,l.confirmed_by,l.confirmed_at,
            a.id AS character_id,a.region,a.server_id,a.character_id AS upstream_id,a.data,a.source,
            a.last_success,a.last_attempt,a.refresh_status, EXISTS(SELECT 1 FROM character_refresh_jobs j
            WHERE j.character_id=a.id AND j.next_attempt<=now()+interval '1 minute') AS refresh_pending
            FROM member_characters l JOIN aion_characters a ON a.id=l.character_id
            WHERE l.guild_id=$1 AND l.user_id=$2 ORDER BY l.is_main DESC,l.created_at''', self.guild, int(user_id))
        result = public(row)
        result['characters'] = public(list(links))
        result['balances'] = None
        if balances and await self.pool.fetchval("SELECT to_regclass('user_balances')"):
            balance = await self.pool.fetchrow('SELECT cash,bank FROM user_balances WHERE guild_id=$1 AND user_id=$2', self.guild, int(user_id))
            if balance:
                # Currency integers can exceed JS safe integer range too.
                result['balances'] = {'cash': str(balance['cash']), 'bank': str(balance['bank']), 'source': 'Local bot economy'}
        return result

    async def preferences(self, user_id, preferences, availability):
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute('UPDATE member_profiles SET preferences=$3,availability=$4 WHERE guild_id=$1 AND user_id=$2',
                               self.guild, int(user_id), preferences, availability)
            await self.audit(conn, user_id, 'preferences_updated', {})

    async def link(self, user_id, region, server, cid, data, source, main):
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                # Lock the member so concurrent main changes serialize.
                await conn.fetchval('SELECT user_id FROM member_profiles WHERE guild_id=$1 AND user_id=$2 FOR UPDATE', self.guild, int(user_id))
                count = await conn.fetchval('SELECT count(*) FROM member_characters WHERE guild_id=$1 AND user_id=$2', self.guild, int(user_id))
                char = await conn.fetchrow('''INSERT INTO aion_characters(region,server_id,character_id,data,source,last_success,refresh_status)
                    VALUES($1,$2,$3,$4,$5,CASE WHEN $5='imported' THEN now() END,
                    CASE WHEN $5='imported' THEN 'available' ELSE 'never_loaded' END)
                    ON CONFLICT(region,server_id,character_id) DO UPDATE SET
                    data=CASE WHEN excluded.source='imported' THEN excluded.data ELSE aion_characters.data END,
                    source=CASE WHEN excluded.source='imported' THEN excluded.source ELSE aion_characters.source END,
                    last_success=CASE WHEN excluded.source='imported' THEN excluded.last_success ELSE aion_characters.last_success END,
                    refresh_status=CASE WHEN excluded.source='imported' THEN 'available' ELSE aion_characters.refresh_status END
                    RETURNING id''',
                                          region, server, cid, data, source)
                existing = await conn.fetchrow('SELECT * FROM member_characters WHERE guild_id=$1 AND character_id=$2', self.guild, char['id'])
                if existing:
                    if existing['user_id'] != int(user_id):
                        raise Conflict('This character is already linked to another member. Ask an officer to resolve it.')
                    return str(existing['id'])
                if count >= 10:
                    raise Conflict('You may link up to ten characters')
                main = main or count == 0
                if main:
                    await conn.execute('UPDATE member_characters SET is_main=false WHERE guild_id=$1 AND user_id=$2', self.guild, int(user_id))
                link_id = await conn.fetchval('''INSERT INTO member_characters(guild_id,user_id,character_id,is_main)
                    VALUES($1,$2,$3,$4) RETURNING id''', self.guild, int(user_id), char['id'], main)
                await self.audit(conn, user_id, 'character_linked', {'link_id': str(link_id), 'source': source})
                return str(link_id)
        except asyncpg.UniqueViolationError:
            raise Conflict('This character was just claimed by another member') from None

    async def own_link(self, conn, user_id, link_id):
        row = await conn.fetchrow('SELECT * FROM member_characters WHERE guild_id=$1 AND id=$2 AND user_id=$3 FOR UPDATE', self.guild, int(link_id), int(user_id))
        if not row:
            raise Missing()
        return row

    async def change_link(self, user_id, link_id, delete=False):
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.fetchval('SELECT user_id FROM member_profiles WHERE guild_id=$1 AND user_id=$2 FOR UPDATE', self.guild, int(user_id))
            row = await self.own_link(conn, user_id, link_id)
            if delete:
                await conn.execute('DELETE FROM member_characters WHERE id=$1', int(link_id))
                if row['is_main']:
                    await conn.execute('''UPDATE member_characters SET is_main=true WHERE id=(SELECT id FROM member_characters
                        WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at,id LIMIT 1)''', self.guild, int(user_id))
            else:
                await conn.execute('UPDATE member_characters SET is_main=false WHERE guild_id=$1 AND user_id=$2', self.guild, int(user_id))
                await conn.execute('UPDATE member_characters SET is_main=true WHERE id=$1', int(link_id))
            await self.audit(conn, user_id, 'character_unlinked' if delete else 'main_changed', {'link_id': str(link_id)})

    async def confirm(self, actor, link_id):
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow('''UPDATE member_characters SET confirmed_by=$3,confirmed_at=now()
                WHERE guild_id=$1 AND id=$2 RETURNING id''', self.guild, int(link_id), int(actor))
            if not row:
                raise Missing()
            await self.audit(conn, actor, 'character_confirmed', {'link_id': str(link_id)})

    async def reassign(self, actor, link_id, target):
        async with self.pool.acquire() as conn, conn.transaction():
            old = await conn.fetchrow('SELECT * FROM member_characters WHERE guild_id=$1 AND id=$2', self.guild, int(link_id))
            if not old:
                raise Missing()
            # Deterministic lock order prevents deadlocks between officer reassignments.
            await conn.fetch('SELECT user_id FROM member_profiles WHERE guild_id=$1 AND user_id=ANY($2::bigint[]) ORDER BY user_id FOR UPDATE',
                             self.guild, sorted({old['user_id'], int(target)}))
            if not await conn.fetchval('SELECT 1 FROM member_profiles WHERE guild_id=$1 AND user_id=$2 AND active', self.guild, int(target)):
                raise Missing()
            current = await conn.fetchrow('SELECT * FROM member_characters WHERE guild_id=$1 AND id=$2 FOR UPDATE', self.guild, int(link_id))
            if not current or current['user_id'] != old['user_id']:
                raise Conflict('The link changed; reload and try again')
            if current['user_id'] == int(target):
                return
            count = await conn.fetchval('SELECT count(*) FROM member_characters WHERE guild_id=$1 AND user_id=$2', self.guild, int(target))
            if count >= 10:
                raise Conflict('The destination member already has ten characters')
            await conn.execute('UPDATE member_characters SET user_id=$2,is_main=$3,confirmed_by=$4,confirmed_at=now() WHERE id=$1',
                               int(link_id), int(target), count == 0, int(actor))
            if current['is_main']:
                await conn.execute('''UPDATE member_characters SET is_main=true WHERE id=(SELECT id FROM member_characters
                    WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at,id LIMIT 1)''', self.guild, current['user_id'])
            await self.audit(conn, actor, 'character_reassigned', {'link_id': str(link_id), 'from': str(current['user_id']), 'to': str(target)})

    async def state(self, token):
        await self.pool.execute("INSERT INTO dashboard_oauth_states VALUES($1,now()+interval '10 minutes')", digest(token))

    async def consume_state(self, token):
        return await self.pool.fetchval('DELETE FROM dashboard_oauth_states WHERE token_hash=$1 AND expires_at>now() RETURNING token_hash', digest(token))

    async def create_session(self, user_id, hours):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        await self.pool.execute("INSERT INTO dashboard_sessions(token_hash,user_id,csrf,expires_at) VALUES($1,$2,$3,now()+$4*interval '1 hour')",
                                digest(token), int(user_id), csrf, hours)
        return token

    async def session(self, token):
        return await self.pool.fetchrow('SELECT user_id,csrf FROM dashboard_sessions WHERE token_hash=$1 AND expires_at>now()', digest(token))

    async def logout(self, token):
        await self.pool.execute('DELETE FROM dashboard_sessions WHERE token_hash=$1', digest(token))

    async def rate(self, bucket, maximum, seconds=60):
        row = await self.pool.fetchrow('''INSERT INTO dashboard_rate_limits(bucket) VALUES($1)
            ON CONFLICT(bucket) DO UPDATE SET requests=CASE WHEN dashboard_rate_limits.window_start<now()-$2*interval '1 second'
            THEN 1 ELSE dashboard_rate_limits.requests+1 END,
            window_start=CASE WHEN dashboard_rate_limits.window_start<now()-$2*interval '1 second'
            THEN now() ELSE dashboard_rate_limits.window_start END RETURNING requests''', bucket, seconds)
        return row['requests'] <= maximum

    async def queue_refresh(self, user_id, character_id, cooldown):
        async with self.pool.acquire() as conn, conn.transaction():
            if not await conn.fetchval('SELECT 1 FROM member_characters WHERE guild_id=$1 AND user_id=$2 AND character_id=$3', self.guild, int(user_id), int(character_id)):
                raise Missing()
            row = await conn.fetchrow('SELECT * FROM aion_characters WHERE id=$1 FOR UPDATE', int(character_id))
            if row['last_attempt'] and (datetime.now(row['last_attempt'].tzinfo) - row['last_attempt']).total_seconds() < cooldown:
                raise Conflict('This character was refreshed recently. Try again after the cooldown.')
            # Never override a throttled retry or a worker's lease.
            await conn.execute('INSERT INTO character_refresh_jobs(character_id) VALUES($1) ON CONFLICT DO NOTHING', int(character_id))
            await self.audit(conn, user_id, 'refresh_requested', {'character_id': str(character_id)})

    async def schedule(self, seconds):
        await self.pool.execute('''INSERT INTO character_refresh_jobs(character_id)
            SELECT a.id FROM aion_characters a WHERE a.source='imported'
            AND (a.last_success IS NULL OR a.last_success<now()-$1*interval '1 second')
            AND EXISTS(SELECT 1 FROM member_characters l JOIN member_profiles m USING(guild_id,user_id)
                       WHERE l.character_id=a.id AND m.active)
            ON CONFLICT DO NOTHING''', seconds)

    async def claim_job(self):
        token = secrets.token_hex(16)
        row = await self.pool.fetchrow('''UPDATE character_refresh_jobs SET lease_until=now()+interval '2 minutes',lease_token=$1
            WHERE character_id=(SELECT character_id FROM character_refresh_jobs WHERE next_attempt<=now()
            AND (lease_until IS NULL OR lease_until<now()) ORDER BY next_attempt FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING character_id,attempts,lease_token''', token)
        if not row:
            return None
        char = await self.pool.fetchrow('SELECT * FROM aion_characters WHERE id=$1', row['character_id'])
        await self.pool.execute('UPDATE aion_characters SET last_attempt=now() WHERE id=$1', row['character_id'])
        return {**dict(char), **dict(row)}

    async def finish_job(self, job, data=None, error=None, retry_after=60):
        async with self.pool.acquire() as conn, conn.transaction():
            valid = await conn.fetchval('SELECT 1 FROM character_refresh_jobs WHERE character_id=$1 AND lease_token=$2 FOR UPDATE', job['id'], job['lease_token'])
            if not valid:
                return
            if data is not None:
                await conn.execute("UPDATE aion_characters SET data=$2,source='imported',last_success=now(),refresh_status='available' WHERE id=$1", job['id'], data)
                await conn.execute('''INSERT INTO character_snapshots(character_id,data) VALUES($1,$2)
                    ON CONFLICT(character_id,day) DO UPDATE SET data=excluded.data,collected_at=now()''', job['id'], data)
                await conn.execute('DELETE FROM character_refresh_jobs WHERE character_id=$1', job['id'])
            else:
                await conn.execute('UPDATE aion_characters SET refresh_status=$2 WHERE id=$1', job['id'], error)
                # Five attempts per retry cycle, then wait for the normal refresh interval.
                attempts = job['attempts'] + 1
                delay = max(retry_after, 21600 if attempts >= 5 else 60 * 2 ** attempts)
                delay += secrets.randbelow(30)
                await conn.execute("UPDATE character_refresh_jobs SET attempts=$3,next_attempt=now()+$2*interval '1 second',lease_until=NULL,lease_token=NULL WHERE character_id=$1", job['id'], delay, 0 if attempts >= 5 else attempts)

    async def cleanup(self):
        await self.pool.execute('''DELETE FROM character_refresh_jobs j WHERE NOT EXISTS(
            SELECT 1 FROM member_characters l JOIN member_profiles m USING(guild_id,user_id)
            WHERE l.character_id=j.character_id AND m.active)''')
        await self.pool.execute("DELETE FROM dashboard_sessions WHERE expires_at<now()")
        await self.pool.execute("DELETE FROM dashboard_oauth_states WHERE expires_at<now()")
        await self.pool.execute("DELETE FROM dashboard_rate_limits WHERE window_start<now()-interval '1 day'")
        await self.pool.execute("DELETE FROM character_snapshots WHERE day<current_date-90")
