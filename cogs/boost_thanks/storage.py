import json
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

THANKS_MESSAGES_FILE = Path(__file__).with_name("thanks_messages.json")
BOOST_THANKS_DATA_FILE = "data/boost_thanks.json"
TZ_CN = timezone(timedelta(hours=8))

DIGIT_EMOJIS = {
    "1": "<:kimi1:1093887092507021332>",
    "2": "<:kimi2:1093887089730396230>",
    "3": "<:kimi3:1093887094931324929>",
    "4": "<:kimi4:1093887099171774494>",
    "5": "<:kimi5:1093887101302484993>",
    "6": "<:kimi6:1093887103856820345>",
    "7": "<:kimi7:1093887107736535081>",
    "8": "<:kimi8:1093887112073465946>",
    "9": "<:kimi9:1093887114220929124>",
    "0": "<:kimi0:1093887083568955422>",
}

DEFAULT_MESSAGES = [
    "奇米蛋把这份助力认真记进小本本里，今天的服务器也亮了一点点。",
    "助力光落在小蛋报到台上，奇米蛋开心得转了一圈。",
    "收到助力啦，奇米蛋把亮晶晶的感谢塞进了蛋壳里。",
]


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_thanks_messages() -> list[str]:
    raw = _load_json(THANKS_MESSAGES_FILE, {"version": 1, "messages": DEFAULT_MESSAGES})
    messages = raw.get("messages", []) if isinstance(raw, dict) else []
    cleaned = [str(msg).strip() for msg in messages if str(msg).strip()]
    return cleaned or DEFAULT_MESSAGES


def pick_thanks_message() -> str:
    return random.choice(load_thanks_messages())


def format_digit_emojis(number: int) -> str:
    value = max(0, int(number))
    return "".join(DIGIT_EMOJIS[digit] for digit in str(value))


def load_boost_thanks_data() -> dict:
    raw = _load_json(BOOST_THANKS_DATA_FILE, {"version": 1, "processed": {}})
    if not isinstance(raw, dict):
        return {"version": 1, "processed": {}}
    processed = raw.get("processed", {})
    if not isinstance(processed, dict):
        processed = {}
    return {"version": 1, "processed": processed}


def mark_processed(message_id: int, payload: dict) -> bool:
    data = load_boost_thanks_data()
    key = str(message_id)
    if key in data["processed"]:
        return False
    data["processed"][key] = {
        **payload,
        "processed_at": _now_iso(),
    }
    _save_json(BOOST_THANKS_DATA_FILE, data)
    return True
