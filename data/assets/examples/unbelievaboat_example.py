"""
Example usage of the UnbelievaBoat API implementation.

This file demonstrates how to use the UnbelievaBoat API client to interact
with guild information, user balances, and leaderboards.

Make sure to set your API token and guild/user IDs before running.
"""

import asyncio
import os
from unbelievaboat_api import Client, quick_get_balance, quick_get_leaderboard
from dotenv import load_dotenv
load_dotenv()
# Configuration - Replace with your actual values
API_TOKEN = os.getenv("UNBELIEVABOAT_TOKEN", "your-api-token-here")
GUILD_ID = os.getenv("UNBELIEVABOAT_GUILD_ID", "your-api-token-here")
USER_ID = os.getenv("UNBELIEVABOAT_USER_ID", "your-api-token-here")


async def basic_usage_example():
    """Basic usage example with context manager."""
    print("=== Basic Usage Example ===")
    
    async with Client(API_TOKEN) as client:
        try:
            # Get guild information
            print(f"Getting guild information for {GUILD_ID}")
            print(f"Getting user information for {USER_ID}")
            print(f"Getting API token for {API_TOKEN}")
            guild = await client.get_guild(GUILD_ID)
            print(f"Guild: {guild.name} (ID: {guild.id})")
            
            # Get user balance
            user = await client.get_user_balance(GUILD_ID, USER_ID)
            print(f"User balance: Cash={user.cash}, Bank={user.bank}, Total={user.total}")
            
            # Get guild leaderboard
            leaderboard = await client.get_guild_leaderboard(GUILD_ID, limit=5)
            print(f"\nTop 5 users:")
            for entry in leaderboard:
                print(f"  {entry.rank}. User {entry.user_id}: {entry.total} total")
                
        except Exception as e:
            print(f"Error: {e}")


async def balance_management_example():
    """Example of managing user balances."""
    print("\n=== Balance Management Example ===")
    
    async with Client(API_TOKEN) as client:
        try:
            # Get current balance
            user = await client.get_user_balance(GUILD_ID, USER_ID)
            print(f"Current balance: Cash={user.cash}, Bank={user.bank}")
            
            # Add some money (daily bonus example)
            await user.update(cash=100, reason="Daily login bonus")
            print(f"After daily bonus: Cash={user.cash}, Bank={user.bank}")
            
            # Transfer money from cash to bank
            transfer_amount = 50
            await user.update(cash=-transfer_amount, bank=transfer_amount, reason="Transfer to bank")
            print(f"After transfer: Cash={user.cash}, Bank={user.bank}")
            
        except Exception as e:
            print(f"Error: {e}")


async def convenience_functions_example():
    """Example using convenience functions."""
    print("\n=== Convenience Functions Example ===")
    
    try:
        # Quick balance check
        balance = await quick_get_balance(API_TOKEN, GUILD_ID, USER_ID)
        print(f"Quick balance check: {balance}")
        
        # Quick leaderboard
        top_users = await quick_get_leaderboard(API_TOKEN, GUILD_ID, limit=3)
        print(f"Top 3 users:")
        for entry in top_users:
            print(f"  {entry.rank}. User {entry.user_id}: {entry.total} total")
            
    except Exception as e:
        print(f"Error: {e}")


async def guild_operations_example():
    """Example of guild-specific operations."""
    print("\n=== Guild Operations Example ===")
    
    async with Client(API_TOKEN) as client:
        try:
            # Get guild object
            guild = await client.get_guild(GUILD_ID)
            print(f"Working with guild: {guild.name}")
            
            # Get user through guild
            user = await guild.get_user_balance(USER_ID)
            print(f"User balance via guild: {user}")
            
            # Get leaderboard through guild
            leaderboard = await guild.get_leaderboard(limit=10, sort='total')
            print(f"Guild leaderboard has {len(leaderboard)} entries")
            
        except Exception as e:
            print(f"Error: {e}")


async def error_handling_example():
    """Example of error handling."""
    print("\n=== Error Handling Example ===")
    
    from unbelievaboat_api import (
        AuthenticationError, 
        NotFoundError, 
        RateLimitError, 
        APIError
    )
    
    async with Client("invalid-token") as client:
        try:
            # This should raise an AuthenticationError
            guild = await client.get_guild(GUILD_ID)
        except AuthenticationError:
            print("✓ Caught authentication error as expected")
        except Exception as e:
            print(f"Unexpected error: {e}")
    
    async with Client(API_TOKEN) as client:
        try:
            # This should raise a NotFoundError
            user = await client.get_user_balance("invalid-guild-id", USER_ID)
        except NotFoundError:
            print("✓ Caught not found error as expected")
        except Exception as e:
            print(f"Unexpected error: {e}")


async def main():
    """Run all examples."""
    print("UnbelievaBoat API Examples")
    print("=" * 50)
    
    if API_TOKEN == "your-api-token-here":
        print("⚠️  Please set your API_TOKEN, GUILD_ID, and USER_ID before running examples")
        print("   You can set them as environment variables or edit this file directly")
        return
    
    # await basic_usage_example()
    await balance_management_example()
    # await convenience_functions_example()
    # await guild_operations_example()
    # await error_handling_example()
    
    print("\n✅ All examples completed!")


if __name__ == "__main__":
    # Run the examples
    asyncio.run(main())
