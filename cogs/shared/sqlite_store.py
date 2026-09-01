import copy
import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_STATE_DB_FILE = "data/app_state.sqlite3"
_SCHEMA_LOCK = threading.RLock()
_SCHEMA_READY = False


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@contextmanager
def _connection():
    os.makedirs(os.path.dirname(APP_STATE_DB_FILE), exist_ok=True)
    connection = sqlite3.connect(APP_STATE_DB_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with _connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS json_namespaces (
                       namespace TEXT PRIMARY KEY,
                       payload TEXT NOT NULL,
                       migrated_from TEXT NOT NULL DEFAULT '',
                       updated_at TEXT NOT NULL
                   )"""
            )
        _SCHEMA_READY = True


def initialize_app_state_storage() -> None:
    _ensure_schema()


def migrate_runtime_json_namespaces() -> None:
    """启动期导入所有增长型运行数据；人工维护的配置 JSON 不在此列。"""
    try:
        import config
        ticket_quota_default = {
            "last_reset_date": "2000-01-01",
            "daily_quota_left": config.QUOTA["DAILY_TICKET_LIMIT"],
        }
        quota_file = config.QUOTA["QUOTA_FILE_PATH"]
    except (AttributeError, KeyError, ImportError):
        ticket_quota_default = {"last_reset_date": "2000-01-01", "daily_quota_left": 50}
        quota_file = "quota_data.json"

    specs = (
        (
            "egg_qa",
            "data/egg_qa.json",
            {
                "version": 3,
                "questions": {},
                "panels": {},
                "author_subscriptions": {},
                "daily_question_counts": {},
                "daily_reply_totals": {},
            },
        ),
        (
            "submissions",
            "data/submissions.json",
            {
                "version": 1,
                "panel_info": {},
                "submissions": {},
                "comment_rewards": {},
                "meaningless_submission_users": {},
            },
        ),
        ("red_packets", "data/red_packets.json", {"version": 1, "packets": {}}),
        ("prequiz_attempts", "data/prequiz_attempts.json", {"version": 1, "attempts": {}}),
        ("boost_thanks", "data/boost_thanks.json", {"version": 1, "processed": {}}),
        ("general_lottery", "data/general_lottery.json", {"active_lotteries": {}}),
        ("server_daily_reports", "data/server_daily_reports.json", {"version": 1, "guilds": {}}),
        ("manage_complaint_notice_cache", "data/manage_complaint_notice_cache.json", {}),
        ("role_collection_rewards", "data/role_collection_rewards.json", {}),
        ("ticket_quota", quota_file, ticket_quota_default),
        ("ticket_audit_schedule", "data/audit_schedule.json", {"suspended": False, "reason": None, "start_dt": None, "end_dt": None}),
    )
    for namespace, legacy_file, default in specs:
        load_json_namespace(namespace, legacy_file=legacy_file, default=default)


def _read_legacy(path: str | os.PathLike[str] | None, default: Any) -> Any:
    if not path:
        return copy.deepcopy(default)
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def load_json_namespace(
    namespace: str,
    *,
    legacy_file: str | os.PathLike[str] | None,
    default: Any,
) -> Any:
    """读取一个运行时数据域；首次读取时自动导入其旧 JSON。"""
    _ensure_schema()
    with _connection() as connection:
        row = connection.execute(
            "SELECT payload FROM json_namespaces WHERE namespace=?", (str(namespace),)
        ).fetchone()
        if row is not None:
            try:
                return json.loads(row["payload"])
            except json.JSONDecodeError:
                return copy.deepcopy(default)

        value = _read_legacy(legacy_file, default)
        source = str(legacy_file or "")
        connection.execute(
            """INSERT INTO json_namespaces(namespace, payload, migrated_from, updated_at)
               VALUES (?, ?, ?, ?)""",
            (str(namespace), _dump(value), source, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        if legacy_file and Path(legacy_file).exists():
            backup = Path(f"{legacy_file}.pre_sqlite.bak")
            if not backup.exists():
                shutil.copy2(legacy_file, backup)
        return value


def save_json_namespace(namespace: str, value: Any) -> None:
    """事务性覆盖单个数据域，不影响同一数据库中的其他模块。"""
    _ensure_schema()
    with _connection() as connection:
        connection.execute(
            """INSERT INTO json_namespaces(namespace, payload, migrated_from, updated_at)
               VALUES (?, ?, '', ?)
               ON CONFLICT(namespace) DO UPDATE SET
                   payload=excluded.payload,
                   updated_at=excluded.updated_at""",
            (str(namespace), _dump(value), datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
