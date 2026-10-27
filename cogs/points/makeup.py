"""Permanent makeup cards with transactional wallet, inventory and monthly usage."""
from datetime import date, timedelta
import re
from . import storage as p
import config

CARDS = {
    'week': {'name': '一天补签卡', 'price': 5, 'days': 1},
    'month': {'name': '三天补签卡', 'price': 10, 'days': 3},
    'previous': {'name': '七天补签卡', 'price': 15, 'days': 7},
}


def _state(con, key):
    state = p._db_get_section(con, 'makeup_cards', key, None)
    if state is not None:
        return state
    state = {'inventory': {}, 'dates': [], 'usage': {}}
    gid, uid = key.split(':', 1)
    # Older snapshot saves erased sections but retained the accounting ledger.
    for row in con.execute("SELECT * FROM point_transactions WHERE guild_id=? AND user_id=? AND source IN ('makeup_card_purchase','makeup_sign_reward') ORDER BY id", (gid, uid)):
        if row['source'] == 'makeup_card_purchase':
            kind = next((k for k,v in CARDS.items() if v['name'] == row['reason']), None)
            if kind:
                state['inventory'][kind] = state['inventory'].get(kind, 0) + 1
        else:
            days = re.findall(r'\d{4}-\d{2}-\d{2}', row['reason'])
            if ' 至 ' in row['reason'] and len(days) == 2:
                start, end = map(date.fromisoformat, days)
                days = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
            kind = next((k for k,v in CARDS.items() if v['days'] == len(days)), None)
            if kind:
                state['inventory'][kind] = state['inventory'].get(kind, 0) - 1
                state['dates'].extend(days)
                month = row['time'][:7]
                state['usage'][month] = state['usage'].get(month, 0) + 1
        if row['idempotency_key']:
            p._db_put_section(con, 'makeup_receipts', row['idempotency_key'], {'message': '该操作此前已完成，已恢复记录，不会重复扣款或发奖。'})
    p._db_put_section(con, 'makeup_cards', key, state)
    return state


@p._locked_points_data
def snapshot(uid, gid):
    p._ensure_points_db()
    with p._points_connection() as con:
        record, key = p._db_get_user(con, uid, gid)
        state = _state(con, key)
    return dict(state, balance=record.get('shells', 0), used=state['usage'].get(p._today()[:7], 0))


@p._locked_points_data
def purchase(uid, gid, kind, operation_id):
    if kind not in CARDS: raise ValueError('未知补签卡类型。')
    p._ensure_points_db()
    with p._points_connection() as con:
        con.execute('BEGIN IMMEDIATE')
        _state(con, p._make_user_key(uid, gid))
        receipt_key=f'{gid}:{uid}:buy:{operation_id}'
        previous=p._db_get_section(con,'makeup_receipts',receipt_key,None)
        if previous: return previous
        record,key=p._db_get_user(con,uid,gid)
        price=CARDS[kind]['price']
        if record.get('shells',0)<price: raise ValueError('蛋壳不足，未购买。')
        state=_state(con,key)
        state['inventory'][kind]=state['inventory'].get(kind,0)+1
        record['shells']=record['points']=p._round_shells(record.get('shells',0)-price)
        p._db_append_transaction(con,record,user_id=uid,guild_id=gid,amount=-price,source='makeup_card_purchase',reason=CARDS[kind]['name'],idempotency_key=receipt_key)
        p._db_put_user(con,key,record)
        p._db_put_section(con,'makeup_cards',key,state)
        result={'message':f"已购买 1 张{CARDS[kind]['name']}，花费 {price} 蛋壳。"}
        p._db_put_section(con,'makeup_receipts',receipt_key,result)
        return result


