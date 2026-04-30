# cogs/points/storage.py

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Tuple

POINTS_DATA_FILE = "data/user_points.json"
LOTTERY_DATA_FILE = "data/general_lottery.json"
TZ_CN = timezone(timedelta(hours=8))


def _make_user_key(user_id: int, guild_id: int | None = None) -> str:
    if guild_id is None:
        return str(user_id)
    return f"{guild_id}:{user_id}"


def _normalize_points_data(raw_data: dict) -> dict:
    """兼容旧格式并统一为新结构。"""
    if not isinstance(raw_data, dict):
        return {"version": 2, "users": {}}

    # 新格式
    if "users" in raw_data and isinstance(raw_data["users"], dict):
        return {
            "version": int(raw_data.get("version", 2)),
            "users": raw_data["users"],
        }

    # 旧格式: {"user_id": points}
    users = {}
    for uid, pts in raw_data.items():
        try:
            points = max(0, int(pts))
        except (TypeError, ValueError):
            points = 0
        users[str(uid)] = {
            "points": points,
            "last_sign_date": "",
            "daily_msg_pts": 0,
            "daily_msg_date": "",
        }

    return {"version": 2, "users": users}


def _ensure_user_record(data: dict, user_id: int, guild_id: int | None = None) -> tuple[dict, str]:
    users = data.setdefault("users", {})
    key = _make_user_key(user_id, guild_id)
    if key not in users or not isinstance(users[key], dict):
        users[key] = {
            "points": 0,
            "last_sign_date": "",
            "daily_msg_pts": 0,
            "daily_msg_date": "",
        }

    record = users[key]
    record.setdefault("points", 0)
    record.setdefault("last_sign_date", "")
    record.setdefault("daily_msg_pts", 0)
    record.setdefault("daily_msg_date", "")
    return record, key

def load_points_data():
    """加载用户积分数据，如果文件不存在则返回空字典。"""
    if not os.path.exists(POINTS_DATA_FILE):
        return {"version": 2, "users": {}}
    try:
        with open(POINTS_DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return _normalize_points_data(raw)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"version": 2, "users": {}}

def save_points_data(data):
    """保存用户积分数据到文件。"""
    os.makedirs(os.path.dirname(POINTS_DATA_FILE), exist_ok=True)
    with open(POINTS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def modify_user_points(user_id: int, amount: int, guild_id: int | None = None) -> int:
    """
    修改单个用户的积分。

    Args:
        user_id (int): 用户的ID。
        amount (int): 要增加或减少的积分量 (可以为负数)。

    Returns:
        int: 用户修改后的最新总积分。
    """
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)

    current_points = int(record.get("points", 0))
    new_points = max(0, current_points + int(amount))
    record["points"] = new_points
    save_points_data(data)
    return new_points

def get_user_points(user_id: int, guild_id: int | None = None) -> int:
    """
    获取单个用户的积分。

    Args:
        user_id (int): 用户的ID。

    Returns:
        int: 用户的当前积分，如果不存在则为0。
    """
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)
    return int(record.get("points", 0))


def sign_in_user(user_id: int, guild_id: int, reward: int = 30) -> Tuple[bool, int]:
    """每日签到。返回(是否成功签到, 当前积分)。"""
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)

    today = datetime.now(TZ_CN).date().isoformat()
    if record.get("last_sign_date", "") == today:
        return False, int(record.get("points", 0))

    record["last_sign_date"] = today
    record["points"] = max(0, int(record.get("points", 0)) + int(reward))
    save_points_data(data)
    return True, int(record["points"])


def add_message_points(
    user_id: int,
    guild_id: int,
    amount: int,
    daily_cap: int,
) -> int:
    """发言加分，受每日上限限制，返回本次实际加分。"""
    if amount <= 0 or daily_cap <= 0:
        return 0

    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)

    today = datetime.now(TZ_CN).date().isoformat()
    if record.get("daily_msg_date", "") != today:
        record["daily_msg_date"] = today
        record["daily_msg_pts"] = 0

    today_pts = int(record.get("daily_msg_pts", 0))
    if today_pts >= daily_cap:
        return 0

    can_add = min(amount, daily_cap - today_pts)
    record["daily_msg_pts"] = today_pts + can_add
    record["points"] = max(0, int(record.get("points", 0)) + can_add)
    save_points_data(data)
    return can_add
