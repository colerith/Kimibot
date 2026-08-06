# cogs/points/storage.py

import json
import math
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import config

POINTS_DATA_FILE = "data/user_points.json"
RANDOM_EVENTS_FILE = Path(__file__).with_name("random_events.json")
TZ_CN = timezone(timedelta(hours=8))

SHELL_PRECISION = 1
LEGACY_POINTS_TO_SHELLS = 0.1

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


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


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
    return record


def _normalize_points_data(raw_data: dict) -> dict:
    """兼容旧积分格式并统一为蛋壳结构。"""
    if not isinstance(raw_data, dict):
        return {"version": 3, "users": {}, "daily_signins": {}, "daily_forum_rewards": {}, "transactions": []}

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
            "transactions": raw_data.get("transactions", []),
        }

    users = {}
    for uid, pts in raw_data.items():
        try:
            shells = float(pts) * LEGACY_POINTS_TO_SHELLS
        except (TypeError, ValueError):
            shells = 0.0
        users[str(uid)] = _normalize_record({"shells": shells})

    return {"version": 3, "users": users, "daily_signins": {}, "daily_forum_rewards": {}, "transactions": []}


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
    record.setdefault("transactions", []).append(tx)
    record["transactions"] = record["transactions"][-50:]
    data.setdefault("transactions", []).append(tx)
    data["transactions"] = data["transactions"][-500:]


def load_points_data():
    if not os.path.exists(POINTS_DATA_FILE):
        return {"version": 3, "users": {}, "daily_signins": {}, "daily_forum_rewards": {}, "transactions": []}
    try:
        with open(POINTS_DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return _normalize_points_data(raw)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"version": 3, "users": {}, "daily_signins": {}, "daily_forum_rewards": {}, "transactions": []}


def save_points_data(data):
    os.makedirs(os.path.dirname(POINTS_DATA_FILE), exist_ok=True)
    normalized = _normalize_points_data(data)
    with open(POINTS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=4, ensure_ascii=False)


def modify_user_points(
    user_id: int,
    amount: float,
    guild_id: int | None = None,
    *,
    source: str = "manual",
    reason: str = "",
) -> float:
    """兼容旧入口：修改用户蛋壳余额，返回最新余额。"""
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)

    current_shells = _round_shells(record.get("shells", 0))
    delta = _round_delta(amount)
    new_shells = _round_shells(current_shells + delta)
    actual_delta = _round_delta(new_shells - current_shells)

    record["shells"] = new_shells
    record["points"] = new_shells
    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=actual_delta,
        source=source,
        reason=reason,
    )
    save_points_data(data)
    return new_shells


def get_user_points(user_id: int, guild_id: int | None = None) -> float:
    """兼容旧入口：获取用户蛋壳余额。"""
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)
    return _round_shells(record.get("shells", 0))


def get_user_summary(user_id: int, guild_id: int | None = None) -> dict:
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)
    return {
        "shells": _round_shells(record.get("shells", 0)),
        "last_sign_date": record.get("last_sign_date", ""),
        "streak_days": int(record.get("streak_days", 0)),
        "daily_msg_count": int(record.get("daily_msg_count", 0)),
        "acceleration_days": int(record.get("acceleration_days", 0)),
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
        {"id": "day_1", "label": "减1天", "days": 1, "cost": 8.0},
        {"id": "day_5", "label": "减5天", "days": 5, "cost": 35.0},
        {"id": "day_10", "label": "减10天", "days": 10, "cost": 60.0},
    ]


def get_acceleration_status(user_id: int, guild_id: int | None = None) -> dict:
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)
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
        "tier_id": tier["id"],
        "label": tier["label"],
        "configured_days": int(tier["days"]),
        "effective_days": effective_days,
        "cost": cost,
    }
    record.setdefault("acceleration_cards", []).append(card_record)

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

    return valid_events or DEFAULT_RANDOM_EVENTS["events"]


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
    data = load_points_data()
    today = _today()
    daily_key = f"{guild_id}:{today}"
    signers = data.get("daily_signins", {}).get(daily_key, [])
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


