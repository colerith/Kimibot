import json
import os
import random
from datetime import datetime, timedelta, timezone


DATA_FILE = "data/egg_qa.json"
TZ_CN = timezone(timedelta(hours=8))
DAILY_QUESTION_LIMIT = 3

# 低额奖励常见，高额奖励逐渐稀有。
REWARD_AMOUNTS = list(range(3, 16))
REWARD_WEIGHTS = [60, 50, 42, 34, 26, 20, 16, 12, 8, 6, 4, 2, 1]
SELF_ANSWER_AMOUNTS = [1, 2, 3]
SELF_ANSWER_WEIGHTS = [6, 3, 1]


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(TZ_CN).date().isoformat()


def _empty_data() -> dict:
    return {"version": 1, "questions": {}}


def load_data() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError):
        return _empty_data()

    if not isinstance(raw, dict) or not isinstance(raw.get("questions"), dict):
        return _empty_data()
    return {"version": 1, "questions": raw["questions"]}


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

    if is_self_answer:
        amount = random.choices(SELF_ANSWER_AMOUNTS, weights=SELF_ANSWER_WEIGHTS, k=1)[0]
    else:
        amount = random.choices(REWARD_AMOUNTS, weights=REWARD_WEIGHTS, k=1)[0]
    reward = {
        "user_id": uid,
        "reply_message_id": str(reply_message_id),
        "amount": amount,
        "self_answer": bool(is_self_answer),
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
