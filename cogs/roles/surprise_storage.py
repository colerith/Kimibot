"""Surprise slot machine: atomic debit/result/shards and recoverable wardrobe delivery."""
import math
import random
import os

from cogs.points import storage as points
from . import storage as roles

PITY_LIMIT = 80
BASE_CHANCE_CAP = 3.0


def _ensure_storage():
    points._ensure_points_db()
    with points._points_connection() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS surprise_state (
            namespace TEXT NOT NULL, item_key TEXT NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY(namespace, item_key))""")


def _get(con, namespace, key, default):
    row = con.execute("SELECT data FROM surprise_state WHERE namespace=? AND item_key=?", (namespace, str(key))).fetchone()
    return points._json_load(row["data"] if row else None, default)


def _put(con, namespace, key, value):
    con.execute("""INSERT INTO surprise_state(namespace, item_key, data) VALUES (?, ?, ?)
        ON CONFLICT(namespace, item_key) DO UPDATE SET data=excluded.data""", (namespace, str(key), points._json_dump(value)))


def ordinary_role_chance():
    """Cap surprise base odds at 3%, or use ordinary odds when lower (before pity)."""
    cfg = roles.get_lottery_config()["outcome_weights"]
    weights = [max(0, int(cfg.get(name, 1))) for name in ("role", "shells", "empty")]
    if sum(weights) <= 0:
        weights = [23, 32, 45]
    else:
        weights[0] = max(1, weights[0])
    return min(BASE_CHANCE_CAP, 100 * weights[0] / sum(weights))


def get_config(guild_id):
    _ensure_storage()
    with points._points_connection() as con:
        cfg = _get(con, "surprise_config", str(guild_id), {
            "enabled": False, "cost": roles.get_lottery_config().get("cost_single", 1.0),
            "duplicate_shards": 1, "roles": {},
        })
    # Ignore legacy independent probabilities, including already saved configs.
    cfg["chance"] = ordinary_role_chance()
    return cfg


def reserved_role_ids():
    """All configured surprise roles, including paused ones; ordinary pools are global."""
    if not os.path.exists(points.POINTS_DB_FILE):
        return set()
    with points._points_connection() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='surprise_state'").fetchone():
            return set()
        rows = con.execute("SELECT data FROM surprise_state WHERE namespace='surprise_config'")
        return {int(rid) for row in rows for rid in points._json_load(row["data"], {}).get("roles", {})}


def update_config(guild_id, *, settings=None, role_id=None, entry=None, remove=False):
    """Merge one edit under the points lock so concurrent admin panels cannot overwrite it."""
    with roles._role_data_lock, points._POINTS_DATA_LOCK:
        cfg = get_config(guild_id)
        if settings:
            if "chance" in settings:
                raise ValueError("基础中奖率取普通抽奖概率与 3% 中较低值，80 抽保底独立计算。")
            for name in ("cost", "duplicate_shards"):
                if name not in settings:
                    continue
                value = float(settings[name])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("费用、概率与蛋壳必须是非负有限数字。")
                if name == "duplicate_shards" and (value != int(value) or value < 1 or value > 1000000):
                    raise ValueError("重复奖励蛋壳应为 1–1000000 的整数。")
                cfg[name] = int(value) if name == "duplicate_shards" else round(value, 1 if name == "cost" else 4)
            if "enabled" in settings:
                cfg["enabled"] = bool(settings["enabled"])
        if role_id is not None:
            key = str(int(role_id))
            if remove:
                cfg["roles"].pop(key, None)
            elif entry is not None:
                if int(role_id) in roles.load_role_data().get("lottery_roles", []):
                    raise ValueError("该身份组已在普通抽奖奖池，请先从普通奖池移除。")
                weight = float(entry.get("weight", 1))
                if not math.isfinite(weight) or weight < 0 or weight > 1000000:
                    raise ValueError("身份组权重应在 0–1000000 之间；0 为暂停。")
                cfg["roles"][key] = {"weight": weight, "symbol": str(entry.get("symbol", "")).strip()}
        with points._points_connection() as con:
            _put(con, "surprise_config", str(guild_id), cfg)
        return cfg


def _credit_legacy_rewards(con, user_id, guild_id):
    key = f"{guild_id}:{user_id}"
    account = _get(con, "surprise_accounts", key, {"owned": [], "shards": 0, "draws": 0})
    total = int(account.get("shards", 0))
    credited = int(account.get("credited_shards", 0))
    delta = max(0, total - credited)
    if delta:
        record, wallet_key = points._db_get_user(con, user_id, guild_id)
        record["shells"] = record["points"] = points._round_shells(record.get("shells", 0) + delta)
        points._db_append_transaction(con, record, user_id=user_id, guild_id=guild_id,
            amount=delta, source="surprise_duplicate_backfill", reason="历史惊喜重复奖励补入蛋壳钱包",
            idempotency_key=f"surprise-backfill:{key}:{total}")
        points._db_put_user(con, wallet_key, record)
        account["credited_shards"] = total
        _put(con, "surprise_accounts", key, account)
    return account


def get_account(user_id, guild_id, *, recover=True):
    _ensure_storage()
    with points._points_connection() as con:
        con.execute("BEGIN IMMEDIATE")
        result = _credit_legacy_rewards(con, user_id, guild_id)
    if recover and result["owned"]:
        roles.add_many_to_collection(user_id, result["owned"])
    return result


def set_role_weights(guild_id, role_ids, weight):
    """Validate the entire selection before saving; preserve each role's own symbol."""
    weight = float(weight)
    if not math.isfinite(weight) or not 0 <= weight <= 1000000:
        raise ValueError("权重应在 0–1000000 之间；0 为暂停。")
    ids = set(int(rid) for rid in role_ids)
    if not ids:
        raise ValueError("请先选择身份组。")
    with roles._role_data_lock, points._POINTS_DATA_LOCK:
        if ids & set(roles.load_role_data().get("lottery_roles", [])):
            raise ValueError("所选身份组中有普通奖池身份组，本次未保存，请刷新后重选。")
        cfg = get_config(guild_id)
        for rid in ids:
            entry = cfg["roles"].setdefault(str(rid), {"symbol": ""})
            entry["weight"] = weight
        with points._points_connection() as con:
            _put(con, "surprise_config", str(guild_id), cfg)
    return cfg


