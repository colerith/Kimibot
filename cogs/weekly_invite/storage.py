from datetime import datetime, timedelta, timezone
from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace

CHANNEL_ID = 1563535291850170389
TZ = timezone(timedelta(hours=8))
DEFAULT_COPY = ('本周邀请链接有效至周六 00:00（北京时间），不限使用次数。'
                '有效期内显示无效，可先检查网络；仍无法加入请联系管理员。\n\n'
                '✅ dc社区传播　✅ 境内私发　❌ 境内大范围传播\n'
                '寒暑假会暂停开放。')


def now():
    return datetime.now(TZ)


def load():
    return load_json_namespace('weekly_invite', legacy_file=None, default={
        'enabled': True, 'title': '🌱 社区每周邀请', 'copy': DEFAULT_COPY,
        'pauses': [], 'message_id': None, 'invite': None, 'attempt': None})


def save(state):
    save_json_namespace('weekly_invite', state)


def window(at=None):
    at = (at or now()).astimezone(TZ)
    monday = (at - timedelta(days=at.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday, monday + timedelta(days=5)


def parse_pauses(text):
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.strip().split('~')
        if len(parts) != 2:
            raise ValueError('每行格式为 YYYY-MM-DD ~ YYYY-MM-DD。')
        dates = [datetime.strptime(p.strip(), '%Y-%m-%d').date() for p in parts]
        if dates[1] < dates[0]:
            raise ValueError('结束日期不能早于开始日期。')
        result.append([d.isoformat() for d in dates])
    if len(result) > 20:
        raise ValueError('最多设置 20 段暂停区间。')
    return sorted(result)


def creation_allowed(state, at=None):
    at = (at or now()).astimezone(TZ)
    _, end = window(at)
    return (state['enabled'] and at < end and
            not any(start <= at.date().isoformat() <= finish for start, finish in state['pauses']))


def active_invite(state, at=None):
    invite = state.get('invite')
    return invite if invite and datetime.fromisoformat(invite['expires']) > (at or now()) else None
