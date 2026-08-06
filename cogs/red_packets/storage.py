import json
import os
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

DATA_FILE = "data/red_packets.json"
TZ_CN = timezone(timedelta(hours=8))
SHELL_PRECISION = 1
EXPIRE_HOURS = 24


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
    return round(max(0.0, amount), SHELL_PRECISION)


def format_shells(value: float | int | str) -> str:
    amount = round_shells(value)
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:.1f}"


def load_data() -> dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"version": 1, "packets": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"version": 1, "packets": {}}

    if not isinstance(data, dict):
        return {"version": 1, "packets": {}}
    data.setdefault("version", 1)
    data.setdefault("packets", {})
    if not isinstance(data["packets"], dict):
        data["packets"] = {}
    return data


def save_data(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def generate_allocations(total_amount: float, count: int) -> list[float]:
    total_units = int(round(round_shells(total_amount) * 10))
    if count <= 0 or total_units < count:
        raise ValueError("红包金额不足以分配给指定数量")

    units = [1 for _ in range(count)]
    for _ in range(total_units - count):
        units[random.randrange(count)] += 1

    random.shuffle(units)
    return [round(u / 10, SHELL_PRECISION) for u in units]


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
) -> dict[str, Any]:
    created_at = now_cn()
    packet_id = f"{int(created_at.timestamp())}-{secrets.token_hex(4)}"
    allocations = generate_allocations(total_amount, count)

    packet = {
        "id": packet_id,
        "guild_id": str(guild_id),
        "channel_id": str(channel_id),
        "message_id": "",
        "sender_id": str(sender_id),
        "sender_name": sender_name,
        "message": message,
        "total_amount": round_shells(total_amount),
        "count": int(count),
        "remaining_amount": round_shells(sum(allocations)),
        "remaining_count": len(allocations),
        "allocations": allocations,
        "claims": {},
        "admin_free": bool(admin_free),
        "created_at": created_at.isoformat(timespec="seconds"),
        "expires_at": (created_at + timedelta(hours=EXPIRE_HOURS)).isoformat(timespec="seconds"),
        "status": "active",
        "refunded": False,
    }

    data = load_data()
    data["packets"][packet_id] = packet
    save_data(data)
    return packet


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


def claim_packet(packet_id: str, user_id: int) -> dict[str, Any]:
    data = load_data()
    packet = data["packets"].get(packet_id)
    if not isinstance(packet, dict):
        return {"success": False, "reason": "not_found"}

    if packet.get("sender_id") == str(user_id):
        return {"success": False, "reason": "sender_blocked", "packet": packet}

    if packet.get("status") != "active":
        return {"success": False, "reason": packet.get("status", "closed"), "packet": packet}

    if parse_time(packet.get("expires_at", "")) <= now_cn():
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
    if not allocations:
        packet["status"] = "empty"
        packet["remaining_amount"] = 0.0
        packet["remaining_count"] = 0
        save_data(data)
        return {"success": False, "reason": "empty", "packet": packet}

    amount = round_shells(allocations.pop())
    claims[str(user_id)] = {"amount": amount, "claimed_at": now_iso()}
    packet["remaining_count"] = len(allocations)
    packet["remaining_amount"] = round_shells(sum(round_shells(x) for x in allocations))
    if not allocations:
        packet["status"] = "empty"

    save_data(data)
    return {"success": True, "amount": amount, "packet": packet}


def mark_packet_cancelled(packet_id: str) -> None:
    data = load_data()
    packet = data["packets"].get(packet_id)
    if not isinstance(packet, dict):
        return
    packet["status"] = "cancelled"
    save_data(data)


def expire_due_packets() -> list[dict[str, Any]]:
    data = load_data()
    expired = []
    changed = False
    now = now_cn()

    for packet in data.get("packets", {}).values():
        if not isinstance(packet, dict) or packet.get("status") != "active":
            continue
        if parse_time(packet.get("expires_at", "")) > now:
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
