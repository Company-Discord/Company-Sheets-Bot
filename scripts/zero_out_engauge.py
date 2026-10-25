"""
One-time script: sets all Engauge server members' currency to 0.

Strategy: page through members ordered by currency desc, debit each
member their full balance. Stop when no members with currency > 0 remain.

Usage:
    python scripts/zero_out_engauge.py

Requires .env with ENGAUGE_API_TOKEN and ENGAUGE_SERVER_ID (or DISCORD_GUILD_ID).
"""

import asyncio
import os
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv()

BASE = "https://engau.ge/api/v1"
TOKEN = os.getenv("ENGAUGE_API_TOKEN") or os.getenv("ENGAUGE_TOKEN", "")
SERVER_ID = os.getenv("ENGAUGE_SERVER_ID") or os.getenv("DISCORD_GUILD_ID", "")


if not TOKEN:
    sys.exit("ERROR: ENGAUGE_API_TOKEN not set in environment")
if not SERVER_ID:
    sys.exit("ERROR: ENGAUGE_SERVER_ID or DISCORD_GUILD_ID not set in environment")

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}


async def get_members_page(session: aiohttp.ClientSession, start: int) -> list[dict]:
    url = f"{BASE}/servers/{SERVER_ID}/members"
    params = {"start": start, "limit": 50, "order": "currency", "direction": "desc"}
    async with session.get(url, params=params, headers=HEADERS) as r:
        r.raise_for_status()
        return await r.json()


async def zero_member(session: aiohttp.ClientSession, member_id: int | str, balance: int) -> dict:
    url = f"{BASE}/servers/{SERVER_ID}/members/{member_id}/currency"
    params = {"amount": str(-balance)}
    async with session.post(url, params=params, headers=HEADERS) as r:
        if r.status == 402:
            raise RuntimeError(f"Insufficient funds error zeroing member {member_id}")
        r.raise_for_status()
        return await r.json()


TEST_MEMBER_ID = None  # Set to None to run against all members


async def main():
    if TEST_MEMBER_ID:
        print(f"TEST MODE: zeroing single member {TEST_MEMBER_ID} on server {SERVER_ID} ...")
        async with aiohttp.ClientSession() as session:
            url = f"{BASE}/servers/{SERVER_ID}/members/{TEST_MEMBER_ID}"
            async with session.get(url, headers=HEADERS) as r:
                r.raise_for_status()
                data = await r.json()
            balance = int(data.get("currency", 0))
            print(f"  Current balance: {balance}")
            if balance <= 0:
                print("  Already at 0, nothing to do.")
                return
            await zero_member(session, TEST_MEMBER_ID, balance)
            print(f"  Zeroed: -{balance}")
        return

    print(f"Zeroing all Engauge currency for server {SERVER_ID} ...")

    zeroed = 0
    skipped = 0

    async with aiohttp.ClientSession() as session:
        start = 0
        while True:
            members = await get_members_page(session, start)

            if not members:
                print("No more members returned — done.")
                break

            # Members are sorted currency desc; if first has 0 we're done
            first_balance = int(members[0].get("currency", 0)) if members else 0
            if first_balance <= 0:
                print("All remaining members already have 0 currency — done.")
                break

            for member in members:
                balance = int(member.get("currency", 0))
                member_id = member.get("id") or member.get("memberId") or member.get("userId")

                if balance <= 0:
                    skipped += 1
                    continue

                try:
                    await zero_member(session, member_id, balance)
                    print(f"  Zeroed member {member_id}: -{balance}")
                    zeroed += 1
                except Exception as e:
                    print(f"  ERROR zeroing member {member_id} (balance={balance}): {e}")

            # If we got a full page, there may be more — but since we zero as we go,
            # restart from 0 each batch so we always re-sort from the top.
            if len(members) < 50:
                break
            # Re-fetch from start since the ordering shifts as balances change
            start = 0

    print(f"\nDone. Zeroed: {zeroed}, Already-zero skipped: {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
