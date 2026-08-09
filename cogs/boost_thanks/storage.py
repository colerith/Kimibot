import json
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

THANKS_MESSAGES_FILE = Path(__file__).with_name("thanks_messages.json")
BOOST_THANKS_DATA_FILE = "data/boost_thanks.json"
TZ_CN = timezone(timedelta(hours=8))

DIGIT_EMOJI_IDS = {
    "1": 1093887092507021332,
    "2": 1093887089730396230,
    "3": 1093887094931324929,
    "4": 1093887099171774494,
    "5": 1093887101302484993,
    "6": 1093887103856820345,
    "7": 1093887107736535081,
    "8": 1093887112073465946,
    "9": 1093887114220929124,
    "0": 1093887083568955422,
}

DIGIT_EMOJIS = {
    digit: f"<:kimi_digit_{digit}:{emoji_id}>"
    for digit, emoji_id in DIGIT_EMOJI_IDS.items()
}

DEFAULT_MESSAGES = [
    "奇米蛋把这份助力认真记进小本本里，今天的服务器也亮了一点点。",
    "助力光落在小蛋报到台上，奇米蛋开心得转了一圈。",
    "收到助力啦，奇米蛋把亮晶晶的感谢塞进了蛋壳里。",
    "服务器被轻轻托高了一层，奇米蛋向你递来一枚闪亮感谢。",
    "这份助力像小星星一样落下，奇米蛋已经好好收藏。",
    "奇米蛋举起报到牌：感谢你的助力，今天也更热闹啦。",
    "小蛋仓库收到一阵暖光，原来是你的助力到了。",
    "奇米蛋把助力铃摇响，叮的一声，全服都变得更亮。",
    "这份心意已经送达，奇米蛋正在认真盖感谢章。",
    "助力记录更新完成，奇米蛋说今天必须给你记一朵小花。",
    "服务器能量上涨，奇米蛋在报到台旁边开心拍手。",
    "你的助力让小蛋灯亮了起来，奇米蛋郑重说一声谢谢。",
    "奇米蛋把感谢写进今日报到页，边角还画了一个小星星。",
    "助力抵达，服务器等级的进度条像被轻轻推了一把。",
    "奇米蛋收到助力信号，立刻把感谢装进小蛋壳里。",
    "这一下很有分量，奇米蛋已经把它放进服务器荣誉柜。",
    "小蛋报到台响起提示音：收到一份非常可靠的助力。",
    "奇米蛋说这份助力很香，适合放在今天的感谢栏第一排。",
    "服务器被你添了一把柴，奇米蛋的小炉子暖起来了。",
    "奇米蛋把你的名字旁边画了亮亮的一笔，感谢助力。",
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


def resolve_digit_emoji(digit: str, bot=None) -> str:
    emoji_id = DIGIT_EMOJI_IDS[str(digit)]
    if bot is not None:
        emoji = bot.get_emoji(int(emoji_id))
        if emoji is not None:
            return str(emoji)
    return DIGIT_EMOJIS[str(digit)]


def format_digit_emojis(number: int, bot=None) -> str:
    value = max(0, int(number))
    return "".join(resolve_digit_emoji(digit, bot=bot) for digit in str(value))


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


def update_processed_message(message_id: int, payload: dict) -> None:
    data = load_boost_thanks_data()
    key = str(message_id)
    if key not in data["processed"]:
        return
    data["processed"][key].update(payload)
    _save_json(BOOST_THANKS_DATA_FILE, data)
