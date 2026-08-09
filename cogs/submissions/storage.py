import json
import os
import random
from datetime import datetime, timezone, timedelta

import config


DATA_FILE = "data/submissions.json"
TZ_CN = timezone(timedelta(hours=8))

KIND_REPO = "repo"
KIND_BUG = "bug"
KIND_RECOMMENDATION = "recommendation"

STATUS_OPEN = "open"
STATUS_REPLIED = "replied"
STATUS_EDITED = "edited"
STATUS_DELETED = "deleted"


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def _empty_data() -> dict:
    return {
        "version": 1,
        "panel_info": {},
        "submissions": {},
    }


def _round_shells(value) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    return round(max(0.0, amount), 1)


def _reward_range(kind: str, key: str) -> tuple[float, float]:
    cfg = getattr(config, "SUBMISSIONS", {})
    ranges = cfg.get("REWARD_RANGES", {}) if isinstance(cfg, dict) else {}
    default_ranges = {
        "base_repo": (0.5, 2.0),
        "base_bug": (0.8, 2.5),
        "base_recommendation": (1.0, 3.0),
        "reply_repo": (0.3, 1.5),
        "reply_bug": (0.5, 2.0),
    }
    raw = ranges.get(f"{key}_{kind}", default_ranges.get(f"{key}_{kind}", (0.5, 1.5)))
    try:
        low, high = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError):
        low, high = default_ranges.get(f"{key}_{kind}", (0.5, 1.5))
    if high < low:
        low, high = high, low
    return max(0.0, low), max(0.0, high)


def random_reward(kind: str, key: str = "base") -> float:
    low, high = _reward_range(kind, key)
    min_step = int(round(low * 10))
    max_step = int(round(high * 10))
    if max_step < min_step:
        max_step = min_step
    return round(random.randint(min_step, max_step) / 10, 1)


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return _empty_data()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_data()
    if not isinstance(raw, dict):
        return _empty_data()
    data = _empty_data()
    data.update(raw)
    if not isinstance(data.get("submissions"), dict):
        data["submissions"] = {}
    if not isinstance(data.get("panel_info"), dict):
        data["panel_info"] = {}
    return data


def save_data(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def set_panel_info(channel_id: int, message_id: int) -> None:
    data = load_data()
    data["panel_info"] = {"channel_id": str(channel_id), "message_id": str(message_id)}
    save_data(data)


def get_panel_info() -> dict:
    return load_data().get("panel_info", {})


def create_submission(
    *,
    guild_id: int,
    author_id: int,
    author_name: str,
    kind: str,
    fields: dict,
    base_reward: float,
) -> dict:
    data = load_data()
    now = _now_iso()
    submission_id = f"{int(datetime.now(TZ_CN).timestamp())}{random.randint(1000, 9999)}"
    record = {
        "id": submission_id,
        "guild_id": str(guild_id),
        "author_id": str(author_id),
        "author_name": author_name,
        "kind": kind,
        "fields": fields,
        "attachments": [],
        "channel_id": "",
        "message_id": "",
        "status": STATUS_OPEN,
        "base_reward": _round_shells(base_reward),
        "extra_reward": 0.0,
        "delete_penalty": 0.0,
        "replies": [],
        "useful_user_ids": [],
        "useful_reward_tiers": [],
        "comments": [],
        "created_at": now,
        "updated_at": now,
        "deleted_at": "",
    }
    data["submissions"][submission_id] = record
    save_data(data)
    return record


def save_submission(record: dict) -> dict:
    data = load_data()
    record["updated_at"] = _now_iso()
    data.setdefault("submissions", {})[str(record["id"])] = record
    save_data(data)
    return record


def get_submission(submission_id: str) -> dict | None:
    record = load_data().get("submissions", {}).get(str(submission_id))
    return record if isinstance(record, dict) else None


def find_by_message_id(message_id: int) -> dict | None:
    msg_id = str(message_id)
    for record in load_data().get("submissions", {}).values():
        if isinstance(record, dict) and record.get("message_id") == msg_id:
            return record
    return None


def list_user_submissions(user_id: int, guild_id: int | None = None, include_deleted: bool = False) -> list[dict]:
    uid = str(user_id)
    gid = str(guild_id) if guild_id else None
    rows = []
    for record in load_data().get("submissions", {}).values():
        if not isinstance(record, dict):
            continue
        if record.get("author_id") != uid:
            continue
        if gid and record.get("guild_id") != gid:
            continue
        if not include_deleted and record.get("status") == STATUS_DELETED:
            continue
        rows.append(record)
    return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)


