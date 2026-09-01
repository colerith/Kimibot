import json
import os
import random
import re
import threading
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit

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

_MEANINGFUL_CHAR_RE = re.compile(r"[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff]")


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
        "meaningless_submission_users": {},
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


def parse_manual_reply_reward(value: str) -> float | None:
    """解析回信手填奖励；空白表示继续使用默认随机奖励。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    if not re.fullmatch(r"(?:\d+(?:\.\d)?|\.\d)", raw):
        raise ValueError("追加蛋壳只能填写正数，最多保留 1 位小数")
    try:
        amount = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError("追加蛋壳格式不正确") from error
    cfg = getattr(config, "SUBMISSIONS", {})
    maximum = Decimal(str(cfg.get("MANUAL_REPLY_REWARD_MAX", 100.0))) if isinstance(cfg, dict) else Decimal("100")
    if amount <= 0:
        raise ValueError("追加蛋壳必须大于 0")
    if amount > maximum:
        raise ValueError(f"单次手动追加不能超过 {maximum.normalize()} 蛋壳")
    return round(float(amount), 1)


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


def get_daily_comment_reward_usage(*, guild_id: int, user_id: int, day: str | None = None) -> float:
    """读取盖楼任务的权威日累计，不依赖蛋壳流水。"""
    key = f"{guild_id}:{user_id}:{day or _today()}"
    return _round_shells(load_data().get("comment_rewards", {}).get(key, 0.0))


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
        if not isinstance(data.get("meaningless_submission_users"), dict):
            data["meaningless_submission_users"] = {}
        return data


def validate_submission_content(content: str) -> dict:
    """检查正文长度与明显的重复灌水模式。"""
    cfg = getattr(config, "SUBMISSIONS", {})
    min_length = int(cfg.get("MIN_CONTENT_LENGTH", 15)) if isinstance(cfg, dict) else 15
    normalized = "".join(_MEANINGFUL_CHAR_RE.findall(str(content or ""))).casefold()
    meaningful_length = len(normalized)
    if meaningful_length < min_length:
        return {
            "valid": False,
            "reason": "too_short",
            "length": meaningful_length,
            "minimum": min_length,
        }

    # 完全由一个短片段反复拼接（如“嘎哒嘎哒……”）构成。
    repeated_unit = any(
        meaningful_length >= unit_len * 3
        and normalized == normalized[:unit_len] * (meaningful_length // unit_len)
        for unit_len in range(1, min(9, meaningful_length // 3 + 1))
        if meaningful_length % unit_len == 0
    )
    frequencies = {char: normalized.count(char) for char in set(normalized)}
    dominant_ratio = max(frequencies.values(), default=0) / meaningful_length
    low_variety = len(frequencies) <= 2
    long_same_run = bool(re.search(r"(.)\1{5,}", normalized))
    if repeated_unit or low_variety or dominant_ratio >= 0.65 or long_same_run:
        return {
            "valid": False,
            "reason": "repetitive",
            "length": meaningful_length,
            "minimum": min_length,
        }
    return {
        "valid": True,
        "reason": "",
        "length": meaningful_length,
        "minimum": min_length,
    }


def get_meaningless_submission_status(*, guild_id: int, user_id: int) -> dict:
    data = load_data()
    key = f"{guild_id}:{user_id}"
    raw = data.get("meaningless_submission_users", {}).get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    count = max(0, int(raw.get("count", 0) or 0))
    return {
        "count": count,
        "blocked_today": str(raw.get("blocked_day", "")) == _today(),
        "blocked_day": str(raw.get("blocked_day", "")),
        "warning_count": max(0, int(raw.get("warning_count", 0) or 0)),
    }


def record_meaningless_withdrawal(
    submission_id: str,
    moderator_id: int,
    reason: str = "无意义灌水投稿",
) -> dict | None:
    """原子撤回水投稿、记录累计次数并封禁投稿者当日投稿。"""
    with _DATA_LOCK:
        data = load_data()
        record = data.get("submissions", {}).get(str(submission_id))
        if not isinstance(record, dict):
            return None
        moderation = record.setdefault("moderation", {})
        if moderation.get("meaningless_withdrawn"):
            return {
                "record": record,
                "duplicate": True,
                "count": int(moderation.get("meaningless_count", 0) or 0),
                "should_warn": False,
                "penalty": _round_shells(record.get("delete_penalty", 0)),
            }
        if record.get("status") == STATUS_DELETED:
            return None

        author_id = str(record.get("author_id", ""))
        guild_id = str(record.get("guild_id", ""))
        key = f"{guild_id}:{author_id}"
        users = data.setdefault("meaningless_submission_users", {})
        user_status = users.get(key, {})
        if not isinstance(user_status, dict):
            user_status = {}
        count = max(0, int(user_status.get("count", 0) or 0)) + 1
        warning_count = max(0, int(user_status.get("warning_count", 0) or 0))
        cfg = getattr(config, "SUBMISSIONS", {})
        threshold = int(cfg.get("MEANINGLESS_WARNING_THRESHOLD", 3)) if isinstance(cfg, dict) else 3
        threshold = max(1, threshold)
        should_warn = count // threshold > warning_count

        now = _now_iso()
        penalty = _round_shells(
            float(record.get("base_reward", 0) or 0)
            + float(record.get("extra_reward", 0) or 0)
        )
        record["status"] = STATUS_DELETED
        record["deleted_at"] = now
        record["updated_at"] = now
        record["delete_penalty"] = penalty
        moderation.update({
            "meaningless_withdrawn": True,
            "meaningless_count": count,
            "moderator_id": str(moderator_id),
            "withdrawal_reason": str(reason or "无意义灌水投稿")[:500],
            "withdrawn_at": now,
        })
        users[key] = {
            **user_status,
            "count": count,
            "blocked_day": _today(),
            "warning_count": warning_count,
            "last_submission_id": str(submission_id),
            "last_withdrawn_at": now,
        }
        data["submissions"][str(submission_id)] = record
        save_data(data)
        return {
            "record": record,
            "duplicate": False,
            "count": count,
            "should_warn": should_warn,
            "penalty": penalty,
        }


def mark_meaningless_warning_issued(*, guild_id: int, user_id: int, warning_count: int) -> None:
    with _DATA_LOCK:
        data = load_data()
        key = f"{guild_id}:{user_id}"
        users = data.setdefault("meaningless_submission_users", {})
        status = users.get(key, {})
        if not isinstance(status, dict):
            status = {}
        status["warning_count"] = max(
            int(status.get("warning_count", 0) or 0),
            max(0, int(warning_count)),
        )
        users[key] = status
        save_data(data)


def save_data(data: dict) -> None:
    with _DATA_LOCK:
        save_json_namespace("submissions", data)


def set_panel_info(channel_id: int, message_id: int) -> None:
    data = load_data()
    data["panel_info"] = {"channel_id": str(channel_id), "message_id": str(message_id)}
    save_data(data)


def get_panel_info() -> dict:
    return load_data().get("panel_info", {})


def clear_panel_info(channel_id: int) -> dict | None:
    """Clear the main-panel pointer only if it targets the given channel."""
    with _DATA_LOCK:
        data = load_data()
        panel = data.get("panel_info", {})
        if not isinstance(panel, dict) or str(panel.get("channel_id", "")) != str(channel_id):
            return None
        removed = dict(panel)
        data["panel_info"] = {}
        save_data(data)
        return removed


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
            "notifications_enabled": True,
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


def submission_notifications_enabled(record: dict | None) -> bool:
    """旧投稿没有该字段时保持原有提醒行为。"""
    return bool(record is not None and record.get("notifications_enabled", True))


def set_submission_notifications(
    submission_id: str,
    author_id: int,
    enabled: bool,
) -> dict | None:
    """仅投稿者可修改单条投稿的提醒状态。"""
    with _DATA_LOCK:
        data = load_data()
        record = data.get("submissions", {}).get(str(submission_id))
        if not isinstance(record, dict):
            return None
        if record.get("author_id") != str(author_id) or record.get("status") == STATUS_DELETED:
            return None
        record["notifications_enabled"] = bool(enabled)
        record["updated_at"] = _now_iso()
        data["submissions"][str(submission_id)] = record
        save_data(data)
        return record


def find_by_message_id(message_id: int) -> dict | None:
    msg_id = str(message_id)
    for record in load_data().get("submissions", {}).values():
        if isinstance(record, dict) and record.get("message_id") == msg_id:
            return record
    return None


def _attachment_url_key(url: str) -> str:
    """忽略 Discord CDN 临时签名，仅保留稳定的附件路径。"""
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return ""
    return parsed.path.rstrip("/").casefold()


def find_by_attachment_urls(attachment_urls) -> dict | None:
    target_keys = {
        key
        for key in (_attachment_url_key(url) for url in (attachment_urls or []))
        if key
    }
    if not target_keys:
        return None
    for record in load_data().get("submissions", {}).values():
        if not isinstance(record, dict):
            continue
        record_keys = {
            key
            for key in (_attachment_url_key(url) for url in record.get("attachments", []))
            if key
        }
        if target_keys & record_keys:
            return record
    return None


def recover_submission_from_embed_data(
    *,
    guild_id: int,
    channel_id: int,
    message_id: int,
    embed_data: dict,
    attachment_urls=None,
) -> dict | None:
    """从机器人标准投稿 Embed 重建意外丢失的投稿索引。"""
    if not isinstance(embed_data, dict):
        return None
    footer = embed_data.get("footer", {})
    footer_text = str(footer.get("text", "")) if isinstance(footer, dict) else ""
    id_match = re.search(r"投稿\s*#([0-9]{8,})", footer_text)
    reward_match = re.search(r"已奖励\s*([0-9]+(?:\.[0-9]+)?)\s*蛋壳", footer_text)
    if not id_match or not reward_match:
        return None

    submission_id = id_match.group(1)
    existing = get_submission(submission_id)
    if existing:
        return existing

    author_id = ""
    author_name = "未知投稿人"
    recovered_fields = {}
    for field in embed_data.get("fields", []):
        if not isinstance(field, dict):
            continue
        name = str(field.get("name", ""))
        value = str(field.get("value", ""))
        if "投稿人" in name or "投稿者" in name:
            mention = re.search(r"<@!?(\d{15,20})>", value)
            if mention:
                author_id = mention.group(1)
        elif "投稿内容" in name:
            recovered_fields["content"] = value
        elif any(label in name for label in ("标题", "对象")):
            recovered_fields["target"] = value
    if not author_id:
        return None

    title = str(embed_data.get("title", ""))
    if "安利" in title:
        kind = KIND_RECOMMENDATION
    elif "捉虫" in title:
        kind = KIND_BUG
    elif "repo" in title.casefold():
        kind = KIND_REPO
    else:
        return None

    now = _now_iso()
    reward = _round_shells(reward_match.group(1))
    record = {
        "id": submission_id,
        "request_id": "",
        "guild_id": str(guild_id),
        "author_id": author_id,
        "author_name": author_name,
        "kind": kind,
        "fields": recovered_fields,
        "attachments": [str(url) for url in (attachment_urls or []) if url][:9],
        "channel_id": str(channel_id),
        "message_id": str(message_id),
        "status": STATUS_OPEN,
        "base_reward": reward,
        "extra_reward": 0.0,
        "delete_penalty": 0.0,
        "replies": [],
        "useful_user_ids": [],
        "useful_reward_tiers": [],
        "comments": [],
        "notifications_enabled": True,
        "created_at": now,
        "updated_at": now,
        "deleted_at": "",
        "moderation": {"recovered_from_message": True, "recovered_at": now},
    }
    return save_submission(record)


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
    abuse_status = get_meaningless_submission_status(guild_id=guild_id, user_id=author_id)
    if abuse_status["blocked_today"]:
        return {
            "allowed": False,
            "blocked": True,
            "used": 0,
            "limit": max(0, int(limit)),
            "remaining": 0,
            "day": _today(),
            "meaningless_count": abuse_status["count"],
        }
    used = count_daily_submissions(guild_id=guild_id, author_id=author_id, kind=kind)
    max_count = max(0, int(limit))
    return {
        "allowed": used < max_count,
        "blocked": False,
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
