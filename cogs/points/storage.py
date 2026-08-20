# cogs/points/storage.py

import json
import math
import os
import random
import shutil
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from typing import Any

import config

POINTS_DATA_FILE = "data/user_points.json"
POINTS_DB_FILE = "data/user_points.sqlite3"
RANDOM_EVENTS_FILE = Path(__file__).with_name("random_events.json")
PRAISE_RULES_FILE = "data/praise_rules.json"
TZ_CN = timezone(timedelta(hours=8))

SHELL_PRECISION = 1
LEGACY_POINTS_TO_SHELLS = 0.1
_POINTS_DATA_LOCK = threading.RLock()
_POINTS_DB_READY = False
_RANDOM_EVENTS_CACHE: list[dict] | None = None
_RANDOM_EVENTS_MTIME_NS = -1
_PRAISE_RULES_LOCK = threading.RLock()

DEFAULT_MONTHLY_CARD_CONFIG = {
    "enabled": True,
    "price": 30.0,
    "duration_days": 30,
    "daily_reward": 10.0,
    "reward_multiplier": 1.5,
    "max_cards": 3,
}


def _default_praise_rule() -> dict:
    return {
        "id": "default_kimi_praise",
        "field": str(getattr(config, "PRAISE_KIMI_TRIGGER", "赞美奇米蛋！") or "赞美奇米蛋！").strip(),
        "match_mode": "exact",
        "min_reward": 1.0,
        "max_reward": 9.0,
        "start_at": "",
        "end_at": "",
    }


def _normalize_praise_rule(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    field = str(raw.get("field", "") or "").strip()
    if not field:
        return None
    rule_id = str(raw.get("id", "") or "").strip()[:64] or uuid.uuid4().hex[:12]
    mode = str(raw.get("match_mode", "exact") or "exact").strip().lower()
    if mode not in {"exact", "contains"}:
        mode = "exact"
    try:
        minimum = round(max(0.1, float(raw.get("min_reward", 1.0))), 1)
        maximum = round(max(0.1, float(raw.get("max_reward", minimum))), 1)
    except (TypeError, ValueError):
        minimum, maximum = 1.0, 9.0
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    return {
        "id": rule_id,
        "field": field[:200],
        "match_mode": mode,
        "min_reward": minimum,
        "max_reward": maximum,
        "start_at": str(raw.get("start_at", "") or "").strip()[:32],
        "end_at": str(raw.get("end_at", "") or "").strip()[:32],
    }


def load_praise_rules() -> list[dict]:
    with _PRAISE_RULES_LOCK:
        if not os.path.exists(PRAISE_RULES_FILE):
            return [_default_praise_rule()]
        try:
            with open(PRAISE_RULES_FILE, "r", encoding="utf-8") as file:
                raw = json.load(file)
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            return [_default_praise_rule()]
        items = raw.get("rules", []) if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return [_default_praise_rule()]
        rules, seen = [], set()
        for item in items:
            rule = _normalize_praise_rule(item)
            if rule and rule["id"] not in seen:
                seen.add(rule["id"])
                rules.append(rule)
        return rules


def save_praise_rules(rules: list[dict]) -> list[dict]:
    normalized, seen = [], set()
    for item in rules or []:
        rule = _normalize_praise_rule(item)
        if rule and rule["id"] not in seen:
            seen.add(rule["id"])
            normalized.append(rule)
    with _PRAISE_RULES_LOCK:
        os.makedirs(os.path.dirname(PRAISE_RULES_FILE), exist_ok=True)
        with open(PRAISE_RULES_FILE, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "rules": normalized}, file, indent=4, ensure_ascii=False)
    return normalized


def _parse_praise_time(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TZ_CN)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=TZ_CN) if parsed.tzinfo is None else parsed.astimezone(TZ_CN)


def _normalize_praise_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    text = "".join(text.split())
    text = text.replace("！", "!")
    return text


def match_praise_rule(content: str, occurred_at: datetime | None = None, rules: list[dict] | None = None) -> dict | None:
    raw_text = str(content or "").strip()
    text = _normalize_praise_text(raw_text)
    if not text:
        return None
    moment = occurred_at or datetime.now(TZ_CN)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TZ_CN)
    else:
        moment = moment.astimezone(TZ_CN)
    for rule in rules if rules is not None else load_praise_rules():
        start = _parse_praise_time(rule.get("start_at", ""))
        end = _parse_praise_time(rule.get("end_at", ""))
        if (start and moment < start) or (end and moment > end):
            continue
        field = _normalize_praise_text(rule.get("field", ""))
        if not field:
            continue
        matched = text == field if rule.get("match_mode") == "exact" else field in text
        if matched:
            return rule
    return None


