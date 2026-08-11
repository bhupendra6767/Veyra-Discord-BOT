import os
import aiosqlite
import asyncio
from typing import List, Tuple, Any, Optional, AsyncGenerator
from contextlib import asynccontextmanager

from logger import get_logger
from errors import DatabaseError

log = get_logger("DATABASE")

# Determine absolute path to the database file in the root directory
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(ROOT_DIR, "veyra.db")

# Migration registry (version_number, sql_script)
MIGRATIONS: List[Tuple[int, str]] = [
    (1, """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """),
    (2, """
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (guild_id, key)
        );
    """),
    (3, """
        CREATE TABLE IF NOT EXISTS server_layout (
            guild_id INTEGER NOT NULL,
            object_type TEXT NOT NULL,
            object_name TEXT NOT NULL,
            discord_id INTEGER NOT NULL,
            parent_id INTEGER,
            PRIMARY KEY (guild_id, object_type, object_name)
        );
        CREATE TABLE IF NOT EXISTS role_hierarchy (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            role_level INTEGER NOT NULL,
            description TEXT,
            PRIMARY KEY (guild_id, role_id)
        );
        CREATE TABLE IF NOT EXISTS verification_settings (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            role_id INTEGER,
            rules_text TEXT,
            active BOOLEAN NOT NULL DEFAULT 0
        );
    """),
    (4, """
        CREATE TABLE IF NOT EXISTS ticket_settings (
            guild_id INTEGER PRIMARY KEY,
            category_id INTEGER,
            log_channel_id INTEGER,
            active BOOLEAN NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tickets (
            guild_id INTEGER NOT NULL,
            ticket_id TEXT NOT NULL,
            channel_id INTEGER,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            closed_at TIMESTAMP,
            PRIMARY KEY (guild_id, ticket_id)
        );
        CREATE TABLE IF NOT EXISTS ticket_members (
            guild_id INTEGER NOT NULL,
            ticket_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, ticket_id, user_id)
        );
    """),
    (5, """
        CREATE TABLE IF NOT EXISTS security_settings (
            guild_id INTEGER NOT NULL,
            feature TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 0,
            threshold INTEGER,
            window_seconds INTEGER,
            severity TEXT,
            action TEXT,
            PRIMARY KEY (guild_id, feature)
        );
        CREATE TABLE IF NOT EXISTS whitelist (
            guild_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            reason TEXT,
            actor_id INTEGER,
            timestamp TIMESTAMP NOT NULL,
            expiration TIMESTAMP,
            active BOOLEAN NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, entity_id)
        );
        CREATE TABLE IF NOT EXISTS security_incidents (
            guild_id INTEGER NOT NULL,
            incident_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            target_id INTEGER,
            actor_id INTEGER,
            evidence TEXT,
            severity TEXT,
            status TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            PRIMARY KEY (guild_id, incident_id)
        );
        CREATE TABLE IF NOT EXISTS security_actions (
            guild_id INTEGER NOT NULL,
            action_id TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            target_id INTEGER,
            timestamp TIMESTAMP NOT NULL,
            success BOOLEAN NOT NULL,
            PRIMARY KEY (guild_id, action_id)
        );
        CREATE TABLE IF NOT EXISTS punishments (
            guild_id INTEGER NOT NULL,
            punishment_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            reason TEXT,
            actor_id INTEGER,
            timestamp TIMESTAMP NOT NULL,
            expires_at TIMESTAMP,
            active BOOLEAN NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, punishment_id)
        );
    """),
    (6, """
        CREATE TABLE IF NOT EXISTS automation_jobs (
            guild_id INTEGER NOT NULL,
            job_id TEXT NOT NULL,
            name TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL,
            next_run TIMESTAMP,
            last_run TIMESTAMP,
            failure_count INTEGER NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            state TEXT NOT NULL,
            PRIMARY KEY (guild_id, job_id)
        );
        CREATE TABLE IF NOT EXISTS automation_executions (
            guild_id INTEGER NOT NULL,
            job_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            status TEXT NOT NULL,
            logs TEXT,
            PRIMARY KEY (guild_id, execution_id)
        );
    """),
    (7, """
        CREATE TABLE IF NOT EXISTS content_sources (
            guild_id INTEGER NOT NULL,
            source_id TEXT NOT NULL,
            type TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, source_id)
        );
        CREATE TABLE IF NOT EXISTS content_items (
            guild_id INTEGER NOT NULL,
            item_hash TEXT NOT NULL,
            source_id TEXT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TIMESTAMP,
            category TEXT,
            PRIMARY KEY (guild_id, item_hash)
        );
    """),
    (8, """
        CREATE TABLE IF NOT EXISTS analytics_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            user_id INTEGER,
            metadata TEXT,
            timestamp TIMESTAMP NOT NULL
        );
    """),
    (9, """
        CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(guild_id, user_id);
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(guild_id, status);
        CREATE INDEX IF NOT EXISTS idx_automation_next_run ON automation_jobs(guild_id, next_run, enabled);
        CREATE INDEX IF NOT EXISTS idx_content_items_source ON content_items(guild_id, source_id);
        CREATE INDEX IF NOT EXISTS idx_analytics_guild_event ON analytics_events(guild_id, event_type);
        CREATE INDEX IF NOT EXISTS idx_analytics_timestamp ON analytics_events(guild_id, timestamp);
    """),
    (10, """
        CREATE TABLE IF NOT EXISTS member_lifecycle (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TIMESTAMP,
            left_at TIMESTAMP,
            PRIMARY KEY (guild_id, user_id)
        );
    """),
    (11, """
        CREATE TABLE IF NOT EXISTS analytics_daily_metrics (
            guild_id INTEGER NOT NULL,
            date DATE NOT NULL,
            metric_name TEXT NOT NULL,
            value INTEGER NOT NULL,
            PRIMARY KEY (guild_id, date, metric_name)
        );
        CREATE INDEX IF NOT EXISTS idx_member_lifecycle_dates ON member_lifecycle(guild_id, joined_at, left_at);
    """),
    (12, """
        ALTER TABLE content_sources ADD COLUMN target_channel_id INTEGER;
        ALTER TABLE content_sources ADD COLUMN config_json TEXT;
        ALTER TABLE content_sources ADD COLUMN last_fetch TIMESTAMP;
        ALTER TABLE content_sources ADD COLUMN last_success TIMESTAMP;
        ALTER TABLE content_sources ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE content_sources ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE content_sources ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        
        ALTER TABLE content_items ADD COLUMN external_id TEXT;
        ALTER TABLE content_items ADD COLUMN author TEXT;
        ALTER TABLE content_items ADD COLUMN content_type TEXT;
        ALTER TABLE content_items ADD COLUMN description TEXT;
        ALTER TABLE content_items ADD COLUMN thumbnail_url TEXT;
        ALTER TABLE content_items ADD COLUMN tags TEXT;
        ALTER TABLE content_items ADD COLUMN version TEXT;
        ALTER TABLE content_items ADD COLUMN discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE content_items ADD COLUMN discord_published BOOLEAN NOT NULL DEFAULT 0;
        ALTER TABLE content_items ADD COLUMN discord_message_id INTEGER;
    """)
]