@p._locked_points_data
def use(uid,gid,kind,target,operation_id,joined_date=None):
    today=date.fromisoformat(p._today())
    if kind not in CARDS: raise ValueError('未知补签卡类型。')
    if isinstance(target, str):  # Compatibility for already-open old modals.
        try: day=date.fromisoformat(target)
        except ValueError: raise ValueError('日期格式应为 YYYY-MM-DD。')
        targets=[(day+timedelta(days=n)).isoformat() for n in range(CARDS[kind]['days'])]
    else:
        targets=sorted(target)
    if len(targets)!=CARDS[kind]['days'] or len(set(targets))!=len(targets):
        raise ValueError(f"请恰好选择 {CARDS[kind]['days']} 个不同的漏签日期。")
    try:
        parsed=[date.fromisoformat(value) for value in targets]
    except (ValueError, TypeError): raise ValueError('日期格式应为 YYYY-MM-DD。')
    if any(value.isoformat()!=raw for value,raw in zip(parsed,targets)):
        raise ValueError('日期格式应为 YYYY-MM-DD。')
    if any(value>=today for value in parsed): raise ValueError('补签日期必须早于今天，可跨月。')
    if joined_date and min(parsed)<date.fromisoformat(joined_date): raise ValueError('不能补入服前的签到。')
    p._ensure_points_db()
    with p._points_connection() as con:
        con.execute('BEGIN IMMEDIATE')
        _state(con, p._make_user_key(uid, gid))
        receipt_key=f'{gid}:{uid}:use:{operation_id}'
        previous=p._db_get_section(con,'makeup_receipts',receipt_key,None)
        if previous: return previous
        record,key=p._db_get_user(con,uid,gid)
        state=_state(con,key)
        month=today.strftime('%Y-%m')
        if state['usage'].get(month,0)>=3: raise ValueError('本月已使用 3 次补签卡，请下个北京时间自然月再使用。')
        if state['inventory'].get(kind,0)<1: raise ValueError('该补签卡库存不足，请先购买。')
        dates=_signed_dates(con, uid, gid, record, state)
        if dates.intersection(targets): raise ValueError('所选日期包含已签到或已补签日期，请重新选择；未扣卡。')
        dates.update(targets)
        latest=max(dates)
        cursor=date.fromisoformat(latest); streak=0
        while cursor.isoformat() in dates:
            streak+=1; cursor-=timedelta(days=1)
        record.update(last_sign_date=latest,streak_days=streak)
        state['inventory'][kind]-=1
        state['dates'].extend(targets)
        state['usage'][month]=state['usage'].get(month,0)+1
        reward=p._round_shells(float(getattr(config,'POINTS_SIGN_REWARD',1.0))*len(targets))
        record['shells']=record['points']=p._round_shells(record.get('shells',0)+reward)
        p._db_append_transaction(con,record,user_id=uid,guild_id=gid,amount=reward,source='makeup_sign_reward',reason='、'.join(targets)+' 基础签到奖励',idempotency_key=receipt_key)
        p._db_put_user(con,key,record)
        p._db_put_section(con,'makeup_cards',key,state)
        result={'reward': reward, 'dates': targets, 'message':f'已补签 {chr(12289).join(targets)}（{len(targets)}天），当前最近一段连续签到 {streak} 天；本月已使用 {state["usage"][month]}/3 次。已补发基础签到奖励 {reward:g} 蛋壳。'}
        p._db_put_section(con,'makeup_receipts',receipt_key,result)
        return result


def _signed_dates(con, uid, gid, record, state):
    dates=set(state['dates'])
    for row in con.execute("SELECT item_key,data FROM point_sections WHERE namespace='daily_signins' AND item_key LIKE ?",(f'{gid}:%',)):
        if str(uid) in {str(v) for v in p._json_load(row['data'],[])}:
            dates.add(row['item_key'].split(':',1)[1])
    # Preserve migrated streak history even when old day tables are incomplete.
    if record.get('last_sign_date'):
        end=date.fromisoformat(record['last_sign_date'])
        for n in range(max(1,int(record.get('streak_days',0)))):
            dates.add((end-timedelta(days=n)).isoformat())
    return dates


@p._locked_points_data
def missing_dates(uid, gid, joined_date):
    """Only dates since membership can be selected; newest first."""
    if not joined_date:
        raise ValueError('无法获取入服日期，请重新打开面板。')
    p._ensure_points_db()
    with p._points_connection() as con:
        record,key=p._db_get_user(con,uid,gid)
        signed=_signed_dates(con,uid,gid,record,_state(con,key))
    start=date.fromisoformat(joined_date)
    end=date.fromisoformat(p._today())
    return [value for i in range(1,max(0,(end-start).days)+1)
            if (value := (end-timedelta(days=i)).isoformat()) not in signed]
