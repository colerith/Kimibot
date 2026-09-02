import json
import math
import os
import secrets
import threading
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Any

from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace

DATA_FILE = "data/red_packets.json"
TZ_CN = timezone(timedelta(hours=8))
SHELL_PRECISION = 1
EXPIRE_HOURS = 24
_DATA_LOCK = threading.RLock()


def _locked(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with _DATA_LOCK:
            return func(*args, **kwargs)
    return wrapper


def now_cn() -> datetime:
    return datetime.now(TZ_CN)


def now_iso() -> str:
    return now_cn().isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return now_cn()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ_CN)
    return dt.astimezone(TZ_CN)


def round_shells(value: float | int | str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    if not math.isfinite(amount):
        amount = 0.0
    return round(max(0.0, amount), SHELL_PRECISION)


def format_shells(value: float | int | str) -> str:
    amount = round_shells(value)
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:.1f}"


def load_data() -> dict[str, Any]:
    data = load_json_namespace(
        "red_packets", legacy_file=DATA_FILE, default={"version": 1, "packets": {}}
    )

    if not isinstance(data, dict):
        return {"version": 1, "packets": {}}
    data.setdefault("version", 1)
    data.setdefault("packets", {})
    if not isinstance(data["packets"], dict):
        data["packets"] = {}
    return data


def save_data(data: dict[str, Any]) -> None:
    save_json_namespace("red_packets", data)


