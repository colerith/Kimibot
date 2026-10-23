"""Surprise slot machine: atomic debit/result/shards and recoverable wardrobe delivery."""
import math
import random
import os

from cogs.points import storage as points
from . import storage as roles


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


def get_config(guild_id):
    _ensure_storage()
    with points._points_connection() as con:
        return _get(con, "surprise_config", str(guild_id), {
            "enabled": False, "cost": roles.get_lottery_config().get("cost_single", 1.0),
            "chance": 10.0, "duplicate_shards": 1, "roles": {},
        })


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
            for name in ("cost", "chance", "duplicate_shards"):
                if name not in settings:
                    continue
                value = float(settings[name])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("费用、概率与碎片必须是非负有限数字。")
                if name == "chance" and value > 100:
                    raise ValueError("中奖概率应在 0–100% 之间。")
                if name == "duplicate_shards" and (value != int(value) or value < 1 or value > 1000000):
                    raise ValueError("重复奖励碎片应为 1–1000000 的整数。")
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


def get_account(user_id, guild_id, *, recover=True):
    _ensure_storage()
    with points._points_connection() as con:
        result = _get(con, "surprise_accounts", f"{guild_id}:{user_id}",
                                        {"owned": [], "shards": 0, "draws": 0})
    if recover and result["owned"]:
        roles.add_many_to_collection(user_id, result["owned"])
    return result


def recover_all_rewards():
    _ensure_storage()
    with points._points_connection() as con:
        rows = list(con.execute("SELECT item_key, data FROM surprise_state WHERE namespace='surprise_accounts'"))
    for row in rows:
        record = points._json_load(row["data"], {})
        if record.get("owned"):
            roles.add_many_to_collection(int(row["item_key"].split(":")[-1]), record["owned"])


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


def settle_spin(user_id, guild_id, operation_id, valid_role_ids, member_role_ids=(), *, rng=None, expected_config=None, symbols=None):
    """Persist money, shards, owned IDs and a replay receipt in one SQLite transaction.

    The collection mirror may fail independently; account recovery redelivers it idempotently.
    """
    _ensure_storage()
    with roles._ownership_lock, roles._role_data_lock, points._POINTS_DATA_LOCK:
        cfg = get_config(guild_id)
        receipt_key = f"{guild_id}:{user_id}:{operation_id}"
        owned = set(roles.get_user_collection(user_id)) | set(roles.get_user_redeem_ownership(user_id)) | set(member_role_ids)
        with points._points_connection() as con:
            con.execute("BEGIN IMMEDIATE")
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
                if balance < cfg["cost"]:
                    return {"success": False, "reason": f"蛋壳不足：需要 {cfg['cost']:g}，当前 {balance:g}。"}
                account = _get(con, "surprise_accounts", key, {"owned": [], "shards": 0, "draws": 0})
                reels = roll_reels(pool, cfg["chance"], rng)
                winner = reels[0] if len(set(reels)) == 1 else None
                duplicate = bool(winner and winner in owned | set(account["owned"]))
                shards = cfg["duplicate_shards"] if duplicate else 0
                if winner:
                    account["owned"] = sorted(set(account["owned"]) | {winner})
                account["shards"] += shards
                account["draws"] += 1
                balance = points._round_shells(balance - cfg["cost"])
                record["shells"] = record["points"] = balance
                points._db_append_transaction(con, record, user_id=user_id, guild_id=guild_id,
                    amount=-cfg["cost"], source="surprise_lottery", reason=f"reels={reels}",
                    idempotency_key=f"surprise:{receipt_key}")
                points._db_put_user(con, key, record)
                result = {"success": True, "reels": reels, "winner": winner, "duplicate": duplicate,
                          "shards_gained": shards, "shards": account["shards"], "cost": cfg["cost"],
                          "balance": balance, "chance": cfg["chance"]}
                if symbols:
                    result["symbols"] = [symbols[rid] for rid in reels]
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
