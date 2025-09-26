# """
# UnbelievaBoat API Python Implementation

# This module provides a Python wrapper for the UnbelievaBoat Discord bot API.
# It allows you to interact with guild information, user balances, leaderboards, and more.

# Based on: https://github.com/yoggys/unbelievaboat/
# """

# import asyncio
# import aiohttp
# from typing import Optional, Dict, Any, List, Union
# from dataclasses import dataclass
# import json


# class UnbelievaBoatError(Exception):
#     """Base exception class for UnbelievaBoat API errors."""
#     pass


# class AuthenticationError(UnbelievaBoatError):
#     """Raised when API authentication fails."""
#     pass


# class NotFoundError(UnbelievaBoatError):
#     """Raised when a requested resource is not found."""
#     pass


# class RateLimitError(UnbelievaBoatError):
#     """Raised when API rate limit is exceeded."""
#     pass


# class APIError(UnbelievaBoatError):
#     """Raised when the API returns an error response."""
    
#     def __init__(self, message: str, status_code: int = None):
#         super().__init__(message)
#         self.status_code = status_code


# @dataclass
# class UserBalance:
#     """Represents a user's balance information."""
#     user_id: str
#     rank: Optional[int] = None
#     cash: int = 0
#     bank: int = 0
#     total: int = 0
    
#     def __post_init__(self):
#         self.total = self.cash + self.bank


# @dataclass
# class GuildInfo:
#     """Represents guild information."""
#     id: str
#     name: str
#     icon: Optional[str] = None
#     symbol: Optional[str] = None


# @dataclass
# class LeaderboardEntry:
#     """Represents a leaderboard entry."""
#     user_id: str
#     rank: int
#     cash: int
#     bank: int
#     total: int


# class User:
#     """Represents a user with balance management capabilities."""
    
#     def __init__(self, client: 'Client', guild_id: str, user_data: Dict[str, Any]):
#         self._client = client
#         self._guild_id = guild_id
#         self._user_id = user_data.get('user_id', '')
#         self._rank = user_data.get('rank')
#         self._cash = user_data.get('cash', 0)
#         self._bank = user_data.get('bank', 0)
#         self._total = user_data.get('total', self._cash + self._bank)
    
#     @property
#     def user_id(self) -> str:
#         return self._user_id
    
#     @property
#     def rank(self) -> Optional[int]:
#         return self._rank
    
#     @property
#     def cash(self) -> int:
#         return self._cash
    
#     @property
#     def bank(self) -> int:
#         return self._bank
    
#     @property
#     def total(self) -> int:
#         return self._total
    
#     async def set(self, cash: Optional[int] = None, bank: Optional[int] = None, reason: Optional[str] = None) -> 'User':
#         """Set user's balance to specific values."""
#         data = {}
#         if cash is not None:
#             data['cash'] = cash
#         if bank is not None:
#             data['bank'] = bank
#         if reason:
#             data['reason'] = reason
        
#         response = await self._client._request(
#             'PUT',
#             f'/guilds/{self._guild_id}/users/{self._user_id}',
#             json=data
#         )
        
#         # Update internal state
#         if cash is not None:
#             self._cash = cash
#         if bank is not None:
#             self._bank = bank
#         self._total = self._cash + self._bank
        
#         return self
    
#     async def update(self, cash: Optional[int] = None, bank: Optional[int] = None, reason: Optional[str] = None) -> 'User':
#         """Update user's balance by adding/subtracting values."""
#         data = {}
#         if cash is not None:
#             data['cash'] = cash
#         if bank is not None:
#             data['bank'] = bank
#         if reason:
#             data['reason'] = reason
        
#         response = await self._client._request(
#             'PATCH',
#             f'/guilds/{self._guild_id}/users/{self._user_id}',
#             json=data
#         )
        
#         # Update internal state
#         if cash is not None:
#             self._cash += cash
#         if bank is not None:
#             self._bank += bank
#         self._total = self._cash + self._bank
        
#         return self
    
#     def __str__(self) -> str:
#         return f"User(id={self.user_id}, cash={self.cash}, bank={self.bank}, total={self.total})"
    
#     def __repr__(self) -> str:
#         return self.__str__()


# class Guild:
#     """Represents a guild with user and balance management capabilities."""
    
#     def __init__(self, client: 'Client', guild_data: Dict[str, Any]):
#         self._client = client
#         self._id = guild_data.get('id', '')
#         self._name = guild_data.get('name', '')
#         self._icon = guild_data.get('icon')
#         self._symbol = guild_data.get('symbol')
    