def recover_all_rewards():
    _ensure_storage()
    with points._points_connection() as con:
        rows = list(con.execute("SELECT item_key, data FROM surprise_state WHERE namespace='surprise_accounts'"))
    for row in rows:
        guild_id, user_id = map(int, row["item_key"].split(":"))
        get_account(user_id, guild_id)



def roll_reels(pool, chance, rng=None):
    """Explicit overall win probability; conditional winning role uses configured weights.

    Miss reels are drawn without replacement, so a miss can never look like a win.
    This is deliberately not three independent reels (whose hit rate would differ).
    """
    rng = rng or random.SystemRandom()
    ids = list(pool)
    if not ids or (len(ids) < 2 and chance < 100):
        raise ValueError("非必中奖模式至少需要两个有效且图标不同的身份组。")
    if rng.random() * 100 < chance:
        winner = rng.choices(ids, weights=[pool[rid] for rid in ids], k=1)[0]
        return [winner] * 3
    first = rng.choices(ids, weights=[pool[rid] for rid in ids], k=1)[0]
    others = [rid for rid in ids if rid != first]
    second = rng.choices(others, weights=[pool[rid] for rid in others], k=1)[0]
    third = rng.choices(ids, weights=[pool[rid] for rid in ids], k=1)[0]
    reels = [first, second, third]
    rng.shuffle(reels)
    return reels


def refund_rules():
    cfg = roles.get_lottery_config()
    weights = cfg["outcome_weights"]
    shell = max(0, weights.get("shells", 0))
    empty = max(0, weights.get("empty", 0))
    return shell / (shell + empty) if shell + empty else 0, cfg["shell_reward"]


def miss_refund(rng, chance, limits):
    if rng.random() >= chance:
        return 0.0
    low, high = int(round(limits["min"] * 10)), int(round(limits["max"] * 10))
    steps = list(range(low, max(low, high) + 1))
    return rng.choices(steps, weights=[1 / ((n - low + 1) ** 1.35) for n in steps], k=1)[0] / 10