class DatabaseManager:
    """Manages SQLite database connection, migrations, queries, and transactions."""
    def __init__(self):
        self.db: aiosqlite.Connection | None = None
        self._migration_lock = asyncio.Lock()
        self._transaction_lock = asyncio.Lock()

    async def connect(self):
        """Initializes the database connection and verifies the path is writable."""
        if self.db is not None:
            return

        # Ensure directory is writable before connecting
        if not os.access(ROOT_DIR, os.W_OK):
            log.error(f"Root directory {ROOT_DIR} is not writable. Cannot create/open database.")
            raise PermissionError(f"Directory not writable: {ROOT_DIR}")

        log.info(f"Connecting to database at {DB_PATH}")
        # Use isolation_level=None for manual transaction control
        self.db = await aiosqlite.connect(DB_PATH, isolation_level=None)
        self.db.row_factory = aiosqlite.Row
        
        # Configure SQLite pragmas for safety and performance
        await self.db.execute("PRAGMA journal_mode=WAL;")
        await self.db.execute("PRAGMA foreign_keys=ON;")
        await self.db.execute("PRAGMA synchronous=NORMAL;")
        
        await self._run_migrations()
        await self._integrity_check()

    async def _get_current_version(self) -> int:
        """Gets the current schema version from the database."""
        if not self.db:
            return 0
        try:
            async with self.db.execute("SELECT MAX(version) FROM schema_migrations") as cursor:
                result = await cursor.fetchone()
                return result[0] if result and result[0] is not None else 0
        except aiosqlite.OperationalError:
            # Table doesn't exist yet
            return 0

    async def _run_migrations(self):
        """Executes pending migrations safely using a lock and transactions."""
        if not self.db:
            raise DatabaseError("Database not connected.")
            
        async with self._migration_lock:
            current_version = await self._get_current_version()
            pending_migrations = [m for m in MIGRATIONS if m[0] > current_version]
            
            if not pending_migrations:
                log.info(f"Database schema is up to date (version {current_version}).")
                return
                
            log.info(f"Found {len(pending_migrations)} pending migrations.")
            
            for version, script in pending_migrations:
                log.info(f"Applying migration version {version}...")
                try:
                    await self.db.execute("BEGIN TRANSACTION;")
                    # Execute script commands
                    for statement in script.split(';'):
                        stmt = statement.strip()
                        if stmt:
                            await self.db.execute(stmt)
                            
                    # Record migration
                    await self.db.execute("INSERT INTO schema_migrations (version) VALUES (?);", (version,))
                    await self.db.execute("COMMIT;")
                    log.info(f"Successfully applied migration {version}.")
                except Exception as e:
                    await self.db.execute("ROLLBACK;")
                    log.critical(f"Failed to apply migration {version}: {e}")
                    raise DatabaseError(f"Migration {version} failed") from e

    async def _integrity_check(self):
        """Runs the SQLite integrity check to ensure database health."""
        if not self.db:
            raise DatabaseError("Database not connected.")
            
        log.info("Running database integrity check...")
        try:
            async with self.db.execute("PRAGMA integrity_check;") as cursor:
                result = await cursor.fetchone()
                if result and result[0].lower() == "ok":
                    log.info("Database integrity check passed.")
                else:
                    log.error(f"Database integrity check failed: {result[0] if result else 'Unknown error'}")
        except Exception as e:
            log.error(f"Error during integrity check: {e}")
            raise DatabaseError("Integrity check error") from e

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """
        Context manager for safe explicit transactions.
        Nested transactions are NOT supported natively by this context manager to avoid 
        complex savepoint management and deadlocks. Do not nest `async with db.transaction():`
        """
        if not self.db:
            raise DatabaseError("Database is not connected.")

        async with self._transaction_lock:
            try:
                await self.db.execute("BEGIN TRANSACTION;")
                yield self.db
                await self.db.execute("COMMIT;")
            except Exception as e:
                await self.db.execute("ROLLBACK;")
                log.warning(f"Transaction rolled back due to error: {e}")
                raise DatabaseError("Transaction failed and was rolled back.") from e

    async def fetch_one(self, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        """Fetches a single row from the database."""
        if not self.db:
            raise DatabaseError("Database is not connected.")
        try:
            async with self.db.execute(query, params) as cursor:
                return await cursor.fetchone()
        except Exception as e:
            raise DatabaseError(f"Query failed: {e}") from e

    async def fetch_all(self, query: str, params: tuple = ()) -> List[aiosqlite.Row]:
        """Fetches multiple rows from the database."""
        if not self.db:
            raise DatabaseError("Database is not connected.")
        try:
            async with self.db.execute(query, params) as cursor:
                return await cursor.fetchall()
        except Exception as e:
            raise DatabaseError(f"Query failed: {e}") from e

    async def execute(self, query: str, params: tuple = ()) -> int:
        """Executes a single modifying query and returns the number of affected rows."""
        if not self.db:
            raise DatabaseError("Database is not connected.")
        try:
            async with self.transaction():
                async with self.db.execute(query, params) as cursor:
                    return cursor.rowcount
        except Exception as e:
            raise DatabaseError(f"Execute failed: {e}") from e


    async def backup(self, dest_path: str):
        """Safely backs up the database using SQLite's native backup API."""
        if not self.db:
            raise DatabaseError("Database is not connected.")
        log.info(f"Starting database backup to {dest_path}...")
        try:
            async with aiosqlite.connect(dest_path) as dest:
                await self.db.backup(dest)
            log.info(f"Database backup completed successfully to {dest_path}.")
        except Exception as e:
            log.error(f"Database backup failed: {e}")
            raise DatabaseError(f"Backup failed: {e}") from e

    async def close(self):
        """Gracefully closes the database connection."""
        if self.db is not None:
            log.info("Closing database connection.")
            try:
                await self.db.close()
            except Exception as e:
                log.error(f"Error while closing database: {e}")
            finally:
                self.db = None

db = DatabaseManager()