def list_submissions(kind: str | None = None, include_deleted: bool = False) -> list[dict]:
    rows = []
    for record in load_data().get("submissions", {}).values():
        if not isinstance(record, dict):
            continue
        if kind and record.get("kind") != kind:
            continue
        if not include_deleted and record.get("status") == STATUS_DELETED:
            continue
        rows.append(record)
    return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)


def update_submission_fields(submission_id: str, fields: dict) -> dict | None:
    record = get_submission(submission_id)
    if not record or record.get("status") == STATUS_DELETED:
        return None
    record["fields"].update(fields)
    if record.get("status") == STATUS_OPEN:
        record["status"] = STATUS_EDITED
    return save_submission(record)


def mark_deleted(submission_id: str, penalty: float) -> dict | None:
    record = get_submission(submission_id)
    if not record:
        return None
    record["status"] = STATUS_DELETED
    record["deleted_at"] = _now_iso()
    record["delete_penalty"] = _round_shells(penalty)
    return save_submission(record)


def add_owner_reply(submission_id: str, user_id: int, user_name: str, content: str, reward: float) -> dict | None:
    record = get_submission(submission_id)
    if not record or record.get("status") == STATUS_DELETED:
        return None
    record.setdefault("replies", []).append({
        "user_id": str(user_id),
        "user_name": user_name,
        "content": content,
        "reward": _round_shells(reward),
        "created_at": _now_iso(),
    })
    record["extra_reward"] = _round_shells(float(record.get("extra_reward", 0) or 0) + reward)
    record["status"] = STATUS_REPLIED
    return save_submission(record)


def toggle_useful(submission_id: str, user_id: int) -> dict | None:
    record = get_submission(submission_id)
    if not record or record.get("status") == STATUS_DELETED:
        return None
    uid = str(user_id)
    users = record.setdefault("useful_user_ids", [])
    if uid in users:
        users.remove(uid)
        record["useful_user_ids"] = users
        record["updated_at"] = _now_iso()
        save_submission(record)
        return {"record": record, "added": False, "new_tier_rewards": []}

    users.append(uid)
    count = len(users)
    tiers = getattr(config, "SUBMISSION_USEFUL_TIERS", [
        {"count": 3, "reward": 1.0},
        {"count": 10, "reward": 3.0},
        {"count": 30, "reward": 8.0},
        {"count": 50, "reward": 15.0},
    ])
    triggered = set(str(x) for x in record.setdefault("useful_reward_tiers", []))
    new_rewards = []
    for tier in tiers:
        tier_count = int(tier.get("count", 0))
        if tier_count > 0 and count >= tier_count and str(tier_count) not in triggered:
            reward = _round_shells(tier.get("reward", 0))
            if reward > 0:
                new_rewards.append({"count": tier_count, "reward": reward})
                triggered.add(str(tier_count))
    record["useful_reward_tiers"] = sorted(triggered, key=lambda value: int(value))
    record["extra_reward"] = _round_shells(float(record.get("extra_reward", 0) or 0) + sum(x["reward"] for x in new_rewards))
    saved = save_submission(record)
    return {"record": saved, "added": True, "new_tier_rewards": new_rewards}


def add_comment(submission_id: str, user_id: int, user_name: str, content: str) -> dict | None:
    record = get_submission(submission_id)
    if not record or record.get("status") == STATUS_DELETED:
        return None
    record.setdefault("comments", []).append({
        "user_id": str(user_id),
        "user_name": user_name,
        "content": content,
        "created_at": _now_iso(),
    })
    return save_submission(record)
