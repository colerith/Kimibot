"""Small transactional game engine shared by the QQ and Discord adapters."""
import hashlib
import math
import random
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .flavor import PET_STORIES, FORTUNE_STORIES, bar

TZ = timezone(timedelta(hours=8))
ALIASES = {
    '签到': 'checkin', '奇米签到': 'checkin', '奇米我来惹': 'checkin',
    '饭粒': 'balance', '我的饭粒': 'balance', '奇米饭粒': 'balance',
    '喂奇米': 'feed', '摸摸奇米': 'pet', '看看奇米': 'status', '群宠': 'status',
    '今日运势': 'fortune', '今日奇米': 'fortune', '奇米运势': 'fortune',
    '娱乐帮助': 'help', '奇米帮助': 'help',
}
HELP = ('奇米游乐园开门惹♡\n'
        '奇米签到 / 奇米我来惹：每天领5～15粒米，连续7天的倍数额外+5\n'
        '我的饭粒：查看余额\n'
        '喂奇米：花3粒米，饱腹+12、心情+3、成长+5，每人60秒一次\n'
        '摸摸奇米：心情+5、成长+1，每人60秒一次\n'
        '看看奇米：看看大家一起养的群宠\n'
        '今日运势：每天固定一签，纯属娱乐捏！\n'
        '北京时间零点刷新；饭粒只在本群使用，不与蛋壳或其他平台兑换。')

DISCORD_HELP = ('🎪 奇米游乐园 · 玩法指南\n'
                '🍽️ /奇米 喂食：消耗3蛋壳，饱腹+12、心情+3、成长+5\n'
                '🤲 /奇米 摸摸：免费，心情+5、成长+1\n'
                '🐣 /奇米 群宠：状态进度与60种随机日常\n'
                '🔮 /奇米 运势：60种签语，北京时间每日固定一签\n'
                '🎲 群宠、运势各每日结算一次：等概率增加或扣除0.1～10蛋壳，余额不足扣至0。\n'
                '喂食和摸摸各有60秒冷却；饱腹已满不扣蛋壳。\n'
                '蛋壳与身份组商店共用；原有饭粒保留，不兑换、不再用于Discord喂食。')


def fortune(scope, uid, day):
    rng = random.Random(int(hashlib.sha256(f'{scope}:{uid}:{day}'.encode()).hexdigest(), 16))
    score = rng.randint(1, 100)
    color = rng.choice(['奶油黄', '草莓粉', '天空蓝', '薄荷绿', '糯米白'])
    food = rng.choice(['饭团', '小蛋糕', '热牛奶', '烤红薯', '小饼干'])
    advice = rng.choice(FORTUNE_STORIES)
    label = '星光满兜' if score >= 80 else '暖风同行' if score >= 60 else '平稳小憩' if score >= 30 else '慢慢充电'
    task = rng.choice(['给友友送一句夸奖', '整理一个小角落', '记下一件开心的小事', '认真喝一杯水', '给自己留十分钟休息'])
    return (f'🔮 {day} 今日奇米签\n'
            f'✨ 签面 · {label}\n幸运值：{score}/100 {bar(score)}\n'
            f'🎨 幸运色：{color} · 幸运食物：{food}\n'
            f'💌 奇米悄悄话：{advice}\n🎯 今日小任务：{task}\n'
            '每天一签，纯属娱乐，不用较真惹！')


