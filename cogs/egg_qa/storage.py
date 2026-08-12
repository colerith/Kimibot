import json
import os
import random
from datetime import datetime, timedelta, timezone


DATA_FILE = "data/egg_qa.json"
TZ_CN = timezone(timedelta(hours=8))
DAILY_QUESTION_LIMIT = 3
DAILY_REPLY_REWARD_CAP = 15

# 3～5 蛋壳占绝大多数；超过 5 后快速衰减，10～15 为极稀有彩蛋。
REWARD_AMOUNTS = list(range(3, 16))
REWARD_WEIGHTS = [6000, 3000, 900, 60, 25, 10, 4, 2, 1, 1, 1, 1, 1]
SELF_ANSWER_AMOUNTS = [1, 2, 3]
SELF_ANSWER_WEIGHTS = [6, 3, 1]


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(TZ_CN).date().isoformat()


def _empty_data() -> dict:
    return {"version": 1, "questions": {}, "panels": {}}


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
    return {"version": 1, "questions": raw["questions"], "panels": panels}


def save_data(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


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


def save_panel(channel_id: int, message_id: int) -> None:
    data = load_data()
    data["panels"][str(channel_id)] = {
        "channel_id": str(channel_id),
        "message_id": str(message_id),
        "updated_at": _now_iso(),
    }
    save_data(data)


def get_panel(channel_id: int) -> dict | None:
    panel = load_data()["panels"].get(str(channel_id))
    return panel if isinstance(panel, dict) else None


def list_panels() -> list[dict]:
    return [row for row in load_data()["panels"].values() if isinstance(row, dict)]


def remove_panel(channel_id: int, message_id: int | None = None) -> None:
    data = load_data()
    panel = data["panels"].get(str(channel_id))
    if not isinstance(panel, dict):
        return
    if message_id is not None and panel.get("message_id") != str(message_id):
        return
    data["panels"].pop(str(channel_id), None)
    save_data(data)


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


def finalize_question(question_id: str, message_id: int) -> None:
    data = load_data()
    record = data["questions"].get(str(question_id))
    if isinstance(record, dict):
        record["message_id"] = str(message_id)
        save_data(data)


def cancel_question(question_id: str) -> None:
    data = load_data()
    if data["questions"].pop(str(question_id), None) is not None:
        save_data(data)


def find_question_by_message(message_id: int) -> dict | None:
    target = str(message_id)
    for record in load_data()["questions"].values():
        if isinstance(record, dict) and record.get("message_id") == target:
            return record
    return None


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
