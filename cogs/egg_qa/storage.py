import json
import os
import random
import threading
from functools import wraps
from datetime import datetime, timedelta, timezone

from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace


DATA_FILE = "data/egg_qa.json"
TZ_CN = timezone(timedelta(hours=8))
DAILY_QUESTION_LIMIT = 3
DAILY_REPLY_REWARD_CAP = 15
_DATA_LOCK = threading.RLock()

# 3～5 蛋壳占绝大多数；超过 5 后快速衰减，10～15 为极稀有彩蛋。
REWARD_AMOUNTS = list(range(3, 16))
REWARD_WEIGHTS = [6000, 3000, 900, 60, 25, 10, 4, 2, 1, 1, 1, 1, 1]
SELF_ANSWER_AMOUNTS = [1, 2, 3]
SELF_ANSWER_WEIGHTS = [6, 3, 1]


def _synchronized(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with _DATA_LOCK:
            return func(*args, **kwargs)

    return wrapped


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(TZ_CN).date().isoformat()


def _daily_key(guild_id: str | int, user_id: str | int, day: str) -> str:
    return f"{guild_id}:{user_id}:{day}"


def _build_daily_indexes(questions: dict) -> tuple[dict[str, int], dict[str, int]]:
    """旧数据只在迁移时遍历一次，后续任务面板直接查询日索引。"""
    question_counts: dict[str, int] = {}
    reply_totals: dict[str, int] = {}
    for question in questions.values():
        if not isinstance(question, dict):
            continue
        guild_id = str(question.get("guild_id") or "")
        author_id = str(question.get("author_id") or "")
        question_day = str(question.get("date") or question.get("created_at", ""))[:10]
        if guild_id and author_id and question_day:
            key = _daily_key(guild_id, author_id, question_day)
            question_counts[key] = question_counts.get(key, 0) + 1

        rewards = question.get("rewards", {})
        if not guild_id or not isinstance(rewards, dict):
            continue
        for reward_user_id, reward in rewards.items():
            if not isinstance(reward, dict):
                continue
            user_id = str(reward.get("user_id") or reward_user_id or "")
            reward_day = str(reward.get("date") or reward.get("created_at", ""))[:10]
            if not user_id or not reward_day:
                continue
            key = _daily_key(guild_id, user_id, reward_day)
            reply_totals[key] = reply_totals.get(key, 0) + max(0, int(reward.get("amount", 0) or 0))
    return question_counts, reply_totals


def _empty_data() -> dict:
    return {
        "version": 3,
        "questions": {},
        "panels": {},
        "author_subscriptions": {},
        "daily_question_counts": {},
        "daily_reply_totals": {},
    }


@_synchronized
def load_data() -> dict:
    raw = load_json_namespace("egg_qa", legacy_file=DATA_FILE, default=_empty_data())

    if not isinstance(raw, dict) or not isinstance(raw.get("questions"), dict):
        return _empty_data()
    panels = raw.get("panels", {})
    if not isinstance(panels, dict):
        panels = {}
    author_subscriptions = raw.get("author_subscriptions", {})
    if not isinstance(author_subscriptions, dict):
        author_subscriptions = {}
    needs_index_migration = (
        int(raw.get("version", 0) or 0) < 3
        or not isinstance(raw.get("daily_question_counts"), dict)
        or not isinstance(raw.get("daily_reply_totals"), dict)
    )
    if needs_index_migration:
        daily_question_counts, daily_reply_totals = _build_daily_indexes(raw["questions"])
    else:
        daily_question_counts = {
            str(key): max(0, int(value or 0))
            for key, value in raw["daily_question_counts"].items()
        }
        daily_reply_totals = {
            str(key): max(0, int(value or 0))
            for key, value in raw["daily_reply_totals"].items()
        }
    normalized = {
        "version": 3,
        "questions": raw["questions"],
        "panels": panels,
        "author_subscriptions": author_subscriptions,
        "daily_question_counts": daily_question_counts,
        "daily_reply_totals": daily_reply_totals,
    }
    if needs_index_migration:
        save_json_namespace("egg_qa", normalized)
    return normalized


@_synchronized
def save_data(data: dict) -> None:
    save_json_namespace("egg_qa", data)


@_synchronized
def get_daily_usage(user_id: int, guild_id: int) -> int:
    key = _daily_key(guild_id, user_id, _today())
    return max(0, int(load_data()["daily_question_counts"].get(key, 0) or 0))


@_synchronized
def get_daily_reply_reward_total(user_id: int, guild_id: int, day: str | None = None) -> int:
    """读取回答任务的权威日累计，不依赖可能归档的蛋壳流水。"""
    key = _daily_key(guild_id, user_id, str(day or _today()))
    return max(0, int(load_data()["daily_reply_totals"].get(key, 0) or 0))


@_synchronized
def save_panel(channel_id: int, message_id: int) -> None:
    data = load_data()
    data["panels"][str(channel_id)] = {
        "channel_id": str(channel_id),
        "message_id": str(message_id),
        "updated_at": _now_iso(),
    }
    save_data(data)


@_synchronized
def get_panel(channel_id: int) -> dict | None:
    panel = load_data()["panels"].get(str(channel_id))
    return panel if isinstance(panel, dict) else None


@_synchronized
def list_panels() -> list[dict]:
    return [row for row in load_data()["panels"].values() if isinstance(row, dict)]


@_synchronized
def remove_panel(channel_id: int, message_id: int | None = None) -> None:
    data = load_data()
    panel = data["panels"].get(str(channel_id))
    if not isinstance(panel, dict):
        return
    if message_id is not None and panel.get("message_id") != str(message_id):
        return
    data["panels"].pop(str(channel_id), None)
    save_data(data)


@_synchronized
def create_question(*, author_id: int, guild_id: int, channel_id: int, content: str) -> dict | None:
    data = load_data()
    uid = str(author_id)
    gid = str(guild_id)
    today = _today()
    daily_key = _daily_key(gid, uid, today)
    used = max(0, int(data["daily_question_counts"].get(daily_key, 0) or 0))
    if used >= DAILY_QUESTION_LIMIT:
        return None

    question_id = f"{int(datetime.now(TZ_CN).timestamp() * 1000)}{random.randint(100, 999)}"
    record = {
        "id": question_id,
        "guild_id": gid,
        "channel_id": str(channel_id),
        "message_id": "",
        "author_id": uid,
        "content": content,
        "date": today,
        "created_at": _now_iso(),
        "rewards": {},
    }
    data["questions"][question_id] = record
    data["daily_question_counts"][daily_key] = used + 1
    save_data(data)
    return record


@_synchronized
def finalize_question(question_id: str, message_id: int) -> None:
    data = load_data()
    record = data["questions"].get(str(question_id))
    if isinstance(record, dict):
        record["message_id"] = str(message_id)
        save_data(data)


@_synchronized
def cancel_question(question_id: str) -> None:
    data = load_data()
    record = data["questions"].pop(str(question_id), None)
    if not isinstance(record, dict):
        return

    question_day = str(record.get("date") or record.get("created_at", ""))[:10]
    question_key = _daily_key(record.get("guild_id", ""), record.get("author_id", ""), question_day)
    remaining_questions = max(0, int(data["daily_question_counts"].get(question_key, 0) or 0) - 1)
    if remaining_questions:
        data["daily_question_counts"][question_key] = remaining_questions
    else:
        data["daily_question_counts"].pop(question_key, None)

    rewards = record.get("rewards", {})
    if isinstance(rewards, dict):
        for reward_user_id, reward in rewards.items():
            if not isinstance(reward, dict):
                continue
            user_id = reward.get("user_id") or reward_user_id
            reward_day = str(reward.get("date") or reward.get("created_at", ""))[:10]
            reward_key = _daily_key(record.get("guild_id", ""), user_id, reward_day)
            remaining_reward = max(
                0,
                int(data["daily_reply_totals"].get(reward_key, 0) or 0)
                - max(0, int(reward.get("amount", 0) or 0)),
            )
            if remaining_reward:
                data["daily_reply_totals"][reward_key] = remaining_reward
            else:
                data["daily_reply_totals"].pop(reward_key, None)
    save_data(data)


@_synchronized
def find_question_by_message(message_id: int) -> dict | None:
    target = str(message_id)
    for record in load_data()["questions"].values():
        if isinstance(record, dict) and record.get("message_id") == target:
            return record
    return None


def _author_subscription_key(user_id: int | str, guild_id: int | str) -> str:
    return f"{guild_id}:{user_id}"


@_synchronized
def toggle_author_subscription(*, user_id: int, guild_id: int) -> bool:
    """切换用户对自己所发问题的自动私信订阅，返回切换后的状态。"""
    data = load_data()
    subscriptions = data["author_subscriptions"]
    key = _author_subscription_key(user_id, guild_id)
    if key in subscriptions:
        subscriptions.pop(key, None)
        enabled = False
    else:
        subscriptions[key] = {"enabled_at": _now_iso()}
        enabled = True
    save_data(data)
    return enabled


@_synchronized
def toggle_question_subscription(*, question_id: str, user_id: int) -> bool | None:
    """切换指定问题的追踪订阅；问题不存在时返回 None。"""
    data = load_data()
    record = data["questions"].get(str(question_id))
    if not isinstance(record, dict):
        return None

    subscribers = record.setdefault("subscribers", {})
    if not isinstance(subscribers, dict):
        subscribers = {}
        record["subscribers"] = subscribers
    uid = str(user_id)
    if uid in subscribers:
        subscribers.pop(uid, None)
        enabled = False
    else:
        subscribers[uid] = {"subscribed_at": _now_iso()}
        enabled = True
    save_data(data)
    return enabled


@_synchronized
def get_question_notification_subscribers(question_id: str) -> list[int]:
    """返回单题追踪者，以及开启了“我的提问自动订阅”的题主。"""
    data = load_data()
    record = data["questions"].get(str(question_id))
    if not isinstance(record, dict):
        return []

    subscriber_ids = set()
    subscribers = record.get("subscribers", {})
    if isinstance(subscribers, dict):
        subscriber_ids.update(str(uid) for uid in subscribers)

    author_id = str(record.get("author_id") or "")
    guild_id = str(record.get("guild_id") or "")
    key = _author_subscription_key(author_id, guild_id)
    if author_id and key in data["author_subscriptions"]:
        subscriber_ids.add(author_id)

    return [int(uid) for uid in subscriber_ids if uid.isdigit()]


@_synchronized
def claim_reply_reward(
    *,
    question_id: str,
    user_id: int,
    reply_message_id: int,
    is_self_answer: bool = False,
) -> dict | None:
    """原子式记录首次回复奖励；同一用户对同一问题只能成功一次。"""
    data = load_data()
    record = data["questions"].get(str(question_id))
    if not isinstance(record, dict):
        return None

    uid = str(user_id)
    rewards = record.setdefault("rewards", {})
    if uid in rewards:
        return None

    today = _today()
    total_key = _daily_key(record.get("guild_id", ""), uid, today)
    daily_total = max(0, int(data["daily_reply_totals"].get(total_key, 0) or 0))

    remaining = max(0, DAILY_REPLY_REWARD_CAP - daily_total)
    if remaining <= 0:
        return None

    if is_self_answer:
        amount = random.choices(SELF_ANSWER_AMOUNTS, weights=SELF_ANSWER_WEIGHTS, k=1)[0]
    else:
        amount = random.choices(REWARD_AMOUNTS, weights=REWARD_WEIGHTS, k=1)[0]
    amount = min(amount, remaining)
    reward = {
        "user_id": uid,
        "reply_message_id": str(reply_message_id),
        "amount": amount,
        "self_answer": bool(is_self_answer),
        "date": today,
        "daily_total_after": daily_total + amount,
        "created_at": _now_iso(),
    }
    rewards[uid] = reward
    data["daily_reply_totals"][total_key] = daily_total + amount
    save_data(data)
    return reward


@_synchronized
def revoke_reply_reward(*, question_id: str, user_id: int, reply_message_id: int) -> None:
    """蛋壳入账失败时撤销占位，允许用户稍后重新回答。"""
    data = load_data()
    record = data["questions"].get(str(question_id))
    if not isinstance(record, dict):
        return
    rewards = record.get("rewards", {})
    reward = rewards.get(str(user_id)) if isinstance(rewards, dict) else None
    if isinstance(reward, dict) and reward.get("reply_message_id") == str(reply_message_id):
        rewards.pop(str(user_id), None)
        reward_day = str(reward.get("date") or reward.get("created_at", ""))[:10]
        total_key = _daily_key(record.get("guild_id", ""), user_id, reward_day)
        remaining = max(
            0,
            int(data["daily_reply_totals"].get(total_key, 0) or 0)
            - max(0, int(reward.get("amount", 0) or 0)),
        )
        if remaining:
            data["daily_reply_totals"][total_key] = remaining
        else:
            data["daily_reply_totals"].pop(total_key, None)
        save_data(data)