def sign_in_user(user_id: int, guild_id: int, reward: float = 1.0) -> dict:
    """每日报到，返回详细蛋壳结算结果。"""
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)
    today = _today()

    if record.get("last_sign_date", "") == today:
        return {
            "success": False,
            "balance": _round_shells(record.get("shells", 0)),
            "streak_days": int(record.get("streak_days", 0)),
            "message": "今日已报到",
        }

    streak_days = _calculate_streak(
        str(record.get("last_sign_date", "")),
        today,
        int(record.get("streak_days", 0)),
    )
    daily_msg_count = int(record.get("daily_msg_count", 0))
    if record.get("daily_msg_date", "") != today:
        daily_msg_count = 0

    base_reward = _round_delta(reward)
    streak_rate = get_streak_bonus_rate(streak_days)
    activity_rate = get_activity_bonus_rate(daily_msg_count)
    bonus_amount = _round_delta(base_reward * (streak_rate + activity_rate))

    rank = _register_daily_rank(data, guild_id, user_id, today)
    rank_bonus = _round_delta(random.randint(1, 19) / 10) if rank <= 10 else 0.0

    event = _pick_random_event()
    event_delta = _round_delta(event.get("delta", 0))

    before = _round_shells(record.get("shells", 0))
    total_delta = _round_delta(base_reward + bonus_amount + rank_bonus + event_delta)
    after = _round_shells(before + total_delta)
    actual_delta = _round_delta(after - before)

    record["last_sign_date"] = today
    record["streak_days"] = streak_days
    record["shells"] = after
    record["points"] = after

    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=actual_delta,
        source="sign_in",
        reason=f"rank={rank};event={event['id']}",
    )
    save_points_data(data)

    return {
        "success": True,
        "balance": after,
        "base_reward": base_reward,
        "bonus_amount": bonus_amount,
        "streak_rate": streak_rate,
        "activity_rate": activity_rate,
        "streak_days": streak_days,
        "daily_msg_count": daily_msg_count,
        "rank": rank,
        "rank_bonus": rank_bonus,
        "event": event,
        "event_delta": event_delta,
        "total_delta": actual_delta,
    }


def record_message_activity(user_id: int, guild_id: int) -> int:
    """记录每日有效发言次数，不直接发放蛋壳。"""
    data = load_points_data()
    record, _ = _ensure_user_record(data, user_id, guild_id)
    today = _today()
    if record.get("daily_msg_date", "") != today:
        record["daily_msg_date"] = today
        record["daily_msg_count"] = 0
    record["daily_msg_count"] = int(record.get("daily_msg_count", 0)) + 1
    save_points_data(data)
    return int(record["daily_msg_count"])


def add_message_points(
    user_id: int,
    guild_id: int,
    amount: float = 0,
    daily_cap: float = 0,
) -> int:
    """兼容旧入口：新版只记录发言活跃，不再单条发放蛋壳。"""
    return record_message_activity(user_id, guild_id)


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
    before = _round_shells(record.get("shells", 0))
    after = _round_shells(before + can_add)
    actual_delta = _round_delta(after - before)

    record["daily_post_pts"] = _round_delta(today_pts + actual_delta)
    record["shells"] = after
    record["points"] = after
    _append_transaction(
        data,
        record,
        user_id=user_id,
        guild_id=guild_id,
        amount=actual_delta,
        source="forum_post",
        reason="legacy_forum_post_reward",
    )
    save_points_data(data)
    return actual_delta


def reward_daily_forum_post(
    user_id: int,
    guild_id: int,
    channel_id: int,
    thread_id: int,
    *,
    amount: float,
    daily_limit: int,
) -> dict:
    """指定论坛频道每日前 N 帖奖励。"""
    data = load_points_data()
    today = _today()
    reward_key = f"{guild_id}:{channel_id}:{today}"
    rewards = data.setdefault("daily_forum_rewards", {}).setdefault(reward_key, [])

    thread_id_str = str(thread_id)
    if any(row.get("thread_id") == thread_id_str for row in rewards if isinstance(row, dict)):
        return {"success": False, "reason": "duplicate_thread", "rank": None, "amount": 0.0}

    if len(rewards) >= daily_limit:
        return {"success": False, "reason": "daily_limit_reached", "rank": len(rewards) + 1, "amount": 0.0}

    record, _ = _ensure_user_record(data, user_id, guild_id)
    before = _round_shells(record.get("shells", 0))
    delta = _round_delta(amount)
    after = _round_shells(before + delta)
    actual_delta = _round_delta(after - before)

    row = {
        "thread_id": thread_id_str,
        "user_id": str(user_id),
        "time": _now_iso(),
        "amount": actual_delta,
        "rank": len(rewards) + 1,
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
        reason=f"channel={channel_id};thread={thread_id};rank={row['rank']}",
    )
    save_points_data(data)
    return {"success": True, "reason": "rewarded", "rank": row["rank"], "amount": actual_delta}
