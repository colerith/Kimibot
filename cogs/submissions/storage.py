import json
import os
import random
import threading
from datetime import datetime, timezone, timedelta

import config
from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace


DATA_FILE = "data/submissions.json"
TZ_CN = timezone(timedelta(hours=8))
_DATA_LOCK = threading.RLock()

KIND_REPO = "repo"
KIND_BUG = "bug"
KIND_RECOMMENDATION = "recommendation"
DAILY_KIND_LIMIT = 5

STATUS_OPEN = "open"
STATUS_REPLIED = "replied"
STATUS_EDITED = "edited"
STATUS_DELETED = "deleted"


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(TZ_CN).date().isoformat()


def _empty_data() -> dict:
    return {
        "version": 1,
        "panel_info": {},
        "submissions": {},
        "comment_rewards": {},
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


def random_comment_reward() -> float:
    cfg = getattr(config, "SUBMISSIONS", {})
    raw = cfg.get("COMMENT_REWARD_RANGE", (1.0, 5.0)) if isinstance(cfg, dict) else (1.0, 5.0)
    try:
        low, high = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError):
        low, high = 1.0, 5.0
    if high < low:
        low, high = high, low
    min_step = int(round(max(0.0, low) * 10))
    max_step = int(round(max(0.0, high) * 10))
    if max_step < min_step:
        max_step = min_step
    return round(random.randint(min_step, max_step) / 10, 1)


def grant_comment_reward(
    *,
    guild_id: int,
    user_id: int,
    requested_reward: float | None = None,
) -> dict:
    cfg = getattr(config, "SUBMISSIONS", {})
    daily_cap = float(cfg.get("COMMENT_DAILY_CAP", 15.0)) if isinstance(cfg, dict) else 15.0
    reward = random_comment_reward() if requested_reward is None else _round_shells(requested_reward)
    data = load_data()
    key = f"{guild_id}:{user_id}:{_today()}"
    used = _round_shells(data.setdefault("comment_rewards", {}).get(key, 0.0))
    if daily_cap <= 0 or used >= daily_cap:
        return {"awarded": 0.0, "used": used, "cap": daily_cap, "remaining": 0.0, "capped": True}

    remaining = _round_shells(daily_cap - used)
    awarded = _round_shells(min(reward, remaining))
    data["comment_rewards"][key] = _round_shells(used + awarded)
    save_data(data)
    return {
        "awarded": awarded,
        "used": data["comment_rewards"][key],
        "cap": daily_cap,
        "remaining": _round_shells(max(0.0, daily_cap - data["comment_rewards"][key])),
        "capped": awarded < reward or data["comment_rewards"][key] >= daily_cap,
    }


def load_data() -> dict:
    with _DATA_LOCK:
        raw = load_json_namespace("submissions", legacy_file=DATA_FILE, default=_empty_data())
        if not isinstance(raw, dict):
            return _empty_data()
        data = _empty_data()
        data.update(raw)
        if not isinstance(data.get("submissions"), dict):
            data["submissions"] = {}
        if not isinstance(data.get("panel_info"), dict):
            data["panel_info"] = {}
        if not isinstance(data.get("comment_rewards"), dict):
            data["comment_rewards"] = {}
        return data


def save_data(data: dict) -> None:
    with _DATA_LOCK:
        save_json_namespace("submissions", data)


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
    record, _ = create_submission_once(
        guild_id=guild_id,
        author_id=author_id,
        author_name=author_name,
        kind=kind,
        fields=fields,
        base_reward=base_reward,
        request_id="",
    )
    return record


def create_submission_once(
    *,
    guild_id: int,
    author_id: int,
    author_name: str,
    kind: str,
    fields: dict,
    base_reward: float,
    request_id: str,
) -> tuple[dict, bool]:
    """按草稿请求 ID 原子创建投稿，返回 (记录, 是否首次创建)。"""
    with _DATA_LOCK:
        data = load_data()
        normalized_request_id = str(request_id or "").strip()
        if normalized_request_id:
            for existing in data.get("submissions", {}).values():
                if not isinstance(existing, dict):
                    continue
                if (
                    existing.get("request_id") == normalized_request_id
                    and existing.get("guild_id") == str(guild_id)
                    and existing.get("author_id") == str(author_id)
                ):
                    return existing, False

        now = _now_iso()
        submission_id = f"{int(datetime.now(TZ_CN).timestamp())}{random.randint(1000, 9999)}"
        while submission_id in data["submissions"]:
            submission_id = f"{int(datetime.now(TZ_CN).timestamp())}{random.randint(1000, 9999)}"
        record = {
            "id": submission_id,
            "request_id": normalized_request_id,
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
        return record, True


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


def count_daily_submissions(
    *,
    guild_id: int,
    author_id: int,
    kind: str,
    day: str | None = None,
) -> int:
    gid = str(guild_id)
    uid = str(author_id)
    target_day = day or _today()
    count = 0
    for record in load_data().get("submissions", {}).values():
        if not isinstance(record, dict):
            continue
        if record.get("guild_id") != gid:
            continue
        if record.get("author_id") != uid:
            continue
        if record.get("kind") != kind:
            continue
        if str(record.get("created_at", "")).startswith(target_day):
            count += 1
    return count


def can_create_submission(
    *,
    guild_id: int,
    author_id: int,
    kind: str,
    limit: int = DAILY_KIND_LIMIT,
) -> dict:
    used = count_daily_submissions(guild_id=guild_id, author_id=author_id, kind=kind)
    max_count = max(0, int(limit))
    return {
        "allowed": used < max_count,
        "used": used,
        "limit": max_count,
        "remaining": max(0, max_count - used),
        "day": _today(),
    }


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