def _locked_points_data(func):
    """Serialize complete read/modify/write operations on user_points.json."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        with _POINTS_DATA_LOCK:
            return func(*args, **kwargs)
    return wrapper


def _empty_points_data() -> dict:
    return {
        "version": 3,
        "users": {},
        "daily_signins": {},
        "daily_forum_rewards": {},
        "daily_praise_rewards": {},
        "daily_praise_scan_records": {},
        "daily_task_rewards": {},
        "transactions": [],
        "acceleration_purchases": [],
        "monthly_card_config": dict(DEFAULT_MONTHLY_CARD_CONFIG),
        "monthly_card_purchases": [],
    }

DEFAULT_RANDOM_EVENTS = {
    "version": 1,
    "events": [
        {
            "id": "fallback_positive_001",
            "type": "positive",
            "title": "小蛋发光",
            "description": "奇米蛋今天闪了一下，掉出一点亮晶晶的蛋壳。",
            "min_delta": 0.1,
            "max_delta": 1.9,
            "weight": 1,
        },
        {
            "id": "fallback_negative_001",
            "type": "negative",
            "title": "小蛋打滑",
            "description": "奇米蛋抱着蛋壳跑太快，咕噜一下滚掉了一点。",
            "min_delta": 0.1,
            "max_delta": 1.9,
            "weight": 1,
        },
        {
            "id": "fallback_neutral_001",
            "type": "neutral",
            "title": "小蛋点头",
            "description": "奇米蛋认真地点了点头，今天也有好好报到。",
            "min_delta": 0.0,
            "max_delta": 0.0,
            "weight": 1,
        },
    ],
}


def _today() -> str:
    return datetime.now(TZ_CN).date().isoformat()


def _date_cn(value: datetime | None = None) -> str:
    if value is None:
        return _today()
    moment = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return moment.astimezone(TZ_CN).date().isoformat()


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def _prune_daily_only(rows: Any) -> dict:
    if not isinstance(rows, dict):
        return {}
    today = _today()
    value = rows.get(today, {})
    return {today: value if isinstance(value, dict) else {}}


def _make_user_key(user_id: int, guild_id: int | None = None) -> str:
    if guild_id is None:
        return str(user_id)
    return f"{guild_id}:{user_id}"


def _round_shells(value: float | int | str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    return round(max(0.0, amount), SHELL_PRECISION)


def _round_delta(value: float | int | str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    return round(amount, SHELL_PRECISION)


def format_shells(value: float | int | str) -> str:
    amount = _round_shells(value)
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:.1f}"


def _normalize_monthly_card_config(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    try:
        price = max(0.1, float(raw.get("price", DEFAULT_MONTHLY_CARD_CONFIG["price"])))
        duration_days = max(1, int(raw.get("duration_days", DEFAULT_MONTHLY_CARD_CONFIG["duration_days"])))
        daily_reward = max(0.0, float(raw.get("daily_reward", DEFAULT_MONTHLY_CARD_CONFIG["daily_reward"])))
        multiplier = max(1.0, float(raw.get("reward_multiplier", DEFAULT_MONTHLY_CARD_CONFIG["reward_multiplier"])))
    except (TypeError, ValueError):
        return dict(DEFAULT_MONTHLY_CARD_CONFIG)
    return {
        "enabled": bool(raw.get("enabled", True)),
        "price": _round_delta(price),
        "duration_days": min(365, duration_days),
        "daily_reward": _round_delta(daily_reward),
        "reward_multiplier": round(min(5.0, multiplier), 2),
        "max_cards": 3,
    }


def _parse_iso_datetime(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=TZ_CN) if parsed.tzinfo is None else parsed.astimezone(TZ_CN)


def _normalize_monthly_periods(raw: Any) -> list[dict]:
    periods = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        starts_at = _parse_iso_datetime(item.get("starts_at"))
        expires_at = _parse_iso_datetime(item.get("expires_at"))
        if not starts_at or not expires_at or expires_at <= starts_at:
            continue
        try:
            reward_days = max(1, int(item.get("reward_days", round((expires_at - starts_at).total_seconds() / 86400)) or 1))
            daily_rewards_granted = max(0, int(item.get("daily_rewards_granted", 0) or 0))
        except (TypeError, ValueError):
            reward_days = max(1, round((expires_at - starts_at).total_seconds() / 86400))
            daily_rewards_granted = 0
        periods.append({
            "purchase_id": str(item.get("purchase_id", "") or uuid.uuid4().hex[:16]),
            "purchased_at": str(item.get("purchased_at", "") or starts_at.isoformat(timespec="seconds")),
            "starts_at": starts_at.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "cost": _round_delta(item.get("cost", DEFAULT_MONTHLY_CARD_CONFIG["price"])),
            "reward_days": reward_days,
            "daily_rewards_granted": min(reward_days, daily_rewards_granted),
        })
    periods.sort(key=lambda item: item["starts_at"])
    return periods


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        record = {}

    if "shells" not in record:
        legacy_points = record.get("points", 0)
        record["shells"] = _round_shells(float(legacy_points or 0) * LEGACY_POINTS_TO_SHELLS)
    else:
        record["shells"] = _round_shells(record.get("shells", 0))

    record["points"] = record["shells"]
    record.setdefault("last_sign_date", "")
    record.setdefault("streak_days", 0)
    record.setdefault("daily_msg_count", 0)
    record.setdefault("daily_msg_date", "")
    record.setdefault("daily_post_pts", 0)
    record.setdefault("daily_post_date", "")
    record.setdefault("transactions", [])
    record.setdefault("acceleration_days", 0)
    record.setdefault("acceleration_cards", [])
    record["monthly_card_periods"] = _normalize_monthly_periods(record.get("monthly_card_periods", []))
    record["monthly_card_ever_purchased"] = bool(
        record.get("monthly_card_ever_purchased", False) or record["monthly_card_periods"]
    )
    record["monthly_card_first_role_pending"] = bool(record.get("monthly_card_first_role_pending", False))
    try:
        record["monthly_card_first_role_id"] = int(record.get("monthly_card_first_role_id", 0) or 0)
    except (TypeError, ValueError):
        record["monthly_card_first_role_id"] = 0
    record.setdefault("monthly_card_last_daily_reward_date", "")
    if not isinstance(record.get("monthly_card_purchases"), list):
        record["monthly_card_purchases"] = []
    return record


def _normalize_points_data(raw_data: dict) -> dict:
    """兼容旧积分格式并统一为蛋壳结构。"""
    if not isinstance(raw_data, dict):
        return _empty_points_data()

    if "users" in raw_data and isinstance(raw_data["users"], dict):
        users = {
            key: _normalize_record(value)
            for key, value in raw_data["users"].items()
        }
        return {
            "version": 3,
            "users": users,
            "daily_signins": raw_data.get("daily_signins", {}),
            "daily_forum_rewards": raw_data.get("daily_forum_rewards", {}),
            "daily_praise_rewards": raw_data.get("daily_praise_rewards", {}),
            "daily_praise_scan_records": _prune_daily_only(raw_data.get("daily_praise_scan_records", {})),
            "daily_task_rewards": raw_data.get("daily_task_rewards", {}),
            "transactions": raw_data.get("transactions", []),
            "acceleration_purchases": raw_data.get("acceleration_purchases", []),
            "monthly_card_config": _normalize_monthly_card_config(raw_data.get("monthly_card_config")),
            "monthly_card_purchases": raw_data.get("monthly_card_purchases", []) if isinstance(raw_data.get("monthly_card_purchases", []), list) else [],
        }

    users = {}
    for uid, pts in raw_data.items():
        try:
            shells = float(pts) * LEGACY_POINTS_TO_SHELLS
        except (TypeError, ValueError):
            shells = 0.0
        users[str(uid)] = _normalize_record({"shells": shells})

    data = _empty_points_data()
    data["users"] = users
    return data


def _ensure_user_record(data: dict, user_id: int, guild_id: int | None = None) -> tuple[dict, str]:
    users = data.setdefault("users", {})
    key = _make_user_key(user_id, guild_id)
    if key not in users or not isinstance(users[key], dict):
        users[key] = {}
    users[key] = _normalize_record(users[key])
    return users[key], key


def _append_transaction(
    data: dict,
    record: dict,
    *,
    user_id: int,
    guild_id: int | None,
    amount: float,
    source: str,
    reason: str = "",
    idempotency_key: str = "",
) -> None:
    if amount == 0:
        return

    tx = {
        "time": _now_iso(),
        "guild_id": str(guild_id) if guild_id else "",
        "user_id": str(user_id),
        "amount": _round_delta(amount),
        "balance": _round_shells(record.get("shells", 0)),
        "source": source,
        "reason": reason,
    }
    if idempotency_key:
        tx["idempotency_key"] = str(idempotency_key)
    record.setdefault("transactions", []).append(tx)
    record["transactions"] = record["transactions"][-50:]
    data.setdefault("transactions", []).append(tx)
    data["transactions"] = data["transactions"][-500:]


_DICT_SECTIONS = (
    "daily_signins",
    "daily_forum_rewards",
    "daily_praise_rewards",
    "daily_praise_scan_records",
    "daily_task_rewards",
)
_LIST_SECTIONS = ("acceleration_purchases", "monthly_card_purchases")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _connect_points_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(POINTS_DB_FILE), exist_ok=True)
    connection = sqlite3.connect(POINTS_DB_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


@contextmanager
def _points_connection():
    connection = _connect_points_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _create_points_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS points_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS point_users (
            user_key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            has_monthly_card INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS point_sections (
            namespace TEXT NOT NULL,
            item_key TEXT NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY(namespace, item_key)
        );
        CREATE TABLE IF NOT EXISTS point_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            guild_id TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL,
            amount REAL NOT NULL,
            balance REAL NOT NULL,
            source TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_point_transactions_user
            ON point_transactions(guild_id, user_id, id DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_point_transactions_idempotency
            ON point_transactions(guild_id, user_id, idempotency_key)
            WHERE idempotency_key <> '';
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(point_users)")}
    if "has_monthly_card" not in columns:
        connection.execute(
            "ALTER TABLE point_users ADD COLUMN has_monthly_card INTEGER NOT NULL DEFAULT 0"
        )


def _read_legacy_points_json() -> dict:
    backup_file = f"{POINTS_DATA_FILE}.bak"
    if not os.path.exists(POINTS_DATA_FILE):
        return _empty_points_data()
    try:
        with open(POINTS_DATA_FILE, "r", encoding="utf-8") as file:
            return _normalize_points_data(json.load(file))
    except (json.JSONDecodeError, OSError) as error:
        try:
            with open(backup_file, "r", encoding="utf-8") as backup:
                recovered = _normalize_points_data(json.load(backup))
        except (json.JSONDecodeError, OSError) as backup_error:
            raise RuntimeError(
                f"积分数据文件读取失败，且备份不可用: main={error!r}; backup={backup_error!r}"
            ) from error
        print(f"[蛋壳系统] 主积分表读取失败，已从备份恢复: error={error!r}")
        return recovered


def _replace_database_snapshot(connection: sqlite3.Connection, data: dict) -> None:
    normalized = _normalize_points_data(data)
    connection.execute("DELETE FROM point_users")
    connection.execute("DELETE FROM point_sections")
    connection.execute("DELETE FROM point_transactions")
    connection.executemany(
        "INSERT INTO point_users(user_key, data, has_monthly_card) VALUES (?, ?, ?)",
        (
            (str(key), _json_dump(value), int(bool(value.get("monthly_card_periods"))))
            for key, value in normalized["users"].items()
        ),
    )
    for namespace in _DICT_SECTIONS:
        rows = normalized.get(namespace, {})
        if isinstance(rows, dict):
            connection.executemany(
                "INSERT INTO point_sections(namespace, item_key, data) VALUES (?, ?, ?)",
                ((namespace, str(key), _json_dump(value)) for key, value in rows.items()),
            )
    for namespace in _LIST_SECTIONS:
        connection.execute(
            "INSERT INTO point_sections(namespace, item_key, data) VALUES (?, 'value', ?)",
            (namespace, _json_dump(normalized.get(namespace, []))),
        )
    connection.execute(
        "INSERT INTO point_sections(namespace, item_key, data) VALUES ('config', 'monthly_card', ?)",
        (_json_dump(normalized.get("monthly_card_config", DEFAULT_MONTHLY_CARD_CONFIG)),),
    )
    for tx in normalized.get("transactions", []):
        if not isinstance(tx, dict):
            continue
        connection.execute(
            """INSERT OR IGNORE INTO point_transactions
               (time, guild_id, user_id, amount, balance, source, reason, idempotency_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(tx.get("time", "")), str(tx.get("guild_id", "")), str(tx.get("user_id", "")),
                _round_delta(tx.get("amount", 0)), _round_shells(tx.get("balance", 0)),
                str(tx.get("source", "")), str(tx.get("reason", "")), str(tx.get("idempotency_key", "")),
            ),
        )


