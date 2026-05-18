import asyncio
import os
import sqlite3
import threading
import time


class ScamDB:
    def __init__(self, db_path: str = "./data/scam_blocker.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous  = NORMAL;

                CREATE TABLE IF NOT EXISTS message_logs (
                    message_id  INTEGER PRIMARY KEY,
                    user_id     INTEGER,
                    channel_id  INTEGER,
                    timestamp   REAL
                );
                CREATE INDEX IF NOT EXISTS idx_logs_user ON message_logs(user_id);
                CREATE INDEX IF NOT EXISTS idx_logs_ts   ON message_logs(timestamp);

                CREATE TABLE IF NOT EXISTS regex_rules (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern  TEXT UNIQUE,
                    added_by INTEGER,
                    added_at REAL
                );
                """
            )

    def _exec(self, sql: str, params=()):
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _query(self, sql: str, params=()) -> list:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    async def log_message(self, message_id: int, user_id: int, channel_id: int):
        await asyncio.to_thread(
            self._exec,
            "INSERT OR IGNORE INTO message_logs (message_id, user_id, channel_id, timestamp) VALUES (?, ?, ?, ?)",
            (message_id, user_id, channel_id, time.time()),
        )

    async def get_user_messages(self, user_id: int) -> list:
        return await asyncio.to_thread(
            self._query,
            "SELECT message_id, channel_id FROM message_logs WHERE user_id = ?",
            (user_id,),
        )

    async def delete_user_logs(self, user_id: int):
        await asyncio.to_thread(
            self._exec,
            "DELETE FROM message_logs WHERE user_id = ?",
            (user_id,),
        )

    async def clean_old_logs(self, keep_seconds: int = 21600):
        await asyncio.to_thread(
            self._exec,
            "DELETE FROM message_logs WHERE timestamp < ?",
            (time.time() - keep_seconds,),
        )

    async def add_rule(self, pattern: str, author_id: int) -> bool:
        try:
            await asyncio.to_thread(
                self._exec,
                "INSERT INTO regex_rules (pattern, added_by, added_at) VALUES (?, ?, ?)",
                (pattern, author_id, time.time()),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    async def get_all_rules(self) -> list:
        return await asyncio.to_thread(
            self._query,
            "SELECT id, pattern FROM regex_rules ORDER BY id ASC",
        )

    async def delete_rule(self, rule_id: int):
        await asyncio.to_thread(
            self._exec,
            "DELETE FROM regex_rules WHERE id = ?",
            (rule_id,),
        )


scam_db = ScamDB()