#     @property
#     def id(self) -> str:
#         return self._id
    
#     @property
#     def name(self) -> str:
#         return self._name
    
#     @property
#     def icon(self) -> Optional[str]:
#         return self._icon
    
#     @property
#     def symbol(self) -> Optional[str]:
#         return self._symbol
    
#     async def get_user_balance(self, user_id: Union[int, str]) -> User:
#         """Get a user's balance information."""
#         response = await self._client._request(
#             'GET',
#             f'/guilds/{self._id}/users/{user_id}'
#         )
#         return User(self._client, self._id, response)
    
#     async def get_leaderboard(self, limit: int = 10, offset: int = 0, sort: str = 'total') -> List[LeaderboardEntry]:
#         """Get the guild's leaderboard."""
#         params = {
#             'limit': limit,
#             'offset': offset,
#             'sort': sort
#         }
        
#         response = await self._client._request(
#             'GET',
#             f'/guilds/{self._id}/users',
#             params=params
#         )
        
#         leaderboard = []
#         for entry in response.get('users', []):
#             leaderboard.append(LeaderboardEntry(
#                 user_id=entry.get('user_id', ''),
#                 rank=entry.get('rank', 0),
#                 cash=entry.get('cash', 0),
#                 bank=entry.get('bank', 0),
#                 total=entry.get('total', 0)
#             ))
        
#         return leaderboard
    
#     def __str__(self) -> str:
#         return f"Guild(id={self.id}, name={self.name})"
    
#     def __repr__(self) -> str:
#         return self.__str__()


# class Client:
#     """UnbelievaBoat API Client for interacting with the UnbelievaBoat Discord bot API."""
    
#     BASE_URL = 'https://unbelievaboat.com/api/v1'
    
#     def __init__(self, token: str):
#         """
#         Initialize the UnbelievaBoat API client.
        
#         Args:
#             token: Your UnbelievaBoat API token
#         """
#         self.token = token
#         self._session: Optional[aiohttp.ClientSession] = None
#         self._closed = False
    
#     async def _get_session(self) -> aiohttp.ClientSession:
#         """Get or create an aiohttp session."""
#         if self._session is None or self._session.closed:
#             headers = {
#                 'Authorization': self.token,
#                 'Content-Type': 'application/json',
#                 'User-Agent': 'UnbelievaBoat-Python-Wrapper/1.0'
#             }
#             self._session = aiohttp.ClientSession(headers=headers)
#         return self._session
    
#     async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
#         """Make an HTTP request to the API."""
#         if self._closed:
#             raise UnbelievaBoatError("Client is closed")
        
#         session = await self._get_session()
#         url = f"{self.BASE_URL}{endpoint}"
        
#         try:
#             async with session.request(method, url, **kwargs) as response:
#                 if response.status == 401:
#                     raise AuthenticationError("Invalid API token")
#                 elif response.status == 404:
#                     raise NotFoundError("Resource not found")
#                 elif response.status == 429:
#                     raise RateLimitError("Rate limit exceeded")
#                 elif response.status >= 400:
#                     error_text = await response.text()
#                     raise APIError(f"API error: {error_text}", response.status)
                
#                 if response.content_type == 'application/json':
#                     return await response.json()
#                 else:
#                     return {"data": await response.text()}
                    
#         except aiohttp.ClientError as e:
#             raise UnbelievaBoatError(f"Connection error: {str(e)}")
    
#     async def get_guild(self, guild_id: Union[int, str]) -> Guild:
#         """
#         Get guild information.
        
#         Args:
#             guild_id: The Discord guild ID
            
#         Returns:
#             Guild object with guild information
#         """
#         response = await self._request('GET', f'/guilds/{guild_id}')
#         return Guild(self, response)
    
#     async def get_guild_leaderboard(self, guild_id: Union[int, str], limit: int = 10, 
#                                   offset: int = 0, sort: str = 'total') -> List[LeaderboardEntry]:
#         """
#         Get a guild's leaderboard.
        
#         Args:
#             guild_id: The Discord guild ID
#             limit: Number of entries to return (default: 10)
#             offset: Number of entries to skip (default: 0)
#             sort: Sort field ('total', 'cash', 'bank') (default: 'total')
            
#         Returns:
#             List of LeaderboardEntry objects
#         """
#         guild = await self.get_guild(guild_id)
#         return await guild.get_leaderboard(limit, offset, sort)
    