def _ensure_points_db() -> None:
    global _POINTS_DB_READY
    if _POINTS_DB_READY:
        return
    with _POINTS_DATA_LOCK:
        if _POINTS_DB_READY:
            return
        with _points_connection() as connection:
            _create_points_schema(connection)
            migrated = connection.execute(
                "SELECT value FROM points_meta WHERE key='json_migrated'"
            ).fetchone()
            if migrated is None:
                legacy = _read_legacy_points_json()
                _replace_database_snapshot(connection, legacy)
                connection.execute(
                    "INSERT OR REPLACE INTO points_meta(key, value) VALUES ('json_migrated', ?)",
                    (_now_iso(),),
                )
                if os.path.exists(POINTS_DATA_FILE):
                    migration_backup = f"{POINTS_DATA_FILE}.pre_sqlite.bak"
                    if not os.path.exists(migration_backup):
                        shutil.copy2(POINTS_DATA_FILE, migration_backup)
                print(
                    f"[蛋壳系统] SQLite 数据库已就绪，导入用户 {len(legacy.get('users', {}))} 条；"
                    "原 JSON 已保留为迁移备份。"
                )
        _POINTS_DB_READY = True


def initialize_points_storage() -> None:
    """启动期主动完成建表/迁移，避免首次按钮交互承担迁移延迟。"""
    _ensure_points_db()


def _db_get_section(connection: sqlite3.Connection, namespace: str, item_key: str, default: Any) -> Any:
    row = connection.execute(
        "SELECT data FROM point_sections WHERE namespace=? AND item_key=?",
        (namespace, str(item_key)),
    ).fetchone()
    return _json_load(row["data"] if row else None, default)


def _db_put_section(connection: sqlite3.Connection, namespace: str, item_key: str, value: Any) -> None:
    connection.execute(
        """INSERT INTO point_sections(namespace, item_key, data) VALUES (?, ?, ?)
           ON CONFLICT(namespace, item_key) DO UPDATE SET data=excluded.data""",
        (namespace, str(item_key), _json_dump(value)),
    )


def _db_get_user(connection: sqlite3.Connection, user_id: int, guild_id: int | None) -> tuple[dict, str]:
    key = _make_user_key(user_id, guild_id)
    row = connection.execute("SELECT data FROM point_users WHERE user_key=?", (key,)).fetchone()
    return _normalize_record(_json_load(row["data"] if row else None, {})), key


def _db_put_user(connection: sqlite3.Connection, key: str, record: dict) -> None:
    normalized = _normalize_record(record)
    connection.execute(
        """INSERT INTO point_users(user_key, data, has_monthly_card) VALUES (?, ?, ?)
           ON CONFLICT(user_key) DO UPDATE SET
               data=excluded.data, has_monthly_card=excluded.has_monthly_card""",
        (key, _json_dump(normalized), int(bool(normalized.get("monthly_card_periods")))),
    )


def _db_monthly_config(connection: sqlite3.Connection) -> dict:
    return _normalize_monthly_card_config(
        _db_get_section(connection, "config", "monthly_card", DEFAULT_MONTHLY_CARD_CONFIG)
    )


