"""Small transactional game engine shared by the QQ and Discord adapters."""
import hashlib
import math
import random
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def fortune(scope, uid, day):
    rng = random.Random(int(hashlib.sha256(f'{scope}:{uid}:{day}'.encode()).hexdigest(), 16))
    score = rng.randint(1, 100)
    color = rng.choice(['奶油黄', '草莓粉', '天空蓝', '薄荷绿', '糯米白'])
    food = rng.choice(['饭团', '小蛋糕', '热牛奶', '烤红薯', '小饼干'])
    advice = rng.choice(['给自己留一点发呆时间', '把想说的谢谢告诉友友', '完成一件小事就夸夸自己', '出去走走，看看天空', '今晚早点钻进被窝'])
    return f'🔮 {day} 今日奇米签\n幸运值：{score}/100\n幸运色：{color} · 幸运食物：{food}\n奇米悄悄话：{advice}捏♡\n每天一签，纯属娱乐，不用较真惹！'


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
                reply = self.apply(action, wallet, pet, scope, uid, day, now)
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
    def apply(action, wallet, pet, scope, uid, day, now):
        if action == 'help':
            return HELP
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
                if wallet['rice'] < 3:
                    return '米不够惹！喂奇米要3粒米，先来「奇米签到」捏♡'
                if pet['hunger'] >= 99:
                    return '肚肚已经圆滚滚惹！这次不扣饭粒，待会再喂捏♡'
                wallet['rice'] -= 3
                wallet['fed'] = now
                pet['hunger'] = min(100, pet['hunger']+12)
                pet['mood'] = min(100, pet['mood']+3)
                pet['xp'] += 5
                return f"啊呜！吃掉3粒米，肚肚暖乎乎惹♡\n友友还剩{wallet['rice']}粒米；奇米饱腹{int(pet['hunger'])}/100。"
            wallet['petted'] = now
            pet['mood'] = min(100, pet['mood']+5)
            pet['xp'] += 1
            return f"呼噜呼噜……被友友摸成一颗糯米团惹♡\n奇米心情{int(pet['mood'])}/100，成长+1！"
        activity = '捂着空空的肚肚等饭吃' if pet['hunger'] < 25 else '缩在纸箱里等友友抱抱' if pet['mood'] < 30 else '抱着小饭团晒太阳'
        return f"🐣 本群奇米正在{activity}捏♡\n等级 Lv.{1+pet['xp']//100} · 成长 {pet['xp']}\n饱腹 {int(pet['hunger'])}/100 · 心情 {int(pet['mood'])}/100\n这是大家一起养的奇米，快来摸摸它叭！"