#     async def get_user_balance(self, guild_id: Union[int, str], user_id: Union[int, str]) -> User:
#         """
#         Get a user's balance in a specific guild.
        
#         Args:
#             guild_id: The Discord guild ID
#             user_id: The Discord user ID
            
#         Returns:
#             User object with balance information
#         """
#         guild = await self.get_guild(guild_id)
#         return await guild.get_user_balance(user_id)
    
#     async def set_user_balance(self, guild_id: Union[int, str], user_id: Union[int, str],
#                              cash: Optional[int] = None, bank: Optional[int] = None,
#                              reason: Optional[str] = None) -> User:
#         """
#         Set a user's balance to specific values.
        
#         Args:
#             guild_id: The Discord guild ID
#             user_id: The Discord user ID
#             cash: Cash amount to set
#             bank: Bank amount to set
#             reason: Reason for the change
            
#         Returns:
#             Updated User object
#         """
#         user = await self.get_user_balance(guild_id, user_id)
#         return await user.set(cash, bank, reason)
    
#     async def update_user_balance(self, guild_id: Union[int, str], user_id: Union[int, str],
#                                 cash: Optional[int] = None, bank: Optional[int] = None,
#                                 reason: Optional[str] = None) -> User:
#         """
#         Update a user's balance by adding/subtracting values.
        
#         Args:
#             guild_id: The Discord guild ID
#             user_id: The Discord user ID
#             cash: Cash amount to add/subtract
#             bank: Bank amount to add/subtract
#             reason: Reason for the change
            
#         Returns:
#             Updated User object
#         """
#         user = await self.get_user_balance(guild_id, user_id)
#         return await user.update(cash, bank, reason)
    
#     async def close(self):
#         """Close the client session."""
#         if self._session and not self._session.closed:
#             await self._session.close()
#         self._closed = True
    
#     async def __aenter__(self):
#         """Async context manager entry."""
#         return self
    
#     async def __aexit__(self, exc_type, exc_val, exc_tb):
#         """Async context manager exit."""
#         await self.close()
    
#     def __del__(self):
#         """Cleanup when object is destroyed."""
#         if hasattr(self, '_session') and self._session and not self._session.closed:
#             # Create a task to close the session if event loop is running
#             try:
#                 loop = asyncio.get_event_loop()
#                 if loop.is_running():
#                     loop.create_task(self._session.close())
#             except RuntimeError:
#                 pass


# # Example usage and convenience functions
# async def quick_get_balance(token: str, guild_id: Union[int, str], user_id: Union[int, str]) -> UserBalance:
#     """
#     Convenience function to quickly get a user's balance.
    
#     Args:
#         token: UnbelievaBoat API token
#         guild_id: Discord guild ID
#         user_id: Discord user ID
        
#     Returns:
#         UserBalance dataclass with user's balance information
#     """
#     async with Client(token) as client:
#         user = await client.get_user_balance(guild_id, user_id)
#         return UserBalance(
#             user_id=user.user_id,
#             rank=user.rank,
#             cash=user.cash,
#             bank=user.bank,
#             total=user.total
#         )


# async def quick_get_leaderboard(token: str, guild_id: Union[int, str], 
#                               limit: int = 10) -> List[LeaderboardEntry]:
#     """
#     Convenience function to quickly get a guild's leaderboard.
    
#     Args:
#         token: UnbelievaBoat API token
#         guild_id: Discord guild ID
#         limit: Number of entries to return
        
#     Returns:
#         List of LeaderboardEntry objects
#     """
#     async with Client(token) as client:
#         return await client.get_guild_leaderboard(guild_id, limit=limit)


# # Example usage (commented out)
# """
# async def example_usage():
#     # Initialize the client with your API token
#     token = "your-api-token-here"
#     guild_id = "your-guild-id"
#     user_id = "your-user-id"
    
#     async with Client(token) as client:
#         # Get guild information
#         guild = await client.get_guild(guild_id)
#         print(f"Guild: {guild}")
        
#         # Get user balance
#         user = await client.get_user_balance(guild_id, user_id)
#         print(f"User balance: {user}")
        
#         # Update user balance
#         await user.update(cash=100, bank=50, reason="Daily bonus")
#         print(f"Updated balance: {user}")
        
#         # Get leaderboard
#         leaderboard = await client.get_guild_leaderboard(guild_id, limit=5)
#         print("Top 5 users:")
#         for entry in leaderboard:
#             print(f"  {entry.rank}. User {entry.user_id}: {entry.total} total")

# # Run the example
# # asyncio.run(example_usage())
# """