def settle_spin(user_id, guild_id, operation_id, valid_role_ids, member_role_ids=(), *, rng=None, expected_config=None, symbols=None, draw_count=1):
    """Persist money, shards, owned IDs and a replay receipt in one SQLite transaction.

    The collection mirror may fail independently; account recovery redelivers it idempotently.
    """
    if draw_count not in (1, 4, 10):
        raise ValueError("仅支持单抽、四连或十连。")
    rng = rng or random.SystemRandom()
    _ensure_storage()
    with roles._ownership_lock, roles._role_data_lock, points._POINTS_DATA_LOCK:
        cfg = get_config(guild_id)
        receipt_key = f"{guild_id}:{user_id}:{operation_id}"
        owned = set(roles.get_user_collection(user_id)) | set(roles.get_user_redeem_ownership(user_id)) | set(member_role_ids)
        with points._points_connection() as con:
            con.execute("BEGIN IMMEDIATE")
            _credit_legacy_rewards(con, user_id, guild_id)
            previous = _get(con, "surprise_receipts", receipt_key, None)
            if previous:
                result = previous
            else:
                if expected_config is not None and cfg != expected_config:
                    return {"success": False, "reason": "奖池配置刚刚更新，本次未扣费，请重新抽取。"}
                if not cfg["enabled"]:
                    return {"success": False, "reason": "惊喜抽奖尚未开放。"}
                pool = {int(rid): entry["weight"] for rid, entry in cfg["roles"].items()
                        if int(rid) in valid_role_ids and entry["weight"] > 0}
                if set(pool) & set(roles.load_role_data().get("lottery_roles", [])):
                    return {"success": False, "reason": "普通与惊喜奖池存在重复身份组，请管理员调整；本次未扣费。"}
                if not pool or (len(pool) < 2 and cfg["chance"] < 100):
                    return {"success": False, "reason": "有效奖池不足，请联系管理员配置。"}
                record, key = points._db_get_user(con, user_id, guild_id)
                balance = points._round_shells(record.get("shells", 0))
                from cogs.promotion.storage import discounted_cost, is_member
                unit_cost = discounted_cost(cfg["cost"], is_member(con, user_id, guild_id))
                total_cost = round(unit_cost * draw_count, 1)
                if balance < total_cost:
                    return {"success": False, "reason": f"蛋壳不足：需要 {total_cost:g}，当前 {balance:g}。"}
                account = _get(con, "surprise_accounts", key, {"owned": [], "shards": 0, "draws": 0})
                refund_chance, refund_limits = refund_rules()
                results = []
                for _ in range(draw_count):
                    misses_before = max(0, int(account.get("miss_streak", 0)))
                    pity_triggered = misses_before >= PITY_LIMIT - 1
                    reels = roll_reels(pool, 100 if pity_triggered else cfg["chance"], rng)
                    winner = reels[0] if len(set(reels)) == 1 else None
                    account["miss_streak"] = 0 if winner else misses_before + 1
                    duplicate = bool(winner and winner in owned | set(account["owned"]))
                    shards = cfg["duplicate_shards"] if duplicate else 0
                    refund = miss_refund(rng, refund_chance, refund_limits) if not winner else 0.0
                    if winner:
                        account["owned"] = sorted(set(account["owned"]) | {winner})
                    account["shards"] += shards
                    account["credited_shards"] = account.get("credited_shards", 0) + shards
                    account["draws"] += 1
                    balance = points._round_shells(balance - unit_cost + refund + shards)
                    row = {"success": True, "reels": reels, "winner": winner, "duplicate": duplicate,
                           "shards_gained": shards, "shards": account["shards"], "cost": unit_cost,
                           "refund": refund, "balance": balance, "chance": cfg["chance"],
                           "pity_triggered": pity_triggered, "miss_streak": account["miss_streak"],
                           "pity_remaining": PITY_LIMIT - account["miss_streak"]}
                    if symbols:
                        row["symbols"] = [symbols[rid] for rid in reels]
                    results.append(row)
                total_refund = round(sum(r["refund"] for r in results), 1)
                total_duplicates = sum(r["shards_gained"] for r in results)
                record["shells"] = record["points"] = points._round_shells(balance - total_refund - total_duplicates)
                points._db_append_transaction(con, record, user_id=user_id, guild_id=guild_id,
                    amount=-total_cost, source="surprise_lottery", reason=f"draw_count={draw_count}",
                    idempotency_key=f"surprise:{receipt_key}")
                record["shells"] = record["points"] = points._round_shells(balance - total_duplicates)
                if total_refund:
                    points._db_append_transaction(con, record, user_id=user_id, guild_id=guild_id,
                        amount=total_refund, source="surprise_lottery_refund", reason=f"draw_count={draw_count}",
                        idempotency_key=f"surprise-refund:{receipt_key}")
                record["shells"] = record["points"] = balance
                if total_duplicates:
                    points._db_append_transaction(con, record, user_id=user_id, guild_id=guild_id,
                        amount=total_duplicates, source="surprise_duplicate_reward", reason=f"draw_count={draw_count}",
                        idempotency_key=f"surprise-duplicate:{receipt_key}")
                points._db_put_user(con, key, record)
                result = results[0] if draw_count == 1 else {
                    "success": True, "results": results, "cost": total_cost, "refund": total_refund,
                    "balance": balance, "shards": account["shards"], "shards_gained": total_duplicates, "draw_count": draw_count,
                    "pity_remaining": PITY_LIMIT - account["miss_streak"]}
                account["last_result"] = result
                _put(con, "surprise_accounts", key, account)
                _put(con, "surprise_receipts", receipt_key, result)
        # Receipt is committed before touching wardrobe or making any Discord API calls.
        result = dict(result)
        try:
            get_account(user_id, guild_id)
        except Exception as error:
            print(f"[惊喜抽奖] 衣柜待恢复 guild={guild_id} user={user_id}: {error!r}")
            result["delivery_pending"] = True
        return result
