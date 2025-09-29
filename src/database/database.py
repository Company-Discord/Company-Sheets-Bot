"""
Unified Database Service - Centralized database management for all bot functionality.
PostgreSQL-compatible version.
"""

import os
import asyncio
import asyncpg
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
import pytz

from .models import UserBalance, Transaction, GuildSettings
from src.utils.utils import get_role_data

# Currency emoji constant
TC_EMOJI = os.getenv('TC_EMOJI', '💰')

# ================= Configuration =================
# PostgreSQL connection configuration
POSTGRES_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "bot_unified"),
    "user": os.getenv("POSTGRES_USER", "bot_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "bot_password"),
    "min_size": 5,
    "max_size": 20,
    "command_timeout": 60
}

# Default economy settings
DEFAULT_SETTINGS = {
    "currency_symbol": TC_EMOJI,
    "work_cooldown": 30,
    "slut_cooldown": 90,
    "crime_cooldown": 180,
    "rob_cooldown": 900,
    "collect_cooldown": 86400,
    "work_min_percent": 0.01,
    "work_max_percent": 0.05,
    "slut_min_percent": 0.02,
    "slut_max_percent": 0.08,
    "slut_fail_chance": 0.3,
    "crime_min_percent": 0.03,
    "crime_max_percent": 0.12,
    "crime_success_rate": 0.4,
    "rob_min_percent": 0.02,
    "rob_max_percent": 0.08,
    "rob_success_rate": 0.3,
}


