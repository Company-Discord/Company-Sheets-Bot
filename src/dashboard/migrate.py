"""Run once before dashboard startup: python -m src.dashboard.migrate."""
import asyncio
from pathlib import Path
import asyncpg
from dotenv import load_dotenv
import os


async def migrate(dsn):
    conn = await asyncpg.connect(dsn, timeout=15, command_timeout=30, statement_cache_size=0)
    try:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(728193041)')
            await conn.execute('CREATE TABLE IF NOT EXISTS dashboard_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())')
            for path in sorted(Path(__file__).with_name('migrations').glob('*.sql')):
                if not await conn.fetchval('SELECT 1 FROM dashboard_migrations WHERE name=$1', path.name):
                    await conn.execute(path.read_text(encoding='utf-8'))
                    await conn.execute('INSERT INTO dashboard_migrations(name) VALUES($1)', path.name)
    finally:
        try:
            await conn.close(timeout=5)
        except TimeoutError:
            conn.terminate()


if __name__ == '__main__':
    load_dotenv()
    load_dotenv('.env.dashboard', override=True)
    asyncio.run(migrate(os.environ['DATABASE_URL']))