def _db_append_transaction(
    connection: sqlite3.Connection,
    record: dict,
    *,
    user_id: int,
    guild_id: int | None,
    amount: float,
    source: str,
    reason: str = "",
    idempotency_key: str = "",
) -> dict | None:
    if amount == 0:
        return None
    tx = {
        "time": _now_iso(), "guild_id": str(guild_id) if guild_id else "", "user_id": str(user_id),
        "amount": _round_delta(amount), "balance": _round_shells(record.get("shells", 0)),
        "source": str(source), "reason": str(reason),
    }
    if idempotency_key:
        tx["idempotency_key"] = str(idempotency_key)
    connection.execute(
        """INSERT INTO point_transactions
           (time, guild_id, user_id, amount, balance, source, reason, idempotency_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (tx["time"], tx["guild_id"], tx["user_id"], tx["amount"], tx["balance"], tx["source"], tx["reason"], str(idempotency_key)),
    )
    record.setdefault("transactions", []).append(tx)
    record["transactions"] = record["transactions"][-50:]
    connection.execute(
        "DELETE FROM point_transactions WHERE id NOT IN (SELECT id FROM point_transactions ORDER BY id DESC LIMIT 500)"
    )
    return tx


def load_points_data():
    """兼容管理/报表调用的完整快照；高频业务不应调用此函数。"""
    _ensure_points_db()
    with _POINTS_DATA_LOCK, _points_connection() as connection:
        data = _empty_points_data()
        for row in connection.execute("SELECT user_key, data FROM point_users"):
            data["users"][row["user_key"]] = _normalize_record(_json_load(row["data"], {}))
        for namespace in _DICT_SECTIONS:
            data[namespace] = {
                row["item_key"]: _json_load(row["data"], {})
                for row in connection.execute(
                    "SELECT item_key, data FROM point_sections WHERE namespace=?", (namespace,)
                )
            }
        for namespace in _LIST_SECTIONS:
            data[namespace] = _db_get_section(connection, namespace, "value", [])
        data["monthly_card_config"] = _db_monthly_config(connection)
        data["transactions"] = [
            dict(row) for row in connection.execute(
                """SELECT time, guild_id, user_id, amount, balance, source, reason, idempotency_key
                   FROM point_transactions ORDER BY id ASC"""
            )
        ]
        for tx in data["transactions"]:
            if not tx.get("idempotency_key"):
                tx.pop("idempotency_key", None)
        return data


def save_points_data(data):
    """兼容低频管理写入；将完整快照事务性写入 SQLite。"""
    _ensure_points_db()
    with _POINTS_DATA_LOCK, _points_connection() as connection:
        _replace_database_snapshot(connection, data)


@_locked_points_data
def modify_user_points(
    user_id: int,
    amount: float,
    guild_id: int | None = None,
    *,
    source: str = "manual",
    reason: str = "",
) -> float:
    """兼容旧入口：修改用户蛋壳余额，返回最新余额。"""
    _ensure_points_db()
    with _points_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        record, key = _db_get_user(connection, user_id, guild_id)
        current_shells = _round_shells(record.get("shells", 0))
        new_shells = _round_shells(current_shells + _round_delta(amount))
        actual_delta = _round_delta(new_shells - current_shells)
        record["shells"] = record["points"] = new_shells
        _db_append_transaction(
            connection, record, user_id=user_id, guild_id=guild_id,
            amount=actual_delta, source=source, reason=reason,
        )
        _db_put_user(connection, key, record)
        return new_shells


@_locked_points_data
def spend_user_points(
    user_id: int,
    amount: float,
    guild_id: int,
    *,
    source: str,
    reason: str = "",
) -> dict:
    """原子检查并扣除蛋壳，避免余额检查与抽卡扣款之间被其他消费穿插。"""
    cost = _round_delta(max(0.0, float(amount)))
    _ensure_points_db()
    with _points_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        record, key = _db_get_user(connection, user_id, guild_id)
        balance = _round_shells(record.get("shells", 0))
        if balance < cost:
            return {"success": False, "reason": "insufficient_shells", "cost": cost, "balance": balance}
        after = _round_shells(balance - cost)
        actual_delta = _round_delta(after - balance)
        record["shells"] = record["points"] = after
        _db_append_transaction(
            connection, record, user_id=user_id, guild_id=guild_id,
            amount=actual_delta, source=source, reason=reason,
        )
        _db_put_user(connection, key, record)
        return {"success": True, "reason": "spent", "cost": abs(actual_delta), "balance": after}


@_locked_points_data
def claim_daily_task_bonus(
    user_id: int,
    guild_id: int,
    bonus_key: str,
    amount: float = 10.0,
) -> dict:
    return _reconcile_daily_task_bonus_sql(user_id, guild_id, bonus_key, True, amount)


@_locked_points_data
def reconcile_daily_task_bonus(
    user_id: int,
    guild_id: int,
    bonus_key: str,
    qualified: bool,
    amount: float = 10.0,
) -> dict:
    return _reconcile_daily_task_bonus_sql(user_id, guild_id, bonus_key, qualified, amount)


def _reconcile_daily_task_bonus_sql(
    user_id: int,
    guild_id: int,
    bonus_key: str,
    qualified: bool,
    amount: float,
) -> dict:
    _ensure_points_db()
    today = _today()
    reward_key = f"{guild_id}:{today}"
    normalized_key = str(bonus_key or "bonus")[:32]
    claim_key = f"{user_id}:{normalized_key}"
    with _points_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = _db_get_section(connection, "daily_task_rewards", reward_key, {})
        existing = rows.get(claim_key) if isinstance(rows, dict) else None
        if qualified and existing:
            return {
                "success": False, "reason": "already_claimed",
                "amount": _round_delta(existing.get("amount", 0)) if isinstance(existing, dict) else 0.0,
            }
        if not qualified and not existing:
            return {"success": False, "reason": "not_qualified", "amount": 0.0}
        record, user_key = _db_get_user(connection, user_id, guild_id)
        before = _round_shells(record.get("shells", 0))
        if qualified:
            after = _round_shells(before + _round_delta(amount))
            actual_delta = _round_delta(after - before)
            rows[claim_key] = {"time": _now_iso(), "amount": actual_delta, "bonus_key": normalized_key}
            source = "daily_task_bonus"
            reason = f"bonus={normalized_key}"
            result_reason = "rewarded"
        else:
            revoke_amount = _round_delta(existing.get("amount", amount)) if isinstance(existing, dict) else _round_delta(amount)
            after = _round_shells(before - revoke_amount)
            actual_delta = _round_delta(after - before)
            rows.pop(claim_key, None)
            source = "daily_task_bonus_revoke"
            reason = f"bonus={normalized_key};recheck=not_qualified"
            result_reason = "revoked"
        record["shells"] = record["points"] = after
        _db_append_transaction(
            connection, record, user_id=user_id, guild_id=guild_id,
            amount=actual_delta, source=source, reason=reason,
        )
        _db_put_user(connection, user_key, record)
        _db_put_section(connection, "daily_task_rewards", reward_key, rows)
        return {
            "success": True, "reason": result_reason,
            "amount": abs(actual_delta) if result_reason == "revoked" else actual_delta,
            "balance": after,
        }


def get_user_points(user_id: int, guild_id: int | None = None) -> float:
    """兼容旧入口：获取用户蛋壳余额。"""
    _ensure_points_db()
    with _points_connection() as connection:
        record, _ = _db_get_user(connection, user_id, guild_id)
        return _round_shells(record.get("shells", 0))


def get_user_summary(user_id: int, guild_id: int | None = None) -> dict:
    _ensure_points_db()
    with _points_connection() as connection:
        record, _ = _db_get_user(connection, user_id, guild_id)
        monthly_card = _monthly_card_status(record, _db_monthly_config(connection))
        return {
            "shells": _round_shells(record.get("shells", 0)),
            "last_sign_date": record.get("last_sign_date", ""),
            "streak_days": int(record.get("streak_days", 0)),
            "daily_msg_count": int(record.get("daily_msg_count", 0)),
            "acceleration_days": int(record.get("acceleration_days", 0)),
            "monthly_card": monthly_card,
        }


def get_user_daily_snapshot(user_id: int, guild_id: int) -> dict:
    """只读取每日任务所需的当前用户、今日流水和今日识别奖励。"""
    _ensure_points_db()
    today = _today()
    user_key = _make_user_key(user_id, guild_id)
    praise_key = f"{guild_id}:{today}"
    with _points_connection() as connection:
        record, _ = _db_get_user(connection, user_id, guild_id)
        transactions = []
        for row in connection.execute(
            """SELECT time, guild_id, user_id, amount, balance, source, reason, idempotency_key
               FROM point_transactions
               WHERE guild_id=? AND user_id=? AND substr(time, 1, 10)=?
               ORDER BY id ASC""",
            (str(guild_id), str(user_id), today),
        ):
            tx = dict(row)
            if not tx.get("idempotency_key"):
                tx.pop("idempotency_key", None)
            transactions.append(tx)
        praise_rows = _db_get_section(connection, "daily_praise_rewards", praise_key, {})
    return {
        "version": 3,
        "users": {user_key: record},
        "transactions": transactions,
        "daily_praise_rewards": {praise_key: praise_rows},
    }


def get_daily_activity_stats(guild_id: int, report_date: str) -> dict:
    """读取日报所需三类日记录，不加载用户表和流水表。"""
    _ensure_points_db()
    daily_key = f"{guild_id}:{report_date}"
    with _points_connection() as connection:
        signers = _db_get_section(connection, "daily_signins", daily_key, [])
        praise_rows = _db_get_section(connection, "daily_praise_rewards", daily_key, {})
        forum_records = connection.execute(
            """SELECT item_key, data FROM point_sections
               WHERE namespace='daily_forum_rewards' AND item_key LIKE ?""",
            (f"%:{report_date}",),
        ).fetchall()
    signin_users = {str(user_id) for user_id in signers if str(user_id).isdigit()}
    forum_users, forum_threads = set(), set()
    for record in forum_records:
        parts = str(record["item_key"]).split(":")
        key_guild_id = parts[1] if parts and parts[0] == "user" and len(parts) >= 4 else (parts[0] if parts else "")
        if key_guild_id != str(guild_id):
            continue
        rows = _json_load(record["data"], [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            if row.get("user_id"):
                forum_users.add(str(row["user_id"]))
            if row.get("thread_id"):
                forum_threads.add(str(row["thread_id"]))
    praise_users = {
        str(key).split(":", 1)[0]
        for key, row in (praise_rows.items() if isinstance(praise_rows, dict) else [])
        if isinstance(row, dict)
    }
    return {
        "signin_users": len(signin_users), "forum_users": len(forum_users),
        "forum_posts": len(forum_threads), "praise_users": len(praise_users),
    }


def _monthly_card_status(record: dict, raw_config: dict | None = None, now: datetime | None = None) -> dict:
    config_data = _normalize_monthly_card_config(raw_config)
    now = (now or datetime.now(TZ_CN)).astimezone(TZ_CN)
    periods = []
    for item in _normalize_monthly_periods(record.get("monthly_card_periods", [])):
        starts_at = _parse_iso_datetime(item.get("starts_at"))
        expires_at = _parse_iso_datetime(item.get("expires_at"))
        if starts_at and expires_at and expires_at > now:
            periods.append((item, starts_at, expires_at))

    active = any(starts_at <= now < expires_at for _, starts_at, expires_at in periods)
    expires_at = max((end for _, _, end in periods), default=None)
    remaining_seconds = max(0.0, (expires_at - now).total_seconds()) if expires_at else 0.0
    return {
        "enabled": bool(config_data["enabled"]),
        "active": active,
        "stacked_cards": len(periods),
        "max_cards": int(config_data["max_cards"]),
        "remaining_days": round(remaining_seconds / 86400, 2),
        "remaining_seconds": int(remaining_seconds),
        "expires_at": expires_at.isoformat(timespec="seconds") if expires_at else "",
        "price": config_data["price"],
        "duration_days": config_data["duration_days"],
        "daily_reward": config_data["daily_reward"],
        "reward_multiplier": config_data["reward_multiplier"],
        "ever_purchased": bool(record.get("monthly_card_ever_purchased", False)),
        "first_role_pending": bool(record.get("monthly_card_first_role_pending", False)),
        "first_role_id": int(record.get("monthly_card_first_role_id", 0) or 0),
        "last_daily_reward_date": str(record.get("monthly_card_last_daily_reward_date", "") or ""),
    }


def _monthly_reward_amount(record: dict, raw_config: dict | None, base_amount: float) -> tuple[float, float, float]:
    base = _round_delta(base_amount)
    status = _monthly_card_status(record, raw_config)
    multiplier = float(status["reward_multiplier"]) if status["active"] else 1.0
    total = _round_delta(base * multiplier) if base > 0 else base
    return total, _round_delta(max(0.0, total - base)), multiplier


def _grant_monthly_daily_reward(
    data: dict,
    record: dict,
    *,
    user_id: int,
    guild_id: int,
    now: datetime | None = None,
) -> float:
    now = (now or datetime.now(TZ_CN)).astimezone(TZ_CN)
    config_data = _normalize_monthly_card_config(data.get("monthly_card_config"))
    today = now.date().isoformat()
    periods = _normalize_monthly_periods(record.get("monthly_card_periods", []))
    missing_rewards = 0
    for item in periods:
        starts_at = _parse_iso_datetime(item.get("starts_at"))
        expires_at = _parse_iso_datetime(item.get("expires_at"))
        if not starts_at or not expires_at or now < starts_at:
            continue
        reward_days = max(1, int(item.get("reward_days", 1) or 1))
        effective_now = min(now, expires_at - timedelta(microseconds=1))
        elapsed_dates = max(0, (effective_now.date() - starts_at.date()).days + 1)
        eligible_rewards = min(reward_days, elapsed_dates)
        granted = min(reward_days, max(0, int(item.get("daily_rewards_granted", 0) or 0)))
        missing = max(0, eligible_rewards - granted)
        if missing:
            item["daily_rewards_granted"] = granted + missing
            missing_rewards += missing
    record["monthly_card_periods"] = periods
    if missing_rewards <= 0:
        return 0.0

    reward = _round_delta(config_data["daily_reward"] * missing_rewards)
    record["monthly_card_last_daily_reward_date"] = today
    if reward <= 0:
        return 0.0
    before = _round_shells(record.get("shells", 0))
    after = _round_shells(before + reward)
    actual_delta = _round_delta(after - before)
    record["shells"] = after
    record["points"] = after
    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=actual_delta,
        source="monthly_card_daily",
        reason=f"date={today};settled_days={missing_rewards}",
    )
    return actual_delta


def get_monthly_card_config() -> dict:
    _ensure_points_db()
    with _points_connection() as connection:
        return _db_monthly_config(connection)


@_locked_points_data
def update_monthly_card_config(
    *,
    price: float,
    duration_days: int,
    daily_reward: float,
    reward_multiplier: float,
    enabled: bool | None = None,
) -> dict:
    _ensure_points_db()
    with _points_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = _db_monthly_config(connection)
        current.update({
            "price": price, "duration_days": duration_days,
            "daily_reward": daily_reward, "reward_multiplier": reward_multiplier,
        })
        if enabled is not None:
            current["enabled"] = bool(enabled)
        saved = _normalize_monthly_card_config(current)
        _db_put_section(connection, "config", "monthly_card", saved)
        return saved


def get_monthly_card_status(user_id: int, guild_id: int) -> dict:
    _ensure_points_db()
    with _points_connection() as connection:
        record, _ = _db_get_user(connection, user_id, guild_id)
        status = _monthly_card_status(record, _db_monthly_config(connection))
        status["balance"] = _round_shells(record.get("shells", 0))
        return status


@_locked_points_data
def purchase_monthly_card(user_id: int, guild_id: int) -> dict:
    data = load_points_data()
    config_data = _normalize_monthly_card_config(data.get("monthly_card_config"))
    record, _ = _ensure_user_record(data, user_id, guild_id)
    if not config_data["enabled"]:
        return {"success": False, "reason": "disabled", "status": _monthly_card_status(record, config_data)}

    now = datetime.now(TZ_CN)
    catch_up_reward = _grant_monthly_daily_reward(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        now=now,
    )
    if catch_up_reward > 0:
        save_points_data(data)
    all_periods = _normalize_monthly_periods(record.get("monthly_card_periods", []))
    active_periods = []
    for item in all_periods:
        expires_at = _parse_iso_datetime(item.get("expires_at"))
        if expires_at and expires_at > now:
            active_periods.append(item)
    record["monthly_card_periods"] = all_periods
    if len(active_periods) >= config_data["max_cards"]:
        return {
            "success": False,
            "reason": "max_cards_reached",
            "status": _monthly_card_status(record, config_data, now),
        }

    price = _round_delta(config_data["price"])
    balance = _round_shells(record.get("shells", 0))
    if balance < price:
        return {
            "success": False,
            "reason": "insufficient_shells",
            "cost": price,
            "balance": balance,
            "status": _monthly_card_status(record, config_data, now),
        }

    last_expiry = max(
        (_parse_iso_datetime(item.get("expires_at")) for item in active_periods),
        default=None,
    )
    starts_at = max(now, last_expiry) if last_expiry else now
    expires_at = starts_at + timedelta(days=config_data["duration_days"])
    purchase_id = uuid.uuid4().hex[:16]
    purchase = {
        "purchase_id": purchase_id,
        "purchased_at": now.isoformat(timespec="seconds"),
        "starts_at": starts_at.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "cost": price,
        "reward_days": int(config_data["duration_days"]),
        "daily_rewards_granted": 0,
    }
    all_periods.append(purchase)
    record["monthly_card_periods"] = all_periods[-24:]

    first_purchase = not bool(record.get("monthly_card_ever_purchased", False))
    record["monthly_card_ever_purchased"] = True
    if first_purchase and not int(record.get("monthly_card_first_role_id", 0) or 0):
        record["monthly_card_first_role_pending"] = True

    before = balance
    after_purchase = _round_shells(before - price)
    actual_cost = _round_delta(after_purchase - before)
    record["shells"] = after_purchase
    record["points"] = after_purchase
    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=actual_cost,
        source="monthly_card_purchase",
        reason=f"purchase_id={purchase_id};expires_at={expires_at.isoformat(timespec='seconds')}",
    )
    record.setdefault("monthly_card_purchases", []).append(dict(purchase))
    record["monthly_card_purchases"] = record["monthly_card_purchases"][-20:]
    top_purchase = dict(purchase)
    top_purchase.update({"user_id": str(user_id), "guild_id": str(guild_id)})
    data.setdefault("monthly_card_purchases", []).append(top_purchase)
    data["monthly_card_purchases"] = data["monthly_card_purchases"][-500:]

    current_reward = _grant_monthly_daily_reward(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        now=now,
    )
    daily_reward = _round_delta(catch_up_reward + current_reward)
    save_points_data(data)
    return {
        "success": True,
        "reason": "purchased",
        "cost": price,
        "daily_reward": daily_reward,
        "first_purchase": first_purchase,
        "balance": _round_shells(record.get("shells", 0)),
        "status": _monthly_card_status(record, config_data, now),
    }


@_locked_points_data
def claim_monthly_card_first_role(user_id: int, guild_id: int, role_id: int) -> dict:
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)
    if not record.get("monthly_card_ever_purchased", False):
        return {"success": False, "reason": "not_purchased"}
    if not record.get("monthly_card_first_role_pending", False):
        return {"success": False, "reason": "already_claimed", "role_id": int(record.get("monthly_card_first_role_id", 0) or 0)}
    record["monthly_card_first_role_pending"] = False
    record["monthly_card_first_role_id"] = int(role_id)
    save_points_data(data)
    return {"success": True, "reason": "claimed", "role_id": int(role_id)}


@_locked_points_data
def settle_monthly_card_daily_rewards() -> dict:
    _ensure_points_db()
    now = datetime.now(TZ_CN)
    rewarded_users = 0
    total_reward = 0.0
    with _points_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        config_data = _db_monthly_config(connection)
        candidates = connection.execute(
            "SELECT user_key, data FROM point_users WHERE has_monthly_card=1"
        ).fetchall()
        for row in candidates:
            key = str(row["user_key"])
            if ":" not in key:
                continue
            try:
                guild_id, user_id = (int(value) for value in key.split(":", 1))
            except ValueError:
                continue
            record = _normalize_record(_json_load(row["data"], {}))
            local_data = {"monthly_card_config": config_data, "transactions": []}
            reward = _grant_monthly_daily_reward(
                local_data, record, user_id=user_id, guild_id=guild_id, now=now
            )
            if reward <= 0:
                continue
            tx = local_data["transactions"][-1]
            connection.execute(
                """INSERT INTO point_transactions
                   (time, guild_id, user_id, amount, balance, source, reason, idempotency_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, '')""",
                (
                    tx["time"], tx["guild_id"], tx["user_id"], tx["amount"],
                    tx["balance"], tx["source"], tx["reason"],
                ),
            )
            _db_put_user(connection, key, record)
            rewarded_users += 1
            total_reward = _round_delta(total_reward + reward)
        if rewarded_users:
            connection.execute(
                "DELETE FROM point_transactions WHERE id NOT IN (SELECT id FROM point_transactions ORDER BY id DESC LIMIT 500)"
            )
    return {"date": now.date().isoformat(), "rewarded_users": rewarded_users, "total_reward": total_reward}


@_locked_points_data
def grant_monthly_eligible_reward(
    user_id: int,
    guild_id: int,
    amount: float,
    *,
    source: str,
    reason: str = "",
    idempotency_key: str = "",
) -> dict:
    _ensure_points_db()
    normalized_key = str(idempotency_key or "").strip()
    with _points_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        record, key = _db_get_user(connection, user_id, guild_id)
        if normalized_key:
            existing = connection.execute(
                """SELECT amount FROM point_transactions
                   WHERE guild_id=? AND user_id=? AND idempotency_key=?""",
                (str(guild_id), str(user_id), normalized_key),
            ).fetchone()
            if existing:
                return {
                    "success": True,
                    "duplicate": True,
                    "base_amount": 0.0,
                    "monthly_bonus": 0.0,
                    "amount": _round_delta(existing["amount"]),
                    "multiplier": 1.0,
                    "balance": _round_shells(record.get("shells", 0)),
                }
        base = _round_delta(amount)
        total, monthly_bonus, multiplier = _monthly_reward_amount(record, _db_monthly_config(connection), base)
        before = _round_shells(record.get("shells", 0))
        after = _round_shells(before + total)
        actual_delta = _round_delta(after - before)
        record["shells"] = record["points"] = after
        detail = reason
        if monthly_bonus > 0:
            detail = f"{reason};monthly_card={multiplier}x;base={format_shells(base)}".strip(";")
        _db_append_transaction(
            connection, record, user_id=user_id, guild_id=guild_id,
            amount=actual_delta, source=source, reason=detail, idempotency_key=normalized_key,
        )
        _db_put_user(connection, key, record)
        return {
            "success": True,
            "duplicate": False,
            "base_amount": base,
            "monthly_bonus": monthly_bonus,
            "amount": actual_delta,
            "multiplier": multiplier,
            "balance": after,
        }


def get_acceleration_tiers() -> list[dict]:
    raw_tiers = getattr(config, "ACCELERATION_CARD_TIERS", [])
    tiers = []
    for tier in raw_tiers:
        if not isinstance(tier, dict):
            continue
        tier_id = str(tier.get("id", "")).strip()
        label = str(tier.get("label", "")).strip()
        try:
            days = int(tier.get("days", 0))
            cost = _round_delta(tier.get("cost", 0))
        except (TypeError, ValueError):
            continue
        if not tier_id or days <= 0 or cost <= 0:
            continue
        tiers.append({"id": tier_id, "label": label or f"减{days}天", "days": days, "cost": cost})

    return tiers or [
        {"id": "day_1", "label": "减1天", "days": 1, "cost": 2.0},
        {"id": "day_5", "label": "减5天", "days": 5, "cost": 8.0},
        {"id": "day_10", "label": "减10天", "days": 10, "cost": 15.0},
    ]


def get_acceleration_status(user_id: int, guild_id: int | None = None) -> dict:
    _ensure_points_db()
    with _points_connection() as connection:
        record, _ = _db_get_user(connection, user_id, guild_id)
    max_days = int(getattr(config, "ACCELERATION_CARD_MAX_DAYS", 25))
    base_wait = int(getattr(config, "ACCOUNT_BASE_WAIT_DAYS", 30))
    min_wait = int(getattr(config, "ACCOUNT_MIN_WAIT_DAYS", 5))
    days = min(max_days, max(0, int(record.get("acceleration_days", 0))))
    required_wait = max(min_wait, base_wait - days)
    return {
        "acceleration_days": days,
        "max_days": max_days,
        "remaining_acceleration_days": max(0, max_days - days),
        "base_wait_days": base_wait,
        "min_wait_days": min_wait,
        "required_wait_days": required_wait,
        "tiers": get_acceleration_tiers(),
    }


@_locked_points_data
def purchase_acceleration_card(user_id: int, guild_id: int, tier_id: str) -> dict:
    tiers = {tier["id"]: tier for tier in get_acceleration_tiers()}
    tier = tiers.get(tier_id)
    if not tier:
        return {"success": False, "reason": "unknown_tier"}

    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)
    max_days = int(getattr(config, "ACCELERATION_CARD_MAX_DAYS", 25))
    current_days = min(max_days, max(0, int(record.get("acceleration_days", 0))))
    if current_days >= max_days:
        return {"success": False, "reason": "max_reached", "status": get_acceleration_status(user_id, guild_id)}

    cost = _round_delta(tier["cost"])
    balance = _round_shells(record.get("shells", 0))
    if balance < cost:
        return {
            "success": False,
            "reason": "insufficient_shells",
            "balance": balance,
            "cost": cost,
            "tier": tier,
        }

    effective_days = min(int(tier["days"]), max_days - current_days)
    after = _round_shells(balance - cost)
    record["shells"] = after
    record["points"] = after
    record["acceleration_days"] = current_days + effective_days
    card_record = {
        "time": _now_iso(),
        "guild_id": str(guild_id),
        "user_id": str(user_id),
        "tier_id": tier["id"],
        "label": tier["label"],
        "configured_days": int(tier["days"]),
        "effective_days": effective_days,
        "cost": cost,
        "balance": after,
    }
    record.setdefault("acceleration_cards", []).append(card_record)
    data.setdefault("acceleration_purchases", []).append(card_record)
    data["acceleration_purchases"] = data["acceleration_purchases"][-500:]

    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=-cost,
        source="acceleration_card",
        reason=f"tier={tier['id']};days={effective_days}",
    )
    save_points_data(data)
    return {
        "success": True,
        "tier": tier,
        "effective_days": effective_days,
        "balance": after,
        "status": get_acceleration_status(user_id, guild_id),
    }


def load_random_events() -> list[dict]:
    global _RANDOM_EVENTS_CACHE, _RANDOM_EVENTS_MTIME_NS
    try:
        mtime_ns = os.stat(RANDOM_EVENTS_FILE).st_mtime_ns
    except OSError:
        mtime_ns = -1
    if _RANDOM_EVENTS_CACHE is not None and mtime_ns == _RANDOM_EVENTS_MTIME_NS:
        return [dict(event) for event in _RANDOM_EVENTS_CACHE]
    try:
        with open(RANDOM_EVENTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw = DEFAULT_RANDOM_EVENTS

    events = raw.get("events", []) if isinstance(raw, dict) else []
    valid_events = []
    seen_ids = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id", "")).strip()
        event_type = str(event.get("type", "")).strip()
        if not event_id or event_id in seen_ids:
            continue
        if event_type not in {"positive", "negative", "neutral"}:
            continue

        min_delta = min(1.9, max(0.0, _round_delta(event.get("min_delta", 0))))
        max_delta = min(1.9, max(0.0, _round_delta(event.get("max_delta", min_delta))))
        if max_delta < min_delta:
            min_delta, max_delta = max_delta, min_delta

        valid_events.append(
            {
                "id": event_id,
                "type": event_type,
                "title": str(event.get("title", "小蛋事件")).strip() or "小蛋事件",
                "description": str(event.get("description", "")).strip(),
                "min_delta": min_delta,
                "max_delta": max_delta,
                "weight": max(0, int(event.get("weight", 1) or 1)),
            }
        )
        seen_ids.add(event_id)

    _RANDOM_EVENTS_CACHE = valid_events or [dict(event) for event in DEFAULT_RANDOM_EVENTS["events"]]
    _RANDOM_EVENTS_MTIME_NS = mtime_ns
    return [dict(event) for event in _RANDOM_EVENTS_CACHE]


def _pick_random_event() -> dict:
    events = load_random_events()
    weights = [max(0, int(event.get("weight", 1))) for event in events]
    if sum(weights) <= 0:
        weights = [1] * len(events)
    event = random.choices(events, weights=weights, k=1)[0]
    amount = 0.0
    if event["type"] != "neutral":
        steps_min = int(_round_delta(event["min_delta"]) * 10)
        steps_max = int(_round_delta(event["max_delta"]) * 10)
        amount = random.randint(steps_min, steps_max) / 10
        if event["type"] == "negative":
            amount *= -1
    return {**event, "delta": _round_delta(amount)}


def _calculate_streak(last_sign_date: str, today: str, current_streak: int) -> int:
    if not last_sign_date:
        return 1
    try:
        last_date = datetime.fromisoformat(last_sign_date).date()
        today_date = datetime.fromisoformat(today).date()
    except ValueError:
        return 1
    if last_date == today_date:
        return max(1, current_streak)
    if (today_date - last_date).days == 1:
        return max(0, current_streak) + 1
    return 1


def get_streak_bonus_rate(streak_days: int) -> float:
    if streak_days < 7:
        return 0.0
    return min(0.6, math.floor(math.log2(streak_days / 7 + 1) * 10) / 100)


def get_activity_bonus_rate(valid_message_count: int) -> float:
    if valid_message_count >= 30:
        return 0.20
    if valid_message_count >= 20:
        return 0.15
    if valid_message_count >= 10:
        return 0.10
    if valid_message_count >= 5:
        return 0.05
    return 0.0


def _register_daily_rank(data: dict, guild_id: int, user_id: int, today: str) -> int:
    daily_key = f"{guild_id}:{today}"
    signers = data.setdefault("daily_signins", {}).setdefault(daily_key, [])
    uid = str(user_id)
    if uid not in signers:
        signers.append(uid)
    return signers.index(uid) + 1


def get_daily_signin_summary(guild_id: int) -> dict:
    _ensure_points_db()
    today = _today()
    daily_key = f"{guild_id}:{today}"
    with _points_connection() as connection:
        signers = _db_get_section(connection, "daily_signins", daily_key, [])
    if not isinstance(signers, list):
        signers = []
    normalized = []
    seen = set()
    for raw_user_id in signers:
        user_id = str(raw_user_id)
        if user_id and user_id not in seen:
            normalized.append(user_id)
            seen.add(user_id)
    return {
        "date": today,
        "count": len(normalized),
        "top10": normalized[:10],
    }


@_locked_points_data
def sign_in_user(user_id: int, guild_id: int, reward: float = 1.0) -> dict:
    """每日报到，返回详细蛋壳结算结果。"""
    _ensure_points_db()
    today = _today()
    with _points_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        record, key = _db_get_user(connection, user_id, guild_id)
        if record.get("last_sign_date", "") == today:
            return {
                "success": False, "balance": _round_shells(record.get("shells", 0)),
                "streak_days": int(record.get("streak_days", 0)), "message": "今日已报到",
            }
        streak_days = _calculate_streak(
            str(record.get("last_sign_date", "")), today, int(record.get("streak_days", 0))
        )
        daily_msg_count = int(record.get("daily_msg_count", 0))
        if record.get("daily_msg_date", "") != today:
            daily_msg_count = 0
        base_reward = _round_delta(reward)
        streak_rate = get_streak_bonus_rate(streak_days)
        activity_rate = get_activity_bonus_rate(daily_msg_count)
        bonus_amount = _round_delta(base_reward * (streak_rate + activity_rate))
        daily_key = f"{guild_id}:{today}"
        signers = _db_get_section(connection, "daily_signins", daily_key, [])
        uid = str(user_id)
        if uid not in signers:
            signers.append(uid)
        rank = signers.index(uid) + 1
        rank_bonus = _round_delta(random.randint(1, 19) / 10) if rank <= 10 else 0.0
        event = _pick_random_event()
        event_delta = _round_delta(event.get("delta", 0))
        before = _round_shells(record.get("shells", 0))
        positive_rewards = _round_delta(base_reward + bonus_amount + rank_bonus + max(0.0, event_delta))
        _, monthly_card_bonus, monthly_multiplier = _monthly_reward_amount(
            record, _db_monthly_config(connection), positive_rewards
        )
        total_delta = _round_delta(base_reward + bonus_amount + rank_bonus + event_delta + monthly_card_bonus)
        after = _round_shells(before + total_delta)
        actual_delta = _round_delta(after - before)
        record.update({"last_sign_date": today, "streak_days": streak_days, "shells": after, "points": after})
        _db_append_transaction(
            connection, record, user_id=user_id, guild_id=guild_id, amount=actual_delta,
            source="sign_in", reason=f"rank={rank};event={event['id']};monthly_card={monthly_multiplier}x",
        )
        _db_put_user(connection, key, record)
        _db_put_section(connection, "daily_signins", daily_key, signers)
        return {
            "success": True, "balance": after, "base_reward": base_reward,
            "bonus_amount": bonus_amount, "streak_rate": streak_rate, "activity_rate": activity_rate,
            "streak_days": streak_days, "daily_msg_count": daily_msg_count, "rank": rank,
            "rank_bonus": rank_bonus, "event": event, "event_delta": event_delta,
            "monthly_card_bonus": monthly_card_bonus, "monthly_card_multiplier": monthly_multiplier,
            "total_delta": actual_delta,
        }


@_locked_points_data
def record_message_activity(user_id: int, guild_id: int) -> int:
    """记录每日有效发言次数，不直接发放蛋壳。"""
    _ensure_points_db()
    today = _today()
    with _points_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        record, key = _db_get_user(connection, user_id, guild_id)
        if record.get("daily_msg_date", "") != today:
            record["daily_msg_date"] = today
            record["daily_msg_count"] = 0
        record["daily_msg_count"] = int(record.get("daily_msg_count", 0)) + 1
        _db_put_user(connection, key, record)
        return int(record["daily_msg_count"])


def add_message_points(
    user_id: int,
    guild_id: int,
    amount: float = 0,
    daily_cap: float = 0,
) -> int:
    """兼容旧入口：新版只记录发言活跃，不再单条发放蛋壳。"""
    return record_message_activity(user_id, guild_id)


@_locked_points_data
def add_post_points(
    user_id: int,
    guild_id: int,
    amount: float,
    daily_cap: float,
) -> float:
    """保留旧论坛发帖入口，按每日上限发放蛋壳。"""
    if amount <= 0 or daily_cap <= 0:
        return 0.0

    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)

    today = _today()
    if record.get("daily_post_date", "") != today:
        record["daily_post_date"] = today
        record["daily_post_pts"] = 0.0

    today_pts = _round_shells(record.get("daily_post_pts", 0))
    if today_pts >= daily_cap:
        return 0.0

    can_add = _round_delta(min(amount, daily_cap - today_pts))
    credited, monthly_bonus, multiplier = _monthly_reward_amount(record, data.get("monthly_card_config"), can_add)
    before = _round_shells(record.get("shells", 0))
    after = _round_shells(before + credited)
    actual_delta = _round_delta(after - before)

    record["daily_post_pts"] = _round_delta(today_pts + can_add)
    record["shells"] = after
    record["points"] = after
    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=actual_delta,
        source="forum_post",
        reason=f"legacy_forum_post_reward;monthly_card={multiplier}x;base={format_shells(can_add)}",
    )
    save_points_data(data)
    return actual_delta


@_locked_points_data
def reward_daily_forum_post(
    user_id: int,
    guild_id: int,
    channel_id: int,
    thread_id: int,
    *,
    amount: float,
    daily_limit: int,
) -> dict:
    """用户每日前 N 次论坛发帖奖励，额度跨所有论坛频道累计。"""
    data = load_points_data()
    today = _today()
    reward_key = f"user:{guild_id}:{user_id}:{today}"
    reward_rows = data.setdefault("daily_forum_rewards", {})
    rewards = reward_rows.setdefault(reward_key, [])

    # 当天可能还留有旧版“按频道”记录；迁移期间一并计入个人额度，避免重复发放。
    existing_by_thread: dict[str, dict] = {}
    for key, rows in reward_rows.items():
        key_parts = str(key).split(":")
        if len(key_parts) < 3 or key_parts[-1] != today:
            continue
        key_guild_id = key_parts[1] if key_parts[0] == "user" and len(key_parts) >= 4 else key_parts[0]
        if key_guild_id != str(guild_id) or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or str(row.get("user_id")) != str(user_id):
                continue
            existing_thread_id = str(row.get("thread_id", ""))
            if existing_thread_id:
                existing_by_thread[existing_thread_id] = row

    thread_id_str = str(thread_id)
    if thread_id_str in existing_by_thread:
        return {
            "success": False,
            "reason": "duplicate_thread",
            "daily_count": len(existing_by_thread),
            "amount": 0.0,
        }

    if len(existing_by_thread) >= daily_limit:
        return {
            "success": False,
            "reason": "daily_limit_reached",
            "daily_count": len(existing_by_thread),
            "amount": 0.0,
        }

    record, _ = _ensure_user_record(data, user_id, guild_id)
    before = _round_shells(record.get("shells", 0))
    base_amount = _round_delta(amount)
    delta, monthly_bonus, multiplier = _monthly_reward_amount(record, data.get("monthly_card_config"), base_amount)
    after = _round_shells(before + delta)
    actual_delta = _round_delta(after - before)

    row = {
        "thread_id": thread_id_str,
        "user_id": str(user_id),
        "channel_id": str(channel_id),
        "time": _now_iso(),
        "amount": actual_delta,
        "base_amount": base_amount,
        "monthly_bonus": monthly_bonus,
        "daily_count": len(existing_by_thread) + 1,
    }
    rewards.append(row)

    record["shells"] = after
    record["points"] = after
    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=actual_delta,
        source="daily_forum_post",
        reason=f"channel={channel_id};thread={thread_id};daily_count={row['daily_count']};monthly_card={multiplier}x",
    )
    save_points_data(data)
    return {"success": True, "reason": "rewarded", "daily_count": row["daily_count"], "amount": actual_delta}


def _get_praise_weights() -> list[int]:
    raw = getattr(config, "PRAISE_KIMI_REWARD_WEIGHTS", [90, 70, 52, 36, 24, 15, 9, 4, 1])
    if not isinstance(raw, (list, tuple)) or len(raw) != 9:
        return [90, 70, 52, 36, 24, 15, 9, 4, 1]
    weights = []
    for value in raw:
        try:
            weights.append(max(0, int(value)))
        except (TypeError, ValueError):
            weights.append(0)
    if sum(weights) <= 0:
        return [90, 70, 52, 36, 24, 15, 9, 4, 1]
    return weights


def _praise_scan_key(guild_id: int, message_id: int, rule_id: str | None = None) -> str:
    rule = str(rule_id or "no_rule")[:64]
    return f"{guild_id}:{message_id}:{rule}"


def _discord_snowflake_date_cn(message_id: int | str) -> str | None:
    try:
        snowflake = int(message_id)
        if snowflake <= 0:
            return None
        timestamp_ms = (snowflake >> 22) + 1420070400000
        occurred_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return None
    return _date_cn(occurred_at)


def _repair_praise_reward_dates(data: dict, guild_id: int, reward_date: str) -> int:
    rewards = data.setdefault("daily_praise_rewards", {})
    source_key = f"{guild_id}:{reward_date}"
    source_rows = rewards.setdefault(source_key, {})
    repaired = 0
    for claim_key, item in list(source_rows.items()):
        if not isinstance(item, dict):
            continue
        actual_date = _discord_snowflake_date_cn(item.get("message_id", ""))
        if not actual_date or actual_date == reward_date:
            continue

        source_rows.pop(claim_key, None)
        target_rows = rewards.setdefault(f"{guild_id}:{actual_date}", {})
        target_key = str(claim_key)
        if target_key in target_rows:
            target_key = f"{target_key}:recovered:{item.get('message_id', repaired)}"
        target_rows[target_key] = item
        repaired += 1
    return repaired


@_locked_points_data
def get_successful_praise_scan_record(guild_id: int, message_id: int, rule_id: str) -> dict | None:
    data = load_points_data()
    today = _today()
    rows = data.setdefault("daily_praise_scan_records", {}).setdefault(today, {})
    item = rows.get(_praise_scan_key(guild_id, message_id, rule_id))
    return dict(item) if isinstance(item, dict) and item.get("status") == "rewarded" else None


def has_successful_praise_scan_record(guild_id: int, message_id: int, rule_id: str) -> bool:
    return get_successful_praise_scan_record(guild_id, message_id, rule_id) is not None


@_locked_points_data
def record_praise_scan_log(
    *,
    guild_id: int,
    channel_id: int,
    message_id: int,
    author_id: int,
    author_name: str,
    content: str,
    status: str,
    reason: str,
    rule_id: str = "",
    rule_field: str = "",
    amount: float = 0.0,
    recovered: bool = False,
    message_created_at: str = "",
) -> dict:
    data = load_points_data()
    today = _today()
    rows = data.setdefault("daily_praise_scan_records", {}).setdefault(today, {})
    normalized_rule = str(rule_id or "")[:64]
    key_rule = normalized_rule if status == "rewarded" and normalized_rule else f"{normalized_rule or 'no_rule'}:{status}"
    key = _praise_scan_key(guild_id, message_id, key_rule)
    row = {
        "time": _now_iso(),
        "guild_id": str(guild_id),
        "channel_id": str(channel_id),
        "message_id": str(message_id),
        "author_id": str(author_id),
        "author_name": str(author_name or "")[:100],
        "content": str(content or ""),
        "status": str(status or "unknown")[:32],
        "reason": str(reason or "")[:200],
        "rule_id": str(rule_id or "")[:64],
        "rule_field": str(rule_field or "")[:200],
        "amount": _round_delta(amount),
        "recovered": bool(recovered),
        "message_created_at": str(message_created_at or "")[:40],
    }
    rows[key] = row
    save_points_data(data)
    return row


@_locked_points_data
def reward_daily_kimi_praise(
    user_id: int,
    guild_id: int,
    message_id: int,
    *,
    rule_id: str = "default_kimi_praise",
    min_reward: float = 1.0,
    max_reward: float = 9.0,
    occurred_at: datetime | None = None,
) -> dict:
    """Reward each configured recognition rule at most once per user per day."""
    data = load_points_data()
    today = _date_cn(occurred_at)
    reward_key = f"{guild_id}:{today}"
    rows = data.setdefault("daily_praise_rewards", {}).setdefault(reward_key, {})
    repaired = _repair_praise_reward_dates(data, guild_id, today)
    if repaired:
        save_points_data(data)
    uid = str(user_id)
    message_id_str = str(message_id)
    normalized_rule_id = str(rule_id or "default_kimi_praise")[:64]
    claim_key = f"{uid}:{normalized_rule_id}"

    for existing_key, existing in rows.items():
        if (
            isinstance(existing, dict)
            and str(existing.get("message_id", "")) == message_id_str
            and str(existing.get("rule_id", "default_kimi_praise")) == normalized_rule_id
        ):
            return {
                "success": False,
                "reason": "duplicate_message",
                "amount": _round_delta(existing.get("amount", 0)),
                "message_id": message_id_str,
                "claim_key": str(existing_key),
            }

    # The former single-trigger format used the bare user ID. Preserve its daily claim.
    legacy_claimed = normalized_rule_id == "default_kimi_praise" and uid in rows
    if claim_key in rows or legacy_claimed:
        existing = rows.get(claim_key, rows.get(uid, {}))
        return {
            "success": False,
            "reason": "already_claimed",
            "amount": _round_delta(existing.get("amount", 0)) if isinstance(existing, dict) else 0.0,
            "message_id": str(existing.get("message_id", "")) if isinstance(existing, dict) else "",
        }

    minimum = max(1, int(round(float(min_reward) * 10)))
    maximum = max(1, int(round(float(max_reward) * 10)))
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    base_amount = random.randint(minimum, maximum) / 10
    record, _ = _ensure_user_record(data, user_id, guild_id)
    amount, monthly_bonus, multiplier = _monthly_reward_amount(record, data.get("monthly_card_config"), base_amount)
    before = _round_shells(record.get("shells", 0))
    after = _round_shells(before + amount)
    actual_delta = _round_delta(after - before)

    rows[claim_key] = {
        "time": _now_iso(),
        "message_id": message_id_str,
        "amount": actual_delta,
        "base_amount": _round_delta(base_amount),
        "monthly_bonus": monthly_bonus,
        "rule_id": normalized_rule_id,
    }
    record["shells"] = after
    record["points"] = after
    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=actual_delta,
        source="kimi_praise",
        reason=f"message_id={message_id};rule={normalized_rule_id};monthly_card={multiplier}x",
    )
    save_points_data(data)
    return {
        "success": True,
        "reason": "rewarded",
        "amount": actual_delta,
        "balance": after,
        "reward_date": today,
        "repaired_records": repaired,
    }
