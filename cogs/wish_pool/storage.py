import copy
import threading
import uuid
from datetime import datetime, timezone

from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace


NAMESPACE = "wish_pool"
LEGACY_FILE = "data/wish_pool.json"
DEFAULT_DATA = {
    "version": 1,
    "panel_info": {},
    "entries": {},
}
_LOCK = threading.RLock()


def _load() -> dict:
    data = load_json_namespace(NAMESPACE, legacy_file=LEGACY_FILE, default=DEFAULT_DATA)
    if not isinstance(data, dict):
        data = copy.deepcopy(DEFAULT_DATA)
    data.setdefault("version", 1)
    data.setdefault("panel_info", {})
    data.setdefault("entries", {})
    return data


def _save(data: dict) -> None:
    save_json_namespace(NAMESPACE, data)


def create_entry(
    *,
    guild_id: int,
    author_id: int,
    author_name: str,
    kind: str,
    subject: str,
    content: str,
    scope: str = "phone",
    category: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        data = _load()
        while True:
            entry_id = uuid.uuid4().hex[:10]
            if entry_id not in data["entries"]:
                break
        entry = {
            "id": entry_id,
            "guild_id": str(guild_id),
            "channel_id": "",
            "message_id": "",
            "author_id": str(author_id),
            "author_name": str(author_name)[:100],
            "scope": scope,
            "kind": kind,
            "category": str(category)[:100],
            "subject": str(subject).strip()[:120],
            "content": str(content).strip()[:3000],
            "status": "pending",
            "status_reason": "",
            "replies": [],
            "created_at": now,
            "updated_at": now,
        }
        data["entries"][entry_id] = entry
        _save(data)
        return copy.deepcopy(entry)


def get_entry(entry_id: str) -> dict | None:
    with _LOCK:
        entry = _load()["entries"].get(str(entry_id))
        return copy.deepcopy(entry) if isinstance(entry, dict) else None


def find_entry_by_message_id(message_id: int | str) -> dict | None:
    needle = str(message_id)
    with _LOCK:
        for entry in _load()["entries"].values():
            if isinstance(entry, dict) and str(entry.get("message_id", "")) == needle:
                return copy.deepcopy(entry)
    return None


def bind_entry_message(entry_id: str, *, channel_id: int, message_id: int) -> dict | None:
    with _LOCK:
        data = _load()
        entry = data["entries"].get(str(entry_id))
        if not isinstance(entry, dict):
            return None
        entry["channel_id"] = str(channel_id)
        entry["message_id"] = str(message_id)
        entry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save(data)
        return copy.deepcopy(entry)


def delete_unpublished_entry(entry_id: str) -> bool:
    """Only discard a draft that never reached Discord."""
    with _LOCK:
        data = _load()
        entry = data["entries"].get(str(entry_id))
        if not isinstance(entry, dict) or entry.get("message_id"):
            return False
        del data["entries"][str(entry_id)]
        _save(data)
        return True


def set_entry_status(entry_id: str, status: str, *, reason: str = "") -> dict | None:
    if status not in {"accepted", "implemented", "rejected"}:
        raise ValueError("invalid wish status")
    with _LOCK:
        data = _load()
        entry = data["entries"].get(str(entry_id))
        if not isinstance(entry, dict):
            return None
        entry["status"] = status
        entry["status_reason"] = str(reason).strip()[:1000] if status == "rejected" else ""
        entry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save(data)
        return copy.deepcopy(entry)


def add_entry_reply(entry_id: str, *, role: str, user_id: int, user_name: str, content: str) -> dict | None:
    if role not in {"owner", "author"}:
        raise ValueError("invalid reply role")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        data = _load()
        entry = data["entries"].get(str(entry_id))
        if not isinstance(entry, dict):
            return None
        replies = entry.setdefault("replies", [])
        replies.append({
            "role": role,
            "user_id": str(user_id),
            "user_name": str(user_name)[:100],
            "content": str(content).strip()[:1500],
            "created_at": now,
        })
        entry["updated_at"] = now
        _save(data)
        return copy.deepcopy(entry)


def get_panel_info(guild_id: int) -> dict:
    with _LOCK:
        value = _load()["panel_info"].get(str(guild_id), {})
        return copy.deepcopy(value) if isinstance(value, dict) else {}


def set_panel_info(guild_id: int, *, channel_id: int, message_id: int) -> None:
    with _LOCK:
        data = _load()
        data["panel_info"][str(guild_id)] = {
            "channel_id": str(channel_id),
            "message_id": str(message_id),
        }
        _save(data)