class Entertainment:
    def __init__(self, path, platform):
        self.path = str(path)
        self.platform = platform
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        db = self.connect()
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS wallets (
                    scope TEXT, uid TEXT, rice INTEGER NOT NULL DEFAULT 0 CHECK(rice>=0),
                    checked TEXT NOT NULL DEFAULT '', streak INTEGER NOT NULL DEFAULT 0,
                    fed REAL NOT NULL DEFAULT 0, petted REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(scope,uid));
                CREATE TABLE IF NOT EXISTS pets (
                    scope TEXT PRIMARY KEY, hunger REAL NOT NULL DEFAULT 60,
                    mood REAL NOT NULL DEFAULT 60, xp INTEGER NOT NULL DEFAULT 0,
                    updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (
                    scope TEXT, event TEXT, reply TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(scope,event));
            ''')
        finally:
            db.close()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def handle(self, group, user, text, event_id, now=None):
        action = ALIASES.get(text.strip())
        if action is None:
            return None
        if self.platform == 'discord' and action in {'checkin', 'balance'}:
            return None
        now = datetime.now(TZ).timestamp() if now is None else now
        day = datetime.fromtimestamp(now, TZ).date()
        scope, uid = f'{self.platform}:{group}', str(user)
        db = self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                if event_id is not None:
                    previous = db.execute('SELECT reply FROM receipts WHERE scope=? AND event=?', (scope, str(event_id))).fetchone()
                    if previous:
                        return previous['reply']
                db.execute('INSERT OR IGNORE INTO wallets(scope,uid) VALUES(?,?)', (scope, uid))
                db.execute('INSERT OR IGNORE INTO pets(scope,updated) VALUES(?,?)', (scope, now))
                wallet = dict(db.execute('SELECT * FROM wallets WHERE scope=? AND uid=?', (scope, uid)).fetchone())
                pet = dict(db.execute('SELECT * FROM pets WHERE scope=?', (scope,)).fetchone())
                hours = max(0, now-pet['updated']) / 3600
                pet['hunger'] = max(0, pet['hunger'] - hours*2)
                pet['mood'] = max(0, pet['mood'] - hours)
                pet['updated'] = max(now, pet['updated'])
                reply = self.apply(action, wallet, pet, scope, uid, day, now, event_id)
                if self.platform == 'discord' and action in {'status', 'fortune'}:
                    reply += self.daily_event(group, user, action, day.isoformat())
                db.execute('UPDATE wallets SET rice=?,checked=?,streak=?,fed=?,petted=? WHERE scope=? AND uid=?',
                           (wallet['rice'], wallet['checked'], wallet['streak'], wallet['fed'], wallet['petted'], scope, uid))
                db.execute('UPDATE pets SET hunger=?,mood=?,xp=?,updated=? WHERE scope=?',
                           (pet['hunger'], pet['mood'], pet['xp'], pet['updated'], scope))
                if event_id is not None:
                    db.execute('INSERT INTO receipts VALUES(?,?,?,?)', (scope, str(event_id), reply, now))
                db.execute('DELETE FROM receipts WHERE created<?', (now-30*86400,))
                return reply
        finally:
            db.close()

    @staticmethod
    def daily_event(group, user, action, day):
        from cogs.points.storage import settle_kimi_daily_event, format_shells
        result = settle_kimi_daily_event(int(user), int(group), action, day)
        stories = {
            'status': ('奇米从小窝翻出一袋蛋壳，开心地塞进你的口袋！',
                       '奇米打翻了小窝里的花盆，你用蛋壳补上了修理费。'),
            'fortune': ('签筒里掉出一颗幸运星，附赠的小蛋壳归你啦！',
                        '一阵调皮的风吹跑了幸运丝带，你花蛋壳重新系好了它。'),
        }
        story = stories[action][0 if result['requested'] > 0 else 1]
        shortfall = '（余额不足，仅扣至0）' if result['actual'] != result['requested'] else ''
        return (f'\n\n🎲 {day} 蛋壳奇遇\n{story}\n'
                f"抽取：{result['requested']:+.1f} 蛋壳 · 实际：{result['actual']:+.1f} 蛋壳{shortfall}\n"
                f"结算后余额：{format_shells(result['balance'])} 蛋壳\n"
                '本玩法今日已结算；重复查看不再加扣，北京时间零点刷新。')

    def apply(self, action, wallet, pet, scope, uid, day, now, event_id=None):
        if action == 'help':
            return DISCORD_HELP if self.platform == 'discord' else HELP
        if action == 'fortune':
            return fortune(scope, uid, day.isoformat())
        if action == 'checkin':
            if wallet['checked'] >= day.isoformat():
                return f"友友今天已经来过惹！口袋还有{wallet['rice']}粒米，明天零点再来捏♡"
            wallet['streak'] = wallet['streak']+1 if wallet['checked'] == (day-timedelta(days=1)).isoformat() else 1
            reward = 5 + secrets.randbelow(11) + (5 if wallet['streak'] % 7 == 0 else 0)
            wallet['rice'] += reward
            wallet['checked'] = day.isoformat()
            return f"友友终于来惹！今天捡到{reward}粒米♡\n连续签到{wallet['streak']}天，口袋一共{wallet['rice']}粒米捏！"
        if action == 'balance':
            return f"扒开友友的小口袋……有{wallet['rice']}粒米惹♡\n连续签到{wallet['streak']}天，喂奇米一次要3粒米捏！"
        if action in ('feed', 'pet'):
            last = wallet['fed' if action == 'feed' else 'petted']
            if last and now-last < 60:
                return f'奇米还在回味捏，{math.ceil(60-(now-last))}秒后再来叭♡'
            if action == 'feed':
                if self.platform != 'discord' and wallet['rice'] < 3:
                    return '米不够惹！喂奇米要3粒米，先来「奇米签到」捏♡'
                if pet['hunger'] >= 99:
                    return '肚肚已经圆滚滚惹！这次不扣费，待会再喂捏♡'
                if self.platform == 'discord':
                    from cogs.points.storage import spend_user_points, format_shells
                    result = spend_user_points(int(uid), 3, int(scope.split(':', 1)[1]),
                                               source='kimi_feed', reason='奇米群宠喂食',
                                               operation_id=f'kimi_feed:{scope}:{uid}:{event_id}' if event_id is not None else None)
                    if not result['success']:
                        return f"🥚 蛋壳不够惹！喂食需要3蛋壳，当前只有{format_shells(result['balance'])}蛋壳。"
                    payment = f"消耗3蛋壳，余额{format_shells(result['balance'])}蛋壳"
                else:
                    wallet['rice'] -= 3
                    payment = f"吃掉3粒米，友友还剩{wallet['rice']}粒米"
                wallet['fed'] = now
                pet['hunger'] = min(100, pet['hunger']+12)
                pet['mood'] = min(100, pet['mood']+3)
                pet['xp'] += 5
                return f"🍽️ 啊呜！肚肚暖乎乎惹♡\n{payment}\n饱腹 {int(pet['hunger'])}/100 · 心情 {int(pet['mood'])}/100 · 成长+5"
            wallet['petted'] = now
            pet['mood'] = min(100, pet['mood']+5)
            pet['xp'] += 1
            return f"呼噜呼噜……被友友摸成一颗糯米团惹♡\n奇米心情{int(pet['mood'])}/100，成长+1！"
        activity = '捂着空空的肚肚等饭吃' if pet['hunger'] < 25 else '缩在纸箱里等友友抱抱' if pet['mood'] < 30 else '抱着小饭团晒太阳'
        hint = '肚肚有点空，来一份点心叭！' if pet['hunger'] < 25 else '想要一个抱抱，摸摸就会开心一点。' if pet['mood'] < 30 else '状态不错！谢谢大家把小窝照顾得暖暖的。'
        return (f"🐣 奇米群宠 · 大家的小窝\n正在{activity}捏♡\n"
                f"🌱 等级 Lv.{1+pet['xp']//100} · 成长 {pet['xp']}\n"
                f"升级进度 {bar(pet['xp'] % 100)} · 还差{100-pet['xp'] % 100}成长\n"
                f"🍽️ 饱腹 {int(pet['hunger'])}/100 {bar(pet['hunger'])}\n"
                f"💗 心情 {int(pet['mood'])}/100 {bar(pet['mood'])}\n"
                f"📖 小窝日记：{secrets.choice(PET_STORIES)}\n💬 照顾提示：{hint}\n"
                '大家共养一只奇米；喂食和摸摸各有60秒冷却。')
