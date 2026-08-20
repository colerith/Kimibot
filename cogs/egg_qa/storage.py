import json
import os
import random
import threading
from functools import wraps
from datetime import datetime, timedelta, timezone


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


def _empty_data() -> dict:
    return {"version": 2, "questions": {}, "panels": {}, "author_subscriptions": {}}


@_synchronized
def load_data() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError):
        return _empty_data()

    if not isinstance(raw, dict) or not isinstance(raw.get("questions"), dict):
        return _empty_data()
    panels = raw.get("panels", {})
    if not isinstance(panels, dict):
        panels = {}
    author_subscriptions = raw.get("author_subscriptions", {})
    if not isinstance(author_subscriptions, dict):
        author_subscriptions = {}
    return {
        "version": 2,
        "questions": raw["questions"],
        "panels": panels,
        "author_subscriptions": author_subscriptions,
    }


@_synchronized
def save_data(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    temp_file = f"{DATA_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_file, DATA_FILE)
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass


@_synchronized
def get_daily_usage(user_id: int, guild_id: int) -> int:
    uid = str(user_id)
    gid = str(guild_id)
    today = _today()
    return sum(
        1
        for row in load_data()["questions"].values()
        if isinstance(row, dict)
        and row.get("author_id") == uid
        and row.get("guild_id") == gid
        and row.get("date") == today
    )


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
    used = sum(
        1
        for row in data["questions"].values()
        if isinstance(row, dict)
        and row.get("author_id") == uid
        and row.get("guild_id") == gid
        and row.get("date") == today
    )
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
    if data["questions"].pop(str(question_id), None) is not None:
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
    daily_total = 0
    for question in data["questions"].values():
        if not isinstance(question, dict) or question.get("guild_id") != record.get("guild_id"):
            continue
        for old_reward in question.get("rewards", {}).values():
            if not isinstance(old_reward, dict) or old_reward.get("user_id") != uid:
                continue
            reward_date = str(old_reward.get("date") or old_reward.get("created_at", ""))[:10]
            if reward_date == today:
                daily_total += max(0, int(old_reward.get("amount", 0) or 0))

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
        save_data(data)
