import json
import math
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG_FILE = 'data/festival_rewards.json'
TZ_CN = timezone(timedelta(hours=8))
_LOCK = threading.RLock()


def parse_time(text):
    try:
        value = datetime.fromisoformat(str(text).strip())
    except ValueError:
        raise ValueError('时间请填写 YYYY-MM-DD HH:MM（北京时间）') from None
    return value.replace(tzinfo=TZ_CN) if value.tzinfo is None else value.astimezone(TZ_CN)


def _load():
    try:
        return json.loads(Path(CONFIG_FILE).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def get_config(guild_id):
    with _LOCK:
        return _load().get(str(guild_id), {})


def save_config(guild_id, name, start_at, end_at, multiplier, enabled=True):
    start, end = parse_time(start_at), parse_time(end_at)
    multiplier = float(multiplier)
    if end <= start:
        raise ValueError('结束时间必须晚于开始时间')
    if not math.isfinite(multiplier) or not 1 < multiplier <= 100:
        raise ValueError('倍率必须大于 1 且不超过 100，例如 1.5 表示额外增加 50%')
    value = dict(name=str(name).strip()[:80] or '节日福利', start_at=start.isoformat(),
                 end_at=end.isoformat(), multiplier=multiplier, enabled=bool(enabled))
    with _LOCK:
        data = _load()
        data[str(guild_id)] = value
        path = Path(CONFIG_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    return value


def apply_bonus(guild_id, amount, now=None):
    """Apply once at payout time, after monthly benefits; never amplify a loss."""
    now = now or datetime.now(TZ_CN)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ_CN)
    value = get_config(guild_id)
    multiplier = 1.0
    if value.get('enabled') and parse_time(value['start_at']) <= now < parse_time(value['end_at']):
        multiplier = value['multiplier']
    total = round(amount * multiplier, 1) if amount > 0 else amount
    return total, round(total - amount, 1), multiplier
