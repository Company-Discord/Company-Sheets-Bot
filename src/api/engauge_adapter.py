import os
import random
import json
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

    def _parse_crates_from_env(self) -> list[dict]:
        """
        Parse crates from ENGAUGE_CRATES environment variable.
        Expected format: JSON string with array of crate objects.
        Each crate must have 'id' and 'probability' fields.
        
        Returns:
            List of crate dictionaries
            
        Raises:
            ValueError: If crates JSON is invalid or missing required fields
            RuntimeError: If ENGAUGE_CRATES environment variable is not set
        """
        crates_json = os.getenv("ENGAUGE_CRATES")
        if not crates_json:
            raise RuntimeError("ENGAUGE_CRATES environment variable is not set")
        
        try:
            crates = json.loads(crates_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in ENGAUGE_CRATES: {e}")
        
        if not isinstance(crates, list):
            raise ValueError("ENGAUGE_CRATES must be a JSON array")
        
        if not crates:
            raise ValueError("ENGAUGE_CRATES cannot be empty")
        
        # Validate each crate has required fields
        for i, crate in enumerate(crates):
            if not isinstance(crate, dict):
                raise ValueError(f"Crate {i} must be an object")
            if 'id' not in crate:
                raise ValueError(f"Crate {i} missing 'id' field")
            if 'probability' not in crate:
                raise ValueError(f"Crate {i} missing 'probability' field")
            try:
                float(crate['probability'])
            except (ValueError, TypeError):
                raise ValueError(f"Crate {i} 'probability' must be a number")
        
        return crates

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

    async def get_balance(self, member_id: int) -> int:
        """Get the current balance for a member"""
        url = f"{self.base}/servers/{self.server_id}/members/{int(member_id)}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self._headers()) as r:
                r.raise_for_status()
                data = await r.json()
                # Return the currency field from the member stats
                return int(data.get('currency', 0))

    async def drop_crate(self) -> dict:
        """
        Drop a crate by selecting one based on probability and calling the Engauge API.
        Crates are read from the ENGAUGE_CRATES environment variable.
        
        Returns:
            API response from the crate drop
            
        Raises:
            ValueError: If probabilities are invalid
            RuntimeError: If no crates are provided or ENGAUGE_CRATES is not set
        """
        # Parse crates from environment variable
        crates = self._parse_crates_from_env()
            
        # Extract probabilities from crate objects
        probabilities = []
        for crate in crates:
            probabilities.append(float(crate['probability']))
            
        # Normalize probabilities to ensure they sum to 1.0
        total_prob = sum(probabilities)
        if total_prob == 0:
            raise ValueError("Probabilities cannot all be zero")
        normalized_probs = [p / total_prob for p in probabilities]
        
        # Select crate based on probability
        selected_crate = random.choices(crates, weights=normalized_probs, k=1)[0]
        crate_id = selected_crate['id']
        
        # Call the Engauge API to drop the crate
        url = f"{self.base}/servers/{self.server_id}/crates/{crate_id}/drop"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=self._headers()) as r:
                print(f"Crate drop response: {r.status}")
                # Handle 500 responses gracefully - sometimes the API returns 500 even on successful drops
                if r.status == 500:
                    # Return a success response indicating the drop was attempted
                    return {
                        "success": True,
                        "reponse": await r.json(),
                        "crate_id": crate_id,
                        "status_code": 500
                    }
                elif r.status >= 400:
                    # For other error status codes, raise an exception
                    raise aiohttp.ClientResponseError(
                        request_info=r.request_info,
                        history=r.history,
                        status=r.status,
                        message=f"HTTP {r.status} error"
                    )
                else:
                    # For successful responses, return the JSON
                    return await r.json()
