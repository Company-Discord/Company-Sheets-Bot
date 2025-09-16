import os
import aiohttp


class InsufficientFunds(Exception):
    pass


class EngaugeAdapter:
    """
    Engauge currency client.
    Uses POST https://engau.ge/api/v1/servers/{server_id}/members/{member_id}/currency?amount=±N
    """

    def __init__(self, server_id: int):
        self.base = "https://engau.ge/api/v1"
        self.token = os.getenv("ENGAUGE_API_TOKEN") or os.getenv("ENGAUGE_TOKEN", "")
        self.server_id = int(server_id)
        if not self.token:
            raise RuntimeError("ENGAUGE_API_TOKEN or ENGAUGE_TOKEN must be set")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def adjust(self, member_id: int, amount: int):
        url = f"{self.base}/servers/{self.server_id}/members/{int(member_id)}/currency"
        params = {"amount": str(int(amount))}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params, headers=self._headers()) as r:
                if r.status == 402:
                    raise InsufficientFunds("Insufficient balance")
                r.raise_for_status()
                return await r.json()

    async def debit(self, member_id: int, amount: int):
        return await self.adjust(member_id, -abs(int(amount)))

    async def credit(self, member_id: int, amount: int):
        return await self.adjust(member_id, abs(int(amount)))