def _draw_lazy_allocation(remaining_amount: float, remaining_count: int) -> float:
    """Draw one share without pre-building a list proportional to amount or count."""
    remaining_units = int(round(round_shells(remaining_amount) * 10))
    if remaining_count <= 0 or remaining_units < remaining_count:
        raise ValueError("红包剩余金额不足以分配")
    if remaining_count == 1:
        return round_shells(remaining_units / 10)

    # Keep at least one 0.1-unit share for every later claimant. Capping the
    # random draw at twice the current average keeps the lucky-packet feel while
    # making creation O(1), even for very large packets.
    distributable_units = remaining_units - (remaining_count - 1)
    twice_average = max(1, (remaining_units * 2) // remaining_count)
    upper_units = min(distributable_units, twice_average)
    return round_shells((secrets.randbelow(upper_units) + 1) / 10)


@_locked
def create_packet(
    *,
    guild_id: int,
    channel_id: int,
    sender_id: int,
    sender_name: str,
    total_amount: float,
    count: int,
    message: str,
    admin_free: bool,
    timed: bool = False,
) -> dict[str, Any]:
    created_at = now_cn()
    packet_id = f"{int(created_at.timestamp())}-{secrets.token_hex(4)}"
    total_amount = round_shells(total_amount)
    count = int(count)
    if count <= 0 or total_amount < round_shells(count * 0.1):
        raise ValueError("红包金额不足以分配给指定数量")

    packet = {
        "id": packet_id,
        "guild_id": str(guild_id),
        "channel_id": str(channel_id),
        "message_id": "",
        "sender_id": str(sender_id),
        "sender_name": sender_name,
        "message": message,
        "total_amount": total_amount,
        "count": count,
        "remaining_amount": total_amount,
        "remaining_count": count,
        "allocation_mode": "lazy",
        "allocations": [],
        "claims": {},
        "admin_free": bool(admin_free),
        "timed": bool(timed),
        "created_at": created_at.isoformat(timespec="seconds"),
        "status": "active",
        "refunded": False,
    }
    if timed:
        packet["expires_at"] = (created_at + timedelta(hours=EXPIRE_HOURS)).isoformat(
            timespec="seconds"
        )

    data = load_data()
    data["packets"][packet_id] = packet
    save_data(data)
    return packet


@_locked
def set_packet_message(packet_id: str, message_id: int) -> None:
    data = load_data()
    packet = data["packets"].get(packet_id)
    if not packet:
        return
    packet["message_id"] = str(message_id)
    save_data(data)


def get_packet(packet_id: str) -> dict[str, Any] | None:
    data = load_data()
    packet = data["packets"].get(packet_id)
    return packet if isinstance(packet, dict) else None


@_locked
def claim_packet(packet_id: str, user_id: int) -> dict[str, Any]:
    data = load_data()
    packet = data["packets"].get(packet_id)
    if not isinstance(packet, dict):
        return {"success": False, "reason": "not_found"}

    if packet.get("status") != "active":
        return {"success": False, "reason": packet.get("status", "closed"), "packet": packet}

    expires_at = packet.get("expires_at")
    if expires_at and parse_time(expires_at) <= now_cn():
        packet["status"] = "expired"
        packet["remaining_amount"] = round_shells(packet.get("remaining_amount", 0))
        packet["refund_amount"] = packet["remaining_amount"]
        packet["expired_at"] = now_iso()
        save_data(data)
        return {"success": False, "reason": "expired", "packet": packet}

    claims = packet.setdefault("claims", {})
    if str(user_id) in claims:
        return {
            "success": False,
            "reason": "already_claimed",
            "amount": round_shells(claims[str(user_id)].get("amount", 0)),
            "packet": packet,
        }

    allocations = packet.setdefault("allocations", [])
    remaining_count = int(packet.get("remaining_count", len(allocations)) or 0)
    if remaining_count <= 0:
        packet["status"] = "empty"
        packet["remaining_amount"] = 0.0
        packet["remaining_count"] = 0
        save_data(data)
        return {"success": False, "reason": "empty", "packet": packet}

    if packet.get("allocation_mode") == "lazy":
        amount = _draw_lazy_allocation(packet.get("remaining_amount", 0), remaining_count)
        packet["remaining_count"] = remaining_count - 1
        packet["remaining_amount"] = round_shells(packet.get("remaining_amount", 0) - amount)
    else:
        # Compatibility with packets created before lazy allocation was added.
        if not allocations:
            packet["status"] = "empty"
            packet["remaining_amount"] = 0.0
            packet["remaining_count"] = 0
            save_data(data)
            return {"success": False, "reason": "empty", "packet": packet}
        amount = round_shells(allocations.pop())
        packet["remaining_count"] = len(allocations)
        packet["remaining_amount"] = round_shells(sum(round_shells(x) for x in allocations))

    claims[str(user_id)] = {"amount": amount, "claimed_at": now_iso()}
    if packet["remaining_count"] <= 0:
        packet["remaining_amount"] = 0.0
        packet["status"] = "empty"

    save_data(data)
    return {"success": True, "amount": amount, "packet": packet}


@_locked
def mark_packet_cancelled(packet_id: str) -> None:
    data = load_data()
    packet = data["packets"].get(packet_id)
    if not isinstance(packet, dict):
        return
    packet["status"] = "cancelled"
    save_data(data)


@_locked
def expire_due_packets() -> list[dict[str, Any]]:
    data = load_data()
    expired = []
    changed = False
    now = now_cn()

    for packet in data.get("packets", {}).values():
        if not isinstance(packet, dict) or packet.get("status") != "active":
            continue
        expires_at = packet.get("expires_at")
        if not expires_at or parse_time(expires_at) > now:
            continue

        packet["status"] = "expired"
        refund_amount = round_shells(packet.get("remaining_amount", 0))
        packet["refund_amount"] = refund_amount
        packet["expired_at"] = now.isoformat(timespec="seconds")
        expired.append(dict(packet))
        changed = True

    if changed:
        save_data(data)
    return expired


@_locked
def mark_refunded(packet_id: str) -> None:
    data = load_data()
    packet = data["packets"].get(packet_id)
    if not isinstance(packet, dict):
        return
    packet["refunded"] = True
    packet["refunded_at"] = now_iso()
    save_data(data)


def get_active_packets() -> list[dict[str, Any]]:
    data = load_data()
    return [
        packet
        for packet in data.get("packets", {}).values()
        if isinstance(packet, dict) and packet.get("status") == "active"
    ]
