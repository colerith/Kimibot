"""Promotion quota, review outbox and permanent benefits in the points transaction DB."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from cogs.points import storage as points

CHANNEL_ID = 1559382179677470800
LOG_CHANNEL_ID = 1419652525249794128
ROLE_ID = 1417722389718110249
DAILY_LIMIT = 100


def is_staff(member):
    return not member.bot and (member.id == member.guild.owner_id or member.guild_permissions.administrator)


def auto_eligible(member):
    return not member.bot and (is_staff(member) or any(r.id == ROLE_ID for r in member.roles))


def _quota(con, guild_id, day):
    rows = con.execute('SELECT data FROM promotion_applications WHERE guild_id=? AND batch=?',
                       (str(guild_id), day))
    return sum(not points._json_load(row['data'], {}).get('is_test', False) for row in rows)


def today(now=None):
    return (now or datetime.now(points.TZ_CN)).astimezone(points.TZ_CN).date().isoformat()


def initialize():
    points._ensure_points_db()
    with points._points_connection() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS promotion_members (
            guild_id TEXT NOT NULL, user_id TEXT NOT NULL, activated TEXT NOT NULL,
            last_daily TEXT NOT NULL, PRIMARY KEY(guild_id,user_id));
        CREATE TABLE IF NOT EXISTS promotion_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL,
            guild_id TEXT NOT NULL, user_id TEXT NOT NULL, batch TEXT NOT NULL,
            status TEXT NOT NULL, data TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS promotion_queue ON promotion_applications(guild_id,status,id);
        CREATE TABLE IF NOT EXISTS promotion_panels (name TEXT PRIMARY KEY, message_id TEXT NOT NULL);
        ''')


def is_member(con, user_id, guild_id):
    # Read-only fallback keeps old databases and other cogs usable before extension startup.
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='promotion_members'").fetchone():
        return False
    return bool(con.execute("SELECT 1 FROM promotion_members WHERE guild_id=? AND user_id=?",
                            (str(guild_id), str(user_id))).fetchone())


def discounted_cost(amount, eligible):
    return float((Decimal(str(amount)) * (Decimal('0.8') if eligible else Decimal(1)))
                 .quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def quote(user_id, guild_id, amount):
    points._ensure_points_db()
    with points._points_connection() as con:
        return discounted_cost(amount, is_member(con, user_id, guild_id))


def _credit(con, user_id, guild_id, amount, source, reason):
    record, key = points._db_get_user(con, user_id, guild_id)
    record['shells'] = record['points'] = points._round_shells(record.get('shells', 0) + amount)
    points._db_append_transaction(con, record, user_id=user_id, guild_id=guild_id,
                                  amount=amount, source=source, reason=reason)
    points._db_put_user(con, key, record)


def _activate(con, user_id, guild_id, day):
    inserted = con.execute("INSERT OR IGNORE INTO promotion_members VALUES (?,?,?,?)",
                           (str(guild_id), str(user_id), day, day)).rowcount
    if inserted:
        _credit(con, user_id, guild_id, 100, 'promotion_welcome', '破壳而出永久权益・首次赠礼')
        _credit(con, user_id, guild_id, 30, 'promotion_daily', f'开通当日 {day}')
    return bool(inserted)


@points._locked_points_data
def activate(user_id, guild_id, now=None):
    initialize()
    with points._points_connection() as con:
        con.execute('BEGIN IMMEDIATE')
        return _activate(con, user_id, guild_id, today(now))


@points._locked_points_data
def settle_daily(now=None):
    initialize()
    day = today(now)
    count = 0
    with points._points_connection() as con:
        con.execute('BEGIN IMMEDIATE')
        for row in con.execute('SELECT * FROM promotion_members WHERE last_daily < ?', (day,)).fetchall():
            days = (datetime.fromisoformat(day) - datetime.fromisoformat(row['last_daily'])).days
            _credit(con, int(row['user_id']), int(row['guild_id']), days * 30,
                    'promotion_daily', f"{row['last_daily']} 次日至 {day};days={days}")
            con.execute('UPDATE promotion_members SET last_daily=? WHERE guild_id=? AND user_id=?',
                        (day, row['guild_id'], row['user_id']))
            count += 1
    return count


def _decode(row):
    if not row:
        return None
    result = points._json_load(row['data'], {})
    result.update({k: row[k] for k in ('id', 'guild_id', 'user_id', 'batch', 'status')})
    return result


def get(application_id):
    initialize()
    with points._points_connection() as con:
        return _decode(con.execute('SELECT * FROM promotion_applications WHERE id=?', (application_id,)).fetchone())


def applications(guild_id):
    initialize()
    with points._points_connection() as con:
        return [_decode(row) for row in con.execute('SELECT * FROM promotion_applications WHERE guild_id=? ORDER BY id', (str(guild_id),))]


def quota(guild_id, now=None):
    initialize()
    with points._points_connection() as con:
        return _quota(con, guild_id, today(now))


@points._locked_points_data
def create(user_id, guild_id, request_id, content, files, author_name, now=None, *, is_test=False):
    if len(''.join(content.split())) < 30:
        raise ValueError('请填写至少 30 字的使用感想（空白不计入）。')
    if not 2 <= len(files) <= 6:
        raise ValueError('请提供 2–6 张截图，包含首楼及超过 100 楼的末楼。')
    initialize()
    with points._points_connection() as con:
        con.execute('BEGIN IMMEDIATE')
        previous = con.execute('SELECT * FROM promotion_applications WHERE request_id=?', (str(request_id),)).fetchone()
        if previous:
            return _decode(previous)
        if not is_test and is_member(con, user_id, guild_id):
            raise ValueError('你的永久权益已经开通，无需再次申请。')
        blocked = ("publishing", "pending", "granting") if is_test else ("publishing", "pending", "granting", "approved")
        if con.execute(f"SELECT 1 FROM promotion_applications WHERE guild_id=? AND user_id=? AND status IN ({','.join('?' for _ in blocked)})",
                       (str(guild_id), str(user_id), *blocked)).fetchone():
            raise ValueError('你已有申请，请等待原申请处理，无需重复提交。')
        day = today(now)
        count = _quota(con, guild_id, day)
        if not is_test and count >= DAILY_LIMIT:
            raise ValueError('今天的 100 个申请名额已满，北京时间明天 0 点刷新。')
        data = dict(content=content, files=files, author_name=author_name, is_test=bool(is_test),
                    created=(now or datetime.now(points.TZ_CN)).isoformat(), message_id=None,
                    card_dirty=True, dm_state='pending', log_state='pending')
        cursor = con.execute('INSERT INTO promotion_applications(request_id,guild_id,user_id,batch,status,data) VALUES (?,?,?,?,?,?)',
                             (str(request_id), str(guild_id), str(user_id), day, 'publishing', points._json_dump(data)))
        return dict(data, id=cursor.lastrowid, guild_id=str(guild_id), user_id=str(user_id), batch=day, status='publishing')


def _save(con, row):
    con.execute('UPDATE promotion_applications SET status=?,data=? WHERE id=?',
                (row['status'], points._json_dump(row), row['id']))


@points._locked_points_data
def update(application_id, **changes):
    initialize()
    with points._points_connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = _decode(con.execute('SELECT * FROM promotion_applications WHERE id=?', (application_id,)).fetchone())
        if row is None:
            raise ValueError('申请不存在。')
        row.update(changes)
        _save(con, row)
        return row


@points._locked_points_data
def decide(application_id, reviewer_id, approved, reason=''):
    if not approved and not reason.strip():
        raise ValueError('请填写驳回理由。')
    initialize()
    with points._points_connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = _decode(con.execute('SELECT * FROM promotion_applications WHERE id=?', (application_id,)).fetchone())
        if not row or row['status'] != 'pending':
            raise ValueError('该申请已处理或正在处理，请勿重复审批。')
        row.update(status='granting' if approved else 'rejected', reviewer_id=reviewer_id,
                   reason=reason.strip(), reviewed=datetime.now(points.TZ_CN).isoformat(), card_dirty=True)
        _save(con, row)
        return row


@points._locked_points_data
def complete(application_id):
    initialize()
    with points._points_connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = _decode(con.execute('SELECT * FROM promotion_applications WHERE id=?', (application_id,)).fetchone())
        if not row or row['status'] != 'granting':
            return row
        if not row.get('is_test'):
            _activate(con, int(row['user_id']), int(row['guild_id']), today())
        row.update(status='approved', card_dirty=True, completed=datetime.now(points.TZ_CN).isoformat())
        _save(con, row)
        return row


def panel(name, message_id=None):
    initialize()
    with points._points_connection() as con:
        if message_id is not None:
            con.execute('INSERT OR REPLACE INTO promotion_panels VALUES (?,?)', (name, str(message_id)))
        row = con.execute('SELECT message_id FROM promotion_panels WHERE name=?', (name,)).fetchone()
        return int(row[0]) if row else None