class Database:
    """Unified database service managing all bot data in a single PostgreSQL database."""
    
    def __init__(self, config: dict = None):
        self.config = config or POSTGRES_CONFIG
        self._lock = asyncio.Lock()
        self._initialized = False
        self._pool: Optional[asyncpg.Pool] = None
    
    async def init_database(self):
        """Initialize the unified database with all required tables."""
        async with self._lock:
            if self._initialized:
                return
            
            # Create connection pool
            self._pool = await asyncpg.create_pool(**self.config)
            
            async with self._pool.acquire() as conn:
                # ================= Currency System Tables =================
                
                # User balances table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_balances (
                        user_id BIGINT,
                        guild_id BIGINT,
                        cash BIGINT DEFAULT 0,
                        bank BIGINT DEFAULT 0,
                        total_earned BIGINT DEFAULT 0,
                        total_spent BIGINT DEFAULT 0,
                        crimes_committed BIGINT DEFAULT 0,
                        crimes_succeeded BIGINT DEFAULT 0,
                        robs_attempted BIGINT DEFAULT 0,
                        robs_succeeded BIGINT DEFAULT 0,
                        last_work TIMESTAMP WITH TIME ZONE,
                        last_slut TIMESTAMP WITH TIME ZONE,
                        last_crime TIMESTAMP WITH TIME ZONE,
                        last_rob TIMESTAMP WITH TIME ZONE,
                        last_collect TIMESTAMP WITH TIME ZONE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York'),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York'),
                        PRIMARY KEY (user_id, guild_id)
                    )
                """)
                
                # Transactions table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        guild_id BIGINT,
                        amount BIGINT,
                        transaction_type TEXT,
                        target_user_id BIGINT,
                        success BOOLEAN,
                        reason TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York')
                    )
                """)
                
                # Guild settings table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS guild_settings (
                        guild_id BIGINT PRIMARY KEY,
                        currency_symbol TEXT DEFAULT '{TC_EMOJI}',
                        work_cooldown BIGINT DEFAULT 30,
                        slut_cooldown BIGINT DEFAULT 90,
                        crime_cooldown BIGINT DEFAULT 180,
                        rob_cooldown BIGINT DEFAULT 900,
                        collect_cooldown BIGINT DEFAULT 86400,
                        work_min_percent DECIMAL(5,4) DEFAULT 0.01,
                        work_max_percent DECIMAL(5,4) DEFAULT 0.05,
                        slut_min_percent DECIMAL(5,4) DEFAULT 0.02,
                        slut_max_percent DECIMAL(5,4) DEFAULT 0.08,
                        slut_fail_chance DECIMAL(5,4) DEFAULT 0.3,
                        crime_min_percent DECIMAL(5,4) DEFAULT 0.03,
                        crime_max_percent DECIMAL(5,4) DEFAULT 0.12,
                        crime_success_rate DECIMAL(5,4) DEFAULT 0.4,
                        rob_min_percent DECIMAL(5,4) DEFAULT 0.02,
                        rob_max_percent DECIMAL(5,4) DEFAULT 0.08,
                        rob_success_rate DECIMAL(5,4) DEFAULT 0.3,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York')
                    )
                """)
                
                # Role salary table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS role_salary (
                        name TEXT PRIMARY KEY,
                        role_id BIGINT NOT NULL,
                        salary BIGINT NOT NULL
                    )
                """)
                
                # ================= Game Tables =================
                
                # Cockfight streaks table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS cockfight_streaks (
                        user_id BIGINT,
                        guild_id BIGINT,
                        streak BIGINT NOT NULL DEFAULT 0,
                        PRIMARY KEY (user_id, guild_id)
                    )
                """)
                
                # Lottery tables
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS lotteries (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        status TEXT NOT NULL,
                        ticket_price BIGINT NOT NULL,
                        bonus_per_ticket BIGINT NOT NULL,
                        min_participants BIGINT NOT NULL,
                        split_first_bps BIGINT NOT NULL,
                        seed_amount BIGINT NOT NULL,
                        open_ts BIGINT NOT NULL,
                        close_ts BIGINT NOT NULL,
                        announce_channel_id BIGINT NOT NULL
                    )
                """)
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS tickets (
                        lottery_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        quantity BIGINT NOT NULL,
                        amount_paid BIGINT NOT NULL,
                        PRIMARY KEY (lottery_id, user_id)
                    )
                """)
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS winners (
                        id SERIAL PRIMARY KEY,
                        lottery_id BIGINT NOT NULL,
                        place BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        prize_amount BIGINT NOT NULL,
                        draw_ts BIGINT NOT NULL
                    )
                """)
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS rollover_bank (
                        guild_id BIGINT PRIMARY KEY,
                        amount BIGINT NOT NULL
                    )
                """)
                
                # Lottery entries table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS lottery_entries (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        guild_id BIGINT,
                        amount BIGINT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York')
                    )
                """)
                
                # Lottery winners table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS lottery_winners (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        guild_id BIGINT,
                        amount BIGINT,
                        won_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York')
                    )
                """)
                
                # Poker game sessions table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS poker_sessions (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        guild_id BIGINT,
                        bet_amount BIGINT,
                        hand_cards TEXT,
                        dealer_cards TEXT,
                        result TEXT,
                        winnings BIGINT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York')
                    )
                """)
                
                # Poker stats table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS poker_stats (
                        guild_id BIGINT,
                        user_id BIGINT,
                        hands BIGINT NOT NULL DEFAULT 0,
                        wins BIGINT NOT NULL DEFAULT 0,
                        losses BIGINT NOT NULL DEFAULT 0,
                        pushes BIGINT NOT NULL DEFAULT 0,
                        wagered BIGINT NOT NULL DEFAULT 0,
                        net BIGINT NOT NULL DEFAULT 0,
                        PRIMARY KEY (guild_id, user_id)
                    )
                """)
                
                # Crash game bets table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS crash_bets (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        guild_id BIGINT,
                        amount BIGINT,
                        multiplier DECIMAL(10,2),
                        cashed_out BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York')
                    )
                """)
                
                # Duel Royale matches table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS duel_matches (
                        id SERIAL PRIMARY KEY,
                        challenger_id BIGINT,
                        challenged_id BIGINT,
                        guild_id BIGINT,
                        bet_amount BIGINT,
                        winner_id BIGINT,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York'),
                        completed_at TIMESTAMP WITH TIME ZONE
                    )
                """)
                
                # ================= Prediction System Tables =================
                
                # Predictions table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS predictions (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT,
                        title TEXT NOT NULL,
                        description TEXT,
                        outcome_a TEXT NOT NULL,
                        outcome_b TEXT NOT NULL,
                        status TEXT DEFAULT 'open',
                        winner TEXT,
                        embed_message_id BIGINT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York'),
                        closed_at TIMESTAMP WITH TIME ZONE,
                        created_by BIGINT,
                        created_ts BIGINT,
                        lock_ts BIGINT,
                        announce_channel_id BIGINT
                    )
                """)
                
                # Prediction bets table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS prediction_bets (
                        id SERIAL PRIMARY KEY,
                        prediction_id BIGINT,
                        user_id BIGINT,
                        guild_id BIGINT,
                        side TEXT,
                        amount BIGINT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York'),
                        FOREIGN KEY (prediction_id) REFERENCES predictions(id)
                    )
                """)
                
                # ================= System Tables =================
                
                # Migration status table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS migration_status (
                        migration_name TEXT PRIMARY KEY,
                        completed BOOLEAN DEFAULT FALSE,
                        completed_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York')
                    )
                """)
                
                # Bot settings table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS bot_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/New_York')
                    )
                """)

                # Run migrations
                await self._run_migrations(conn)

                await conn.execute("""
                CREATE TABLE IF NOT EXISTS wlottery_weeks (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    start_ts BIGINT NOT NULL,
                    end_ts   BIGINT NOT NULL,
                    base_pot BIGINT NOT NULL,
                    rolled_over_from BOOLEAN DEFAULT FALSE,
                    UNIQUE (guild_id, start_ts, end_ts)
                );
                """)
                # entries
                await conn.execute("""
                CREATE TABLE IF NOT EXISTS wlottery_entries (
                    week_id BIGINT NOT NULL REFERENCES wlottery_weeks(id) ON DELETE CASCADE,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    earned_sum BIGINT NOT NULL DEFAULT 0,
                    tickets   BIGINT NOT NULL DEFAULT 0,
                    PRIMARY KEY (week_id, guild_id, user_id)
                );
                """)
                # winners (now track status + claim window)
                await conn.execute("""
                CREATE TABLE IF NOT EXISTS wlottery_winners (
                    id BIGSERIAL PRIMARY KEY,
                    week_id BIGINT NOT NULL REFERENCES wlottery_weeks(id) ON DELETE CASCADE,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    place SMALLINT NOT NULL, 
                    pot_awarded BIGINT NOT NULL,
                    drawn_ts BIGINT NOT NULL,
                    claim_deadline_ts BIGINT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'claimed' | 'expired'
                    claimed_at_ts BIGINT
                );
                """)
                # rollover bank per guild
                await conn.execute("""
                CREATE TABLE IF NOT EXISTS wlottery_rollover_bank (
                    guild_id BIGINT PRIMARY KEY,
                    amount BIGINT NOT NULL DEFAULT 0
                );
                """)

                
                # ================= Indexes for Performance =================
                
                # User balances indexes
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_balances_guild ON user_balances(guild_id)")
                # Note: PostgreSQL doesn't support computed columns in indexes the same way
                # We'll create separate indexes for cash and bank instead
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_balances_cash ON user_balances(cash)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_balances_bank ON user_balances(bank)")
                
                # Transactions indexes
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_guild ON transactions(user_id, guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions(created_at)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(transaction_type)")
                
                # Game tables indexes
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cockfight_streaks_guild ON cockfight_streaks(guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_lottery_entries_guild ON lottery_entries(guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_poker_sessions_user ON poker_sessions(user_id, guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_poker_stats_guild ON poker_stats(guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_crash_bets_user ON crash_bets(user_id, guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_duel_matches_guild ON duel_matches(guild_id)")
                
                # Lottery indexes
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_lotteries_guild_status ON lotteries(guild_id, status)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_lottery ON tickets(lottery_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_winners_lottery ON winners(lottery_id)")
                
                # Prediction indexes
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_guild ON predictions(guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_prediction_bets_prediction ON prediction_bets(prediction_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_prediction_bets_user ON prediction_bets(user_id, guild_id)")
                
                # Add unique constraint for prediction_bets if it doesn't exist
                try:
                    await conn.execute("""
                        ALTER TABLE prediction_bets 
                        ADD CONSTRAINT unique_user_guild_bet UNIQUE (guild_id, user_id)
                    """)
                    print("✅ Added unique constraint to prediction_bets table")
                except Exception as e:
                    if "already exists" in str(e) or "duplicate key" in str(e).lower():
                        print("ℹ️ Unique constraint already exists on prediction_bets")
                    else:
                        print(f"⚠️ Could not add unique constraint: {e}")
                
                # Check if migrations have already been run
                migration_completed = await self.check_migration_status()
                if not migration_completed:
                    # Migrate existing data if needed
                    await self.migrate_role_salary()
                    await self.mark_migration_complete()
                else:
                    print("ℹ️  Database migrations already completed, skipping...")
                
                self._initialized = True

    async def _run_migrations(self, conn):
        """Run database migrations."""
        # Migration 1: Add missing columns to predictions table
        try:
            await conn.execute("""
                ALTER TABLE predictions 
                ADD COLUMN IF NOT EXISTS created_by BIGINT,
                ADD COLUMN IF NOT EXISTS created_ts BIGINT,
                ADD COLUMN IF NOT EXISTS lock_ts BIGINT,
                ADD COLUMN IF NOT EXISTS announce_channel_id BIGINT
            """)
            print("✅ Migration 1 completed: Added missing columns to predictions table")
        except Exception as e:
            print(f"⚠️ Migration 1 failed: {e}")
        
        # Migration 2: Rename prediction columns from option1/option2 to outcome_a/outcome_b
        try:
            # Check if old columns exist and new ones don't
            old_columns_exist = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name = 'predictions' AND column_name IN ('option1', 'option2')
            """)
            
            if old_columns_exist == 2:
                # Rename columns
                await conn.execute("ALTER TABLE predictions RENAME COLUMN option1 TO outcome_a")
                await conn.execute("ALTER TABLE predictions RENAME COLUMN option2 TO outcome_b")
                print("✅ Migration 2 completed: Renamed prediction columns")
            else:
                print("ℹ️ Migration 2 skipped: Columns already renamed or don't exist")
        except Exception as e:
            print(f"⚠️ Migration 2 failed: {e}")
        
        # Migration 3: Add missing columns to predictions table
        try:
            await conn.execute("""
                ALTER TABLE predictions 
                ADD COLUMN IF NOT EXISTS winner TEXT,
                ADD COLUMN IF NOT EXISTS embed_message_id BIGINT
            """)
            print("✅ Migration 3 completed: Added winner and embed_message_id columns")
        except Exception as e:
            print(f"⚠️ Migration 3 failed: {e}")
        
        # Migration 4: Update prediction_bets table to use side column
        try:
            # Check if old option column exists and side doesn't
            old_column_exists = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name = 'prediction_bets' AND column_name = 'option'
            """)
            
            side_column_exists = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name = 'prediction_bets' AND column_name = 'side'
            """)
            
            if old_column_exists == 1 and side_column_exists == 0:
                # Add side column and migrate data
                await conn.execute("ALTER TABLE prediction_bets ADD COLUMN side TEXT")
                await conn.execute("""
                    UPDATE prediction_bets 
                    SET side = CASE 
                        WHEN option = 1 THEN 'A'
                        WHEN option = 2 THEN 'B'
                        ELSE 'A'
                    END
                """)
                await conn.execute("ALTER TABLE prediction_bets DROP COLUMN option")
                print("✅ Migration 4 completed: Updated prediction_bets to use side column")
            else:
                print("ℹ️ Migration 4 skipped: Columns already updated or don't exist")
        except Exception as e:
            print(f"⚠️ Migration 4 failed: {e}")
    
    async def ensure_initialized(self):
        """Ensure database is initialized before operations."""
        if not self._initialized:
            await self.init_database()
    
    # ================= Migration Management =================
    
    async def check_migration_status(self) -> bool:
        """Check if migrations have already been completed."""
        async with self._pool.acquire() as conn:
            try:
                result = await conn.fetchval("""
                    SELECT completed FROM migration_status 
                    WHERE migration_name = $1
                """, 'unified_database_v1')
                return result is not None and result == True
            except Exception as e:
                print(f"⚠️  Error checking migration status: {e}")
                return False
    
    async def mark_migration_complete(self):
        """Mark migrations as completed."""
        async with self._pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO migration_status (migration_name, completed, completed_at)
                    VALUES ($1, $2, (NOW() AT TIME ZONE 'America/New_York'))
                    ON CONFLICT (migration_name) DO UPDATE SET 
                        completed = EXCLUDED.completed,
                        completed_at = EXCLUDED.completed_at
                """, 'unified_database_v1', True)
                print("✅ Marked unified database migration as complete")
            except Exception as e:
                print(f"⚠️  Error marking migration complete: {e}")
    
    async def migrate_role_salary(self):
        """Load role data using get_role_data() and insert/update into role_salary table."""
        role_data = get_role_data()
        if not isinstance(role_data, dict):
            print("⚠️ ROLE_DATA is not a dict.")
            return

        async with self._pool.acquire() as conn:
            for role_name, info in role_data.items():
                role_id = info.get("id")
                salary = info.get("salary")
                if role_id is None or salary is None:
                    print(f"⚠️ Skipping role '{role_name}' due to missing id or salary.")
                    continue
                await conn.execute("""
                    INSERT INTO role_salary (name, role_id, salary)
                    VALUES ($1, $2, $3)
                    ON CONFLICT(name) DO UPDATE SET role_id=EXCLUDED.role_id, salary=EXCLUDED.salary
                """, role_name, role_id, salary)
        print("✅ Migrated role salary data to unified database")
    
    async def get_role_salaries(self) -> Dict[str, Dict[str, int]]:
        """Get all role salary data."""
        await self.ensure_initialized()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT name, role_id, salary FROM role_salary")
            return {row["name"]: {"id": row["role_id"], "salary": row["salary"]} for row in rows}
    
    # ================= Currency System Methods =================
    
    async def get_user_balance(self, user_id: int, guild_id: int) -> UserBalance:
        """Get user's balance information."""
        await self.ensure_initialized()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM user_balances 
                WHERE user_id = $1 AND guild_id = $2
            """, user_id, guild_id)
            
            if row:
                return UserBalance(
                    user_id=row["user_id"],
                    guild_id=row["guild_id"],
                    cash=row["cash"],
                    bank=row["bank"],
                    total_earned=row["total_earned"],
                    total_spent=row["total_spent"],
                    crimes_committed=row["crimes_committed"],
                    crimes_succeeded=row["crimes_succeeded"],
                    robs_attempted=row["robs_attempted"],
                    robs_succeeded=row["robs_succeeded"],
                    last_work=row["last_work"],
                    last_slut=row["last_slut"],
                    last_crime=row["last_crime"],
                    last_rob=row["last_rob"],
                    last_collect=row["last_collect"]
                )
            else:
                # Create new user record
                await self.create_user(user_id, guild_id)
                return UserBalance(user_id=user_id, guild_id=guild_id)
    
    async def create_user(self, user_id: int, guild_id: int):
        """Create a new user record."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_balances (user_id, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (user_id, guild_id) DO NOTHING
            """, user_id, guild_id)
    
    async def update_user_balance(self, user_id: int, guild_id: int, 
                                cash_delta: int = 0, bank_delta: int = 0,
                                total_earned_delta: int = 0, total_spent_delta: int = 0,
                                crimes_committed_delta: int = 0, crimes_succeeded_delta: int = 0,
                                robs_attempted_delta: int = 0, robs_succeeded_delta: int = 0,
                                last_work: Optional[datetime] = None,
                                last_slut: Optional[datetime] = None,
                                last_crime: Optional[datetime] = None,
                                last_rob: Optional[datetime] = None,
                                last_collect: Optional[datetime] = None):
        """Update user's balance and stats."""
        try:
            await self.ensure_initialized()
            async with self._pool.acquire() as conn:
                # Ensure user exists
                await self.create_user(user_id, guild_id)
                
                # Build update query dynamically
                updates = []
                params = []
                param_count = 1
                
                if cash_delta != 0:
                    updates.append(f"cash = cash + ${param_count}")
                    params.append(cash_delta)
                    param_count += 1
                
                if bank_delta != 0:
                    updates.append(f"bank = bank + ${param_count}")
                    params.append(bank_delta)
                    param_count += 1
                
                if total_earned_delta != 0:
                    updates.append(f"total_earned = total_earned + ${param_count}")
                    params.append(total_earned_delta)
                    param_count += 1
                
                if total_spent_delta != 0:
                    updates.append(f"total_spent = total_spent + ${param_count}")
                    params.append(total_spent_delta)
                    param_count += 1
                
                if crimes_committed_delta != 0:
                    updates.append(f"crimes_committed = crimes_committed + ${param_count}")
                    params.append(crimes_committed_delta)
                    param_count += 1
                
                if crimes_succeeded_delta != 0:
                    updates.append(f"crimes_succeeded = crimes_succeeded + ${param_count}")
                    params.append(crimes_succeeded_delta)
                    param_count += 1
                
                if robs_attempted_delta != 0:
                    updates.append(f"robs_attempted = robs_attempted + ${param_count}")
                    params.append(robs_attempted_delta)
                    param_count += 1
                
                if robs_succeeded_delta != 0:
                    updates.append(f"robs_succeeded = robs_succeeded + ${param_count}")
                    params.append(robs_succeeded_delta)
                    param_count += 1
                
                if last_work:
                    updates.append(f"last_work = ${param_count}")
                    params.append(last_work)
                    param_count += 1
                
                if last_slut:
                    updates.append(f"last_slut = ${param_count}")
                    params.append(last_slut)
                    param_count += 1
                
                if last_crime:
                    updates.append(f"last_crime = ${param_count}")
                    params.append(last_crime)
                    param_count += 1
                
                if last_rob:
                    updates.append(f"last_rob = ${param_count}")
                    params.append(last_rob)
                    param_count += 1
                
                if last_collect:
                    updates.append(f"last_collect = ${param_count}")
                    params.append(last_collect)
                    param_count += 1
                
                if updates:
                    updates.append("updated_at = (NOW() AT TIME ZONE 'America/New_York')")
                    query = f"UPDATE user_balances SET {', '.join(updates)} WHERE user_id = ${param_count} AND guild_id = ${param_count + 1}"
                    params.extend([user_id, guild_id])
                    
                    await conn.execute(query, *params)
        except Exception as e:
            print(f"update_user_balance error: {e!r}")
            raise
    
    async def log_transaction(self, user_id: int, guild_id: int, amount: int,
                            transaction_type: str, target_user_id: Optional[int] = None,
                            success: bool = True, reason: str = ""):
        """Log a transaction."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO transactions 
                (user_id, guild_id, amount, transaction_type, target_user_id, success, reason)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, user_id, guild_id, amount, transaction_type, target_user_id, success, reason)
    
    async def get_guild_settings(self, guild_id: int) -> GuildSettings:
        """Get guild economy settings."""
        await self.ensure_initialized()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM guild_settings WHERE guild_id = $1
            """, guild_id)
            
            if row:
                return GuildSettings(
                    guild_id=row["guild_id"],
                    currency_symbol=row["currency_symbol"],
                    work_cooldown=row["work_cooldown"],
                    slut_cooldown=row["slut_cooldown"],
                    crime_cooldown=row["crime_cooldown"],
                    rob_cooldown=row["rob_cooldown"],
                    collect_cooldown=row["collect_cooldown"],
                    work_min_percent=row["work_min_percent"],
                    work_max_percent=row["work_max_percent"],
                    slut_min_percent=row["slut_min_percent"],
                    slut_max_percent=row["slut_max_percent"],
                    slut_fail_chance=row["slut_fail_chance"],
                    crime_min_percent=row["crime_min_percent"],
                    crime_max_percent=row["crime_max_percent"],
                    crime_success_rate=row["crime_success_rate"],
                    rob_min_percent=row["rob_min_percent"],
                    rob_max_percent=row["rob_max_percent"],
                    rob_success_rate=row["rob_success_rate"]
                )
            else:
                # Create default settings
                await self.create_guild_settings(guild_id)
                return GuildSettings(guild_id=guild_id)
    
    async def create_guild_settings(self, guild_id: int):
        """Create default guild settings."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO guild_settings (guild_id) VALUES ($1)
                ON CONFLICT (guild_id) DO NOTHING
            """, guild_id)
    
    async def get_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0) -> List[Tuple[int, int, int, int]]:
        """Get leaderboard (user_id, cash, bank, total)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, cash, bank, (cash + bank) as total
                FROM user_balances 
                WHERE guild_id = $1
                ORDER BY (cash + bank) DESC
                LIMIT $2 OFFSET $3
            """, guild_id, limit, offset)
            return [(row["user_id"], row["cash"], row["bank"], row["total"]) for row in rows]
    
    async def get_user_rank(self, user_id: int, guild_id: int) -> int:
        """Get user's rank in the leaderboard."""
        async with self._pool.acquire() as conn:
            rank = await conn.fetchval("""
                SELECT COUNT(*) + 1 as rank
                FROM user_balances 
                WHERE guild_id = $1 AND (cash + bank) > (
                    SELECT (cash + bank) FROM user_balances 
                    WHERE user_id = $2 AND guild_id = $3
                )
            """, guild_id, user_id, guild_id)
            return rank if rank else 1

    # ================= Game Integration Methods =================
    
    async def check_balance(self, user_id: int, guild_id: int, amount: int) -> bool:
        """Check if user has sufficient cash balance."""
        user_balance = await self.get_user_balance(user_id, guild_id)
        return user_balance.cash >= amount
    
    async def deduct_cash(self, user_id: int, guild_id: int, amount: int, reason: str = "") -> bool:
        """Deduct cash from user's balance. Returns True if successful."""
        
        if not await self.check_balance(user_id, guild_id, amount):
            return False
        
        await self.update_user_balance(
            user_id, guild_id,
            cash_delta=-amount,
            total_spent_delta=amount
        )
        
        await self.log_transaction(
            user_id, guild_id, -amount, "game_deduct", 
            success=True, reason=reason
        )
        return True
    
    async def add_cash(self, user_id: int, guild_id: int, amount: int, reason: str = ""):
        """Add cash to user's balance."""
        try:
            await self.ensure_initialized()
            await self.update_user_balance(
                user_id, guild_id,
                cash_delta=amount,
                total_earned_delta=amount
            )
            
            await self.log_transaction(
                user_id, guild_id, amount, "game_win", 
                success=True, reason=reason
            )
        except Exception as e:
            print(f"add_cash error: {e!r}")
            raise
    
    async def transfer_money(self, from_user_id: int, to_user_id: int, guild_id: int, 
                           amount: int, reason: str = "") -> bool:
        """Transfer money between users. Returns True if successful."""
        if not await self.check_balance(from_user_id, guild_id, amount):
            return False
        
        # Deduct from sender
        await self.update_user_balance(
            from_user_id, guild_id,
            cash_delta=-amount,
            total_spent_delta=amount
        )
        
        # Add to receiver
        await self.update_user_balance(
            to_user_id, guild_id,
            cash_delta=amount,
            total_earned_delta=amount
        )
        
        # Log transactions
        await self.log_transaction(
            from_user_id, guild_id, -amount, "transfer", 
            target_user_id=to_user_id, success=True, reason=f"Transfer to user: {reason}"
        )
        await self.log_transaction(
            to_user_id, guild_id, amount, "transfer", 
            target_user_id=from_user_id, success=True, reason=f"Transfer from user: {reason}"
        )
        return True

    # ================= Game-Specific Methods =================
    
    # Cockfight methods
    async def get_cockfight_streak(self, user_id: int, guild_id: int) -> int:
        """Get user's cockfight streak."""
        async with self._pool.acquire() as conn:
            streak = await conn.fetchval("""
                SELECT streak FROM cockfight_streaks WHERE user_id = $1 AND guild_id = $2
            """, user_id, guild_id)
            return streak if streak else 0
    
    async def update_cockfight_streak(self, user_id: int, guild_id: int, won: bool):
        """Update user's cockfight streak."""
        async with self._pool.acquire() as conn:
            if won:
                await conn.execute("""
                    INSERT INTO cockfight_streaks (user_id, guild_id, streak)
                    VALUES ($1, $2, 1)
                    ON CONFLICT(user_id, guild_id) DO UPDATE SET streak = cockfight_streaks.streak + 1
                """, user_id, guild_id)
            else:
                await conn.execute("""
                    INSERT INTO cockfight_streaks (user_id, guild_id, streak)
                    VALUES ($1, $2, 0)
                    ON CONFLICT(user_id, guild_id) DO UPDATE SET streak = 0
                """, user_id, guild_id)
    
    # Lottery methods
    async def add_lottery_entry(self, user_id: int, guild_id: int, amount: int):
        """Add a lottery entry."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO lottery_entries (user_id, guild_id, amount)
                VALUES ($1, $2, $3)
            """, user_id, guild_id, amount)
    
    async def get_lottery_entries(self, guild_id: int) -> List[Tuple[int, int, int]]:
        """Get all lottery entries for a guild."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, amount, created_at FROM lottery_entries 
                WHERE guild_id = $1 ORDER BY created_at DESC
            """, guild_id)
            return [(row["user_id"], row["amount"], row["created_at"]) for row in rows]
    
    async def record_lottery_winner(self, user_id: int, guild_id: int, amount: int):
        """Record a lottery winner."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO lottery_winners (user_id, guild_id, amount)
                VALUES ($1, $2, $3)
            """, user_id, guild_id, amount)
    
    # Poker methods
    async def save_poker_session(self, user_id: int, guild_id: int, bet_amount: int,
                                hand_cards: str, dealer_cards: str, result: str, winnings: int):
        """Save a poker game session."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO poker_sessions (user_id, guild_id, bet_amount, hand_cards, dealer_cards, result, winnings)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, user_id, guild_id, bet_amount, hand_cards, dealer_cards, result, winnings)
    
    # Crash game methods
    async def add_crash_bet(self, user_id: int, guild_id: int, amount: int, multiplier: float = 0.0):
        """Add a crash game bet."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO crash_bets (user_id, guild_id, amount, multiplier)
                VALUES ($1, $2, $3, $4)
            """, user_id, guild_id, amount, multiplier)
    
    async def update_crash_bet(self, bet_id: int, cashed_out: bool, multiplier: float):
        """Update a crash bet."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                UPDATE crash_bets SET cashed_out = $1, multiplier = $2 WHERE id = $3
            """, cashed_out, multiplier, bet_id)
    
    # Duel Royale methods
    async def create_duel_match(self, challenger_id: int, challenged_id: int, guild_id: int, bet_amount: int) -> int:
        """Create a new duel match."""
        async with self._pool.acquire() as conn:
            match_id = await conn.fetchval("""
                INSERT INTO duel_matches (challenger_id, challenged_id, guild_id, bet_amount)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            """, challenger_id, challenged_id, guild_id, bet_amount)
            return match_id
    
    async def update_duel_match(self, match_id: int, winner_id: int, status: str = "completed"):
        """Update a duel match result."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                UPDATE duel_matches SET winner_id = $1, status = $2, completed_at = NOW()
                WHERE id = $3
            """, winner_id, status, match_id)
    
    # Prediction system methods
    async def create_prediction_old(self, guild_id: int, title: str, description: str, 
                              option1: str, option2: str) -> int:
        """Create a new prediction (old method - kept for compatibility)."""
        async with self._pool.acquire() as conn:
            prediction_id = await conn.fetchval("""
                INSERT INTO predictions (guild_id, title, description, outcome_a, outcome_b)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, guild_id, title, description, option1, option2)
            return prediction_id
    
    async def add_prediction_bet_old(self, prediction_id: int, user_id: int, guild_id: int, 
                                option: int, amount: int):
        """Add a prediction bet (old method - kept for compatibility)."""
        async with self._pool.acquire() as conn:
            side = "A" if option == 1 else "B"
            await conn.execute("""
                INSERT INTO prediction_bets (prediction_id, user_id, guild_id, side, amount)
                VALUES ($1, $2, $3, $4, $5)
            """, prediction_id, user_id, guild_id, side, amount)
    
    async def close_prediction(self, prediction_id: int, winner: str):
        """Close a prediction."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                UPDATE predictions SET status = 'resolved', winner = $1, closed_at = NOW()
                WHERE id = $2
            """, winner, prediction_id)
    
    # ================= Prediction System Methods =================
    
    async def get_current_prediction(self, guild_id: int):
        """Get current prediction for guild."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM predictions 
                WHERE guild_id = $1 AND status IN ('open', 'locked')
                ORDER BY created_at DESC 
                LIMIT 1
            """, guild_id)
            return dict(row) if row else None
    
    async def get_prediction_pools(self, guild_id: int):
        """Get betting pools for guild."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT side, SUM(amount) as total 
                FROM prediction_bets 
                WHERE guild_id = $1 
                GROUP BY side
            """, guild_id)
            
            pool_a = pool_b = 0
            for row in rows:
                if row["side"] == "A":
                    pool_a = row["total"]
                elif row["side"] == "B":
                    pool_b = row["total"]
            return pool_a or 0, pool_b or 0
    
    async def get_prediction_unique_bettors(self, guild_id: int) -> int:
        """Get number of unique bettors for guild."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(DISTINCT user_id) as count 
                FROM prediction_bets 
                WHERE guild_id = $1
            """, guild_id)
            return row["count"] if row else 0
    
    async def get_user_prediction_bet(self, guild_id: int, user_id: int):
        """Get a user's current bet for this prediction."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT side, amount 
                FROM prediction_bets 
                WHERE guild_id = $1 AND user_id = $2
            """, guild_id, user_id)
            return dict(row) if row else None
    
    async def get_prediction_bettor_counts(self, guild_id: int):
        """Return (count_A, count_B, total_unique_bettors)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT side, COUNT(DISTINCT user_id) AS count 
                FROM prediction_bets 
                WHERE guild_id = $1 
                GROUP BY side
            """, guild_id)
            
            a = b = 0
            total = 0
            for row in rows:
                if row["side"] == "A":
                    a = row["count"]
                elif row["side"] == "B":
                    b = row["count"]
                total += row["count"]
            return a, b, total
    
    async def add_prediction_bet(self, guild_id: int, user_id: int, side: str, amount: int):
        """Add or update a prediction bet."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO prediction_bets (guild_id, user_id, side, amount)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, user_id) 
                DO UPDATE SET side = EXCLUDED.side, amount = EXCLUDED.amount
            """, guild_id, user_id, side, amount)
    
    async def get_prediction_bets(self, guild_id: int):
        """Get all bets for a prediction."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, amount, side 
                FROM prediction_bets 
                WHERE guild_id = $1
            """, guild_id)
            return [dict(row) for row in rows]
    
    async def get_winning_bets(self, guild_id: int, winner: str):
        """Get all winning bets for a prediction."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, amount 
                FROM prediction_bets 
                WHERE guild_id = $1 AND side = $2
            """, guild_id, winner)
            return [dict(row) for row in rows]
    
    async def clear_prediction_bets(self, guild_id: int):
        """Clear all bets for a prediction."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM prediction_bets 
                WHERE guild_id = $1
            """, guild_id)
    
    async def update_prediction_status(self, guild_id: int, status: str, winner: str = None):
        """Update prediction status."""
        async with self._pool.acquire() as conn:
            if winner:
                await conn.execute("""
                    UPDATE predictions 
                    SET status = $1, winner = $2 
                    WHERE guild_id = $3
                """, status, winner, guild_id)
            else:
                await conn.execute("""
                    UPDATE predictions 
                    SET status = $1 
                    WHERE guild_id = $2
                """, status, guild_id)
    
    async def get_predictions_to_lock(self, current_time: int):
        """Get predictions that need to be locked."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT guild_id, announce_channel_id 
                FROM predictions 
                WHERE status = 'open' AND lock_ts <= $1
            """, current_time)
            return [dict(row) for row in rows]
    
    async def update_prediction_embed_message(self, guild_id: int, message_id: int):
        """Update prediction embed message ID."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                UPDATE predictions 
                SET embed_message_id = $1 
                WHERE guild_id = $2
            """, message_id, guild_id)
    
    async def create_prediction(self, guild_id: int, title: str, outcome_a: str, outcome_b: str, 
                               created_by: int, created_ts: int, lock_ts: int, announce_channel_id: int):
        """Create a new prediction."""
        async with self._pool.acquire() as conn:
            # Clear any existing predictions for this guild
            await conn.execute("DELETE FROM predictions WHERE guild_id = $1", guild_id)
            await conn.execute("DELETE FROM prediction_bets WHERE guild_id = $1", guild_id)
            
            # Create new prediction
            await conn.execute("""
                INSERT INTO predictions 
                (guild_id, title, outcome_a, outcome_b, status, created_by, created_ts, lock_ts, announce_channel_id)
                VALUES ($1, $2, $3, $4, 'open', $5, $6, $7, $8)
            """, guild_id, title, outcome_a, outcome_b, created_by, created_ts, lock_ts, announce_channel_id)
    
    # ================= Utility Methods =================
    
    async def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        async with self._pool.acquire() as conn:
            stats = {}
            
            # Count records in each table
            tables = [
                'user_balances', 'transactions', 'guild_settings', 'role_salary',
                'cockfight_streaks', 'lottery_entries', 'lottery_winners', 'poker_sessions',
                'crash_bets', 'duel_matches', 'predictions', 'prediction_bets'
            ]
            
            for table in tables:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                stats[table] = count if count else 0
            
            return stats
    
    async def cleanup_old_data(self, days: int = 30):
        """Clean up old data older than specified days."""
        est = pytz.timezone('America/New_York')
        cutoff_date = datetime.now(est) - timedelta(days=days)
        
        async with self._pool.acquire() as conn:
            # Clean up old transactions
            await conn.execute("""
                DELETE FROM transactions WHERE created_at < $1
            """, cutoff_date)
            
            # Clean up old lottery entries
            await conn.execute("""
                DELETE FROM lottery_entries WHERE created_at < $1
            """, cutoff_date)
            
            # Clean up old poker sessions
            await conn.execute("""
                DELETE FROM poker_sessions WHERE created_at < $1
            """, cutoff_date)
            
            # Clean up old crash bets
            await conn.execute("""
                DELETE FROM crash_bets WHERE created_at < $1
            """, cutoff_date)
            
            print(f"✅ Cleaned up data older than {days} days")
    
    async def close(self):
        """Close the database connection pool."""
        if self._pool:
            await self._pool.close()
            print("✅ Database connection pool closed")