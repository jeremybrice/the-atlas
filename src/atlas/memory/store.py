"""SQLite database connection and schema management for ATLAS."""

from __future__ import annotations

import aiosqlite


class DatabaseStore:
    """Manages the single ATLAS SQLite database."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._db

    async def _create_tables(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                episode_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                episode_type TEXT NOT NULL,
                trigger_text TEXT,
                plan TEXT,
                actions TEXT,
                outcome TEXT,
                lessons TEXT,
                mission_id TEXT,
                task_id TEXT,
                tags TEXT,
                correlation_id TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                episode_id,
                trigger_text,
                plan,
                outcome,
                lessons,
                content=episodes,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                INSERT INTO episodes_fts(episode_id, trigger_text, plan, outcome, lessons)
                VALUES (new.episode_id, new.trigger_text, new.plan, new.outcome, new.lessons);
            END;

            CREATE TABLE IF NOT EXISTS audit_log (
                entry_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                correlation_id TEXT,
                actor TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_details TEXT NOT NULL,
                policy_decision TEXT,
                outcome TEXT NOT NULL,
                mission_id TEXT,
                task_id TEXT
            );

            CREATE TABLE IF NOT EXISTS missions (
                mission_id TEXT PRIMARY KEY,
                goal_text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_list TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                mission_id TEXT,
                description TEXT NOT NULL,
                task_type TEXT NOT NULL,
                skill_id TEXT,
                input_params TEXT,
                expected_outcome TEXT,
                status TEXT NOT NULL,
                result TEXT,
                priority INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trust_records (
                skill_id TEXT PRIMARY KEY,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                consecutive_successes INTEGER DEFAULT 0,
                total_invocations INTEGER DEFAULT 0,
                autonomy_override TEXT,
                last_outcome TEXT,
                updated_at TEXT NOT NULL,
                recent_outcomes TEXT
            );

            CREATE TABLE IF NOT EXISTS credentials (
                service TEXT NOT NULL,
                key TEXT NOT NULL,
                encrypted_value BLOB NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (service, key)
            );

            CREATE TABLE IF NOT EXISTS vault_meta (
                key TEXT PRIMARY KEY,
                value BLOB NOT NULL
            );

            CREATE TABLE IF NOT EXISTS entity_mappings (
                service TEXT NOT NULL,
                external_id TEXT NOT NULL,
                atlas_type TEXT NOT NULL,
                atlas_id TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (service, external_id)
            );

            CREATE INDEX IF NOT EXISTS idx_entity_atlas
                ON entity_mappings(atlas_type, atlas_id);
        """)
        await self._db.commit()
