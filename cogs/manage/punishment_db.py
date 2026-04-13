# cogs/manage/punishment_db.py

import sqlite3
import datetime
import os

# --- 配置常量 ---
DB_PATH = "./data/punishments.db"

class PunishmentDB:
    def __init__(self, db_path=DB_PATH):
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS strikes (
                user_id INTEGER PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_updated TIMESTAMP
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ad_signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT UNIQUE,
                source_url TEXT,
                created_by INTEGER,
                created_at TIMESTAMP,
                hit_count INTEGER DEFAULT 0,
                last_hit TIMESTAMP
            )
        """)
        self.conn.commit()

    def add_strike(self, user_id: int):
        self.cursor.execute("""
            INSERT INTO strikes (user_id, count, last_updated)
            VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            count = count + 1,
            last_updated = ?
        """, (user_id, datetime.datetime.now(), datetime.datetime.now()))
        self.conn.commit()
        return self.get_strikes(user_id)

    def get_strikes(self, user_id: int) -> int:
        self.cursor.execute("SELECT count FROM strikes WHERE user_id = ?", (user_id,))
        res = self.cursor.fetchone()
        return res[0] if res else 0

    def reset_strikes(self, user_id: int):
        self.cursor.execute("DELETE FROM strikes WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def add_ad_signature(self, pattern: str, source_url: str | None = None, created_by: int | None = None) -> bool:
        now = datetime.datetime.now()
        try:
            self.cursor.execute(
                """
                INSERT INTO ad_signatures (pattern, source_url, created_by, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (pattern, source_url, created_by, now),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def list_ad_signatures(self) -> list[str]:
        self.cursor.execute("SELECT pattern FROM ad_signatures ORDER BY id ASC")
        rows = self.cursor.fetchall()
        return [row[0] for row in rows]

    def mark_ad_signature_hit(self, pattern: str):
        now = datetime.datetime.now()
        self.cursor.execute(
            """
            UPDATE ad_signatures
            SET hit_count = hit_count + 1,
                last_hit = ?
            WHERE pattern = ?
            """,
            (now, pattern),
        )
        self.conn.commit()

# 创建一个全局数据库实例，供其他模块调用
db = PunishmentDB()