# cogs/roles/storage.py

import json
import os
import copy
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from typing import Dict, List

from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace

ROLES_DATA_FILE = "data/general_roles.json"
COLLECTIONS_DATA_FILE = "data/user_collections.json"
LOTTERY_STATS_DATA_FILE = "data/role_lottery_stats.json"
REDEEM_OWNERSHIP_DATA_FILE = "data/role_redeem_ownership.json"
COLLECTION_REWARDS_DATA_FILE = "data/role_collection_rewards.json"
ROLE_STATE_DB_FILE = "data/role_user_state.sqlite3"

_collection_reward_lock = threading.Lock()
_ownership_lock = threading.RLock()
_lottery_stats_lock = threading.RLock()
_role_state_write_lock = threading.RLock()
_role_data_lock = threading.RLock()
_role_data_cache: dict | None = None
_role_data_cache_mtime_ns = -1
_role_state_ready = False

RARITY_NORMAL = 1
RARITY_RARE = 2
RARITY_LEGENDARY = 3
RARITY_JUNK = 4
SUPPORTED_RARITIES = (RARITY_NORMAL, RARITY_RARE, RARITY_LEGENDARY, RARITY_JUNK)
LOTTERY_KIND_COLOR = "color"
LOTTERY_KIND_ICON = "icon"
SUPPORTED_LOTTERY_KINDS = (LOTTERY_KIND_COLOR, LOTTERY_KIND_ICON)
LOTTERY_OUTCOME_ROLE = "role"
LOTTERY_OUTCOME_SHELLS = "shells"
LOTTERY_OUTCOME_EMPTY = "empty"
SUPPORTED_LOTTERY_OUTCOMES = (LOTTERY_OUTCOME_ROLE, LOTTERY_OUTCOME_SHELLS, LOTTERY_OUTCOME_EMPTY)

DEFAULT_LOTTERY_CONFIG = {
    "cost_single": 1.0,
    "cost_five": 5.0,
    "cost_ten": 10.0,
    "outcome_weights": {
        LOTTERY_OUTCOME_ROLE: 23,
        LOTTERY_OUTCOME_SHELLS: 32,
        LOTTERY_OUTCOME_EMPTY: 45,
    },
    "shell_reward": {
        "min": 0.1,
        "max": 1.0,
    },
    "weights": {
        str(RARITY_JUNK): 52,
        str(RARITY_NORMAL): 38,
        str(RARITY_RARE): 7,
        str(RARITY_LEGENDARY): 3,
    },
    "refund": {
            str(RARITY_JUNK): 0.5,
            str(RARITY_NORMAL): 1.0,
            str(RARITY_RARE): 2.0,
            str(RARITY_LEGENDARY): 5.0,
    },
}

DEFAULT_REDEEM_ROLE_CONFIG = {
    "price": 10.0,
    "sale_mode": "permanent",
    "discount_price": 0.0,
    "discount_start": "",
    "discount_end": "",
}

DEFAULT_FULL_COLLECTION_REWARD = {
    "name": "图鉴大师", "emoji": "👑", "description": "完整收集奖池中的全部身份组",
    "reward_shells": 0.0, "reward_role_id": 0,
}


def _normalize_shell_amount(value, default: float) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return default
    return round(max(0.0, amount), 1)


def _migrate_lottery_cost(value, default: float, *, old_defaults: tuple[float, ...]) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return default
    if amount in old_defaults:
        return default
    return round(max(0.1, amount), 1)


def _migrate_lottery_refund(value, default: float) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return default
    if amount >= 8:
        return default
    return round(max(0.0, amount), 1)


def _normalize_lottery_weights(weights: dict) -> dict:
    default_weights = DEFAULT_LOTTERY_CONFIG["weights"]
    normalized = {
        str(r): int(weights.get(str(r), default_weights[str(r)]))
        for r in SUPPORTED_RARITIES
    }
    old_default = {
        str(RARITY_JUNK): 40,
        str(RARITY_NORMAL): 40,
        str(RARITY_RARE): 15,
        str(RARITY_LEGENDARY): 5,
    }
    if normalized == old_default:
        return dict(default_weights)
    previous_default = {
        str(RARITY_JUNK): 55,
        str(RARITY_NORMAL): 37,
        str(RARITY_RARE): 6,
        str(RARITY_LEGENDARY): 2,
    }
    if normalized == previous_default:
        return dict(default_weights)
    return normalized


def _normalize_outcome_weights(weights: dict) -> dict:
    default_weights = DEFAULT_LOTTERY_CONFIG["outcome_weights"]
    normalized = {
        outcome: max(0, int(weights.get(outcome, default_weights[outcome])))
        for outcome in SUPPORTED_LOTTERY_OUTCOMES
    }
    previous_default = {
        LOTTERY_OUTCOME_ROLE: 20,
        LOTTERY_OUTCOME_SHELLS: 30,
        LOTTERY_OUTCOME_EMPTY: 50,
    }
    if normalized == previous_default:
        return dict(default_weights)
    return normalized


def _normalize_shell_reward(raw: dict) -> dict:
    default_reward = DEFAULT_LOTTERY_CONFIG["shell_reward"]
    if not isinstance(raw, dict):
        raw = {}
    min_amount = _normalize_shell_amount(raw.get("min", default_reward["min"]), default_reward["min"])
    max_amount = _normalize_shell_amount(raw.get("max", default_reward["max"]), default_reward["max"])
    if max_amount < min_amount:
        min_amount, max_amount = max_amount, min_amount
    return {"min": min_amount, "max": max_amount}


def _normalize_redeem_role_config(raw: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    sale_mode = str(raw.get("sale_mode", DEFAULT_REDEEM_ROLE_CONFIG["sale_mode"]) or "permanent").strip().lower()
    if sale_mode not in {"permanent", "limited"}:
        sale_mode = "permanent"
    return {
        "price": _normalize_shell_amount(raw.get("price", DEFAULT_REDEEM_ROLE_CONFIG["price"]), DEFAULT_REDEEM_ROLE_CONFIG["price"]),
        "sale_mode": sale_mode,
        "discount_price": 0.0 if sale_mode == "limited" else _normalize_shell_amount(raw.get("discount_price", DEFAULT_REDEEM_ROLE_CONFIG["discount_price"]), DEFAULT_REDEEM_ROLE_CONFIG["discount_price"]),
        "discount_start": str(raw.get("discount_start", "") or "").strip(),
        "discount_end": str(raw.get("discount_end", "") or "").strip(),
    }


def _uniq_ids(values) -> list[int]:
    seen = set()
    result = []
    for v in values or []:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv not in seen:
            seen.add(iv)
            result.append(iv)
    return result


def _normalize_collection_reward(raw: dict | None, defaults: dict | None = None) -> dict:
    base = dict(defaults or {})
    raw = raw if isinstance(raw, dict) else {}
    try:
        reward_role_id = int(raw.get("reward_role_id", base.get("reward_role_id", 0)) or 0)
    except (TypeError, ValueError):
        reward_role_id = 0
    return {
        "name": str(raw.get("name", base.get("name", "未命名分组")) or "未命名分组")[:80],
        "emoji": str(raw.get("emoji", base.get("emoji", "📚")) or "📚")[:20],
        "description": str(raw.get("description", base.get("description", "")) or "")[:240],
        "reward_shells": _normalize_shell_amount(raw.get("reward_shells", base.get("reward_shells", 0)), 0.0),
        "reward_role_id": max(0, reward_role_id),
    }


def _normalize_collection_config(raw: dict | None, lottery_ids: list[int]) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    lottery_set, used_ids, assigned_roles = set(lottery_ids), set(), set()
    groups = []
    items = raw.get("groups", []) if isinstance(raw.get("groups", []), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("id", "") or "").strip()[:64] or uuid.uuid4().hex[:12]
        if group_id in used_ids:
            continue
        used_ids.add(group_id)
        role_ids = [rid for rid in _uniq_ids(item.get("role_ids", [])) if rid in lottery_set and rid not in assigned_roles]
        assigned_roles.update(role_ids)
        groups.append({"id": group_id, "role_ids": role_ids, **_normalize_collection_reward(item)})
    return {"groups": groups, "full_reward": _normalize_collection_reward(raw.get("full_reward"), DEFAULT_FULL_COLLECTION_REWARD)}


def _normalize_role_data(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}

    claimable = _uniq_ids(data.get("claimable_roles", []))
    lottery = _uniq_ids(data.get("lottery_roles", []))
    notify = _uniq_ids(data.get("notification_roles", []))
    redeem = _uniq_ids(data.get("redeem_roles", []))

    role_meta_raw = data.get("lottery_role_meta", {})
    role_meta = {}
    if isinstance(role_meta_raw, dict):
        for rid in lottery:
            meta = role_meta_raw.get(str(rid), {})
            rarity = int(meta.get("rarity", RARITY_NORMAL)) if isinstance(meta, dict) else RARITY_NORMAL
            if rarity not in SUPPORTED_RARITIES:
                rarity = RARITY_NORMAL
            kind = str(meta.get("kind", LOTTERY_KIND_COLOR)) if isinstance(meta, dict) else LOTTERY_KIND_COLOR
            if kind not in SUPPORTED_LOTTERY_KINDS:
                kind = LOTTERY_KIND_COLOR
            role_meta[str(rid)] = {"rarity": rarity, "kind": kind}
    else:
        for rid in lottery:
            role_meta[str(rid)] = {"rarity": RARITY_NORMAL, "kind": LOTTERY_KIND_COLOR}

    redeem_meta_raw = data.get("redeem_role_meta", {})
    redeem_meta = {}
    for rid in redeem:
        meta = redeem_meta_raw.get(str(rid), {}) if isinstance(redeem_meta_raw, dict) else {}
        redeem_meta[str(rid)] = _normalize_redeem_role_config(meta)

    cfg = data.get("lottery_config", {})
    if not isinstance(cfg, dict):
        cfg = {}

    weights = cfg.get("weights", {}) if isinstance(cfg.get("weights", {}), dict) else {}
    outcome_weights = cfg.get("outcome_weights", {}) if isinstance(cfg.get("outcome_weights", {}), dict) else {}
    shell_reward = cfg.get("shell_reward", {}) if isinstance(cfg.get("shell_reward", {}), dict) else {}
    refund = cfg.get("refund", {}) if isinstance(cfg.get("refund", {}), dict) else {}
    lottery_config = {
        "cost_single": _migrate_lottery_cost(
            cfg.get("cost_single", DEFAULT_LOTTERY_CONFIG["cost_single"]),
            DEFAULT_LOTTERY_CONFIG["cost_single"],
            old_defaults=(3.0, 50.0, 100.0),
        ),
        "cost_five": _migrate_lottery_cost(
            cfg.get("cost_five", DEFAULT_LOTTERY_CONFIG["cost_five"]),
            DEFAULT_LOTTERY_CONFIG["cost_five"],
            old_defaults=(100.0,),
        ),
        "cost_ten": _migrate_lottery_cost(
            cfg.get("cost_ten", DEFAULT_LOTTERY_CONFIG["cost_ten"]),
            DEFAULT_LOTTERY_CONFIG["cost_ten"],
            old_defaults=(25.0, 100.0, 888.0, 900.0),
        ),
        "outcome_weights": _normalize_outcome_weights(outcome_weights),
        "shell_reward": _normalize_shell_reward(shell_reward),
        "weights": _normalize_lottery_weights(weights),
        "refund": {
                str(r): _migrate_lottery_refund(
                    refund.get(str(r), DEFAULT_LOTTERY_CONFIG["refund"][str(r)]),
                    DEFAULT_LOTTERY_CONFIG["refund"][str(r)],
                )
            for r in SUPPORTED_RARITIES
        },
    }

    panel_info = data.get("panel_info", {})
    if not isinstance(panel_info, dict):
        panel_info = {}
    collection_config = _normalize_collection_config(data.get("collection_config"), lottery)

    return {
        "claimable_roles": claimable,
        "lottery_roles": lottery,
        "notification_roles": notify,
        "redeem_roles": redeem,
        "panel_info": panel_info,
        "lottery_role_meta": role_meta,
        "redeem_role_meta": redeem_meta,
        "lottery_config": lottery_config,
        "collection_config": collection_config,
    }

# --- 身份组配置数据 ---
def load_role_data():
    """读取低频变更的奖池配置，并按文件 mtime 缓存规范化结果。"""
    global _role_data_cache, _role_data_cache_mtime_ns
    with _role_data_lock:
        try:
            mtime_ns = os.stat(ROLES_DATA_FILE).st_mtime_ns
        except OSError:
            mtime_ns = -1
        if _role_data_cache is not None and mtime_ns == _role_data_cache_mtime_ns:
            return copy.deepcopy(_role_data_cache)
        try:
            with open(ROLES_DATA_FILE, "r", encoding="utf-8") as file:
                normalized = _normalize_role_data(json.load(file))
        except (OSError, json.JSONDecodeError):
            normalized = _normalize_role_data({})
        _role_data_cache = normalized
        _role_data_cache_mtime_ns = mtime_ns
        return copy.deepcopy(normalized)


def save_role_data(data):
    """保存身份组配置文件。"""
    global _role_data_cache, _role_data_cache_mtime_ns
    normalized = _normalize_role_data(data)
    with _role_data_lock:
        os.makedirs(os.path.dirname(ROLES_DATA_FILE), exist_ok=True)
        temp_file = f"{ROLES_DATA_FILE}.{os.getpid()}.tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(normalized, file, indent=4, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_file, ROLES_DATA_FILE)
        _role_data_cache = normalized
        _role_data_cache_mtime_ns = os.stat(ROLES_DATA_FILE).st_mtime_ns


def get_lottery_role_rarity(role_id: int, role_data: dict | None = None) -> int:
    data = role_data if role_data is not None else load_role_data()
    meta = data.get("lottery_role_meta", {})
    rarity = int(meta.get(str(role_id), {}).get("rarity", RARITY_NORMAL))
    return rarity if rarity in SUPPORTED_RARITIES else RARITY_NORMAL


def get_lottery_role_kind(role_id: int, role_data: dict | None = None) -> str:
    data = role_data if role_data is not None else load_role_data()
    meta = data.get("lottery_role_meta", {})
    kind = str(meta.get(str(role_id), {}).get("kind", LOTTERY_KIND_COLOR))
    return kind if kind in SUPPORTED_LOTTERY_KINDS else LOTTERY_KIND_COLOR


def get_lottery_pools_by_rarity(role_data: dict | None = None) -> Dict[int, List[int]]:
    data = role_data if role_data is not None else load_role_data()
    pools = {r: [] for r in SUPPORTED_RARITIES}
    for rid in data.get("lottery_roles", []):
        rarity = get_lottery_role_rarity(rid, data)
        pools[rarity].append(rid)
    return pools


def get_lottery_pools_by_kind_and_rarity(role_data: dict | None = None) -> Dict[str, Dict[int, List[int]]]:
    data = role_data if role_data is not None else load_role_data()
    pools = {
        LOTTERY_KIND_COLOR: {r: [] for r in SUPPORTED_RARITIES},
        LOTTERY_KIND_ICON: {r: [] for r in SUPPORTED_RARITIES},
    }
    for rid in data.get("lottery_roles", []):
        kind = get_lottery_role_kind(rid, data)
        rarity = get_lottery_role_rarity(rid, data)
        pools[kind][rarity].append(rid)
    return pools


def get_lottery_config(role_data: dict | None = None) -> dict:
    data = role_data if role_data is not None else load_role_data()
    cfg = data.get("lottery_config", DEFAULT_LOTTERY_CONFIG)
    return _normalize_role_data({"lottery_config": cfg}).get("lottery_config", DEFAULT_LOTTERY_CONFIG)


def get_redeem_role_config(role_id: int, role_data: dict | None = None) -> dict:
    data = role_data if role_data is not None else load_role_data()
    meta = data.get("redeem_role_meta", {})
    return _normalize_redeem_role_config(meta.get(str(role_id), {}) if isinstance(meta, dict) else {})


def set_redeem_role_config(
    role_id: int,
    *,
    price: float,
    sale_mode: str = "permanent",
    discount_price: float = 0.0,
    discount_start: str = "",
    discount_end: str = "",
) -> bool:
    data = load_role_data()
    if role_id not in data.get("redeem_roles", []):
        return False

    data.setdefault("redeem_role_meta", {})[str(role_id)] = _normalize_redeem_role_config(
        {
            "price": price,
            "sale_mode": sale_mode,
            "discount_price": discount_price,
            "discount_start": discount_start,
            "discount_end": discount_end,
        }
    )
    save_role_data(data)
    return True


def set_lottery_role_rarity(role_id: int, rarity: int) -> bool:
    if rarity not in SUPPORTED_RARITIES:
        return False

    data = load_role_data()
    if role_id not in data.get("lottery_roles", []):
        return False

    current = data.setdefault("lottery_role_meta", {}).get(str(role_id), {})
    kind = str(current.get("kind", LOTTERY_KIND_COLOR))
    if kind not in SUPPORTED_LOTTERY_KINDS:
        kind = LOTTERY_KIND_COLOR
    data.setdefault("lottery_role_meta", {})[str(role_id)] = {"rarity": rarity, "kind": kind}
    save_role_data(data)
    return True


def set_lottery_role_kind(role_id: int, kind: str) -> bool:
    if kind not in SUPPORTED_LOTTERY_KINDS:
        return False

    data = load_role_data()
    if role_id not in data.get("lottery_roles", []):
        return False

    current = data.setdefault("lottery_role_meta", {}).get(str(role_id), {})
    rarity = int(current.get("rarity", RARITY_NORMAL))
    if rarity not in SUPPORTED_RARITIES:
        rarity = RARITY_NORMAL
    data.setdefault("lottery_role_meta", {})[str(role_id)] = {"rarity": rarity, "kind": kind}
    save_role_data(data)
    return True


def update_lottery_config(
    *,
    cost_single: float | None = None,
    cost_five: float | None = None,
    cost_ten: float | None = None,
    weights: dict | None = None,
    outcome_weights: dict | None = None,
    shell_reward: dict | None = None,
    refund: dict | None = None,
) -> dict:
    data = load_role_data()
    cfg = get_lottery_config(data)

    if cost_single is not None:
        cfg["cost_single"] = round(max(0.1, float(cost_single)), 1)
    if cost_five is not None:
        cfg["cost_five"] = round(max(cfg["cost_single"], float(cost_five)), 1)
    if cost_ten is not None:
        cfg["cost_ten"] = round(max(cfg.get("cost_five", cfg["cost_single"]), float(cost_ten)), 1)

    if isinstance(weights, dict):
        for rarity in SUPPORTED_RARITIES:
            key = str(rarity)
            if key in weights:
                cfg["weights"][key] = max(0, int(weights[key]))

    if isinstance(outcome_weights, dict):
        for outcome in SUPPORTED_LOTTERY_OUTCOMES:
            if outcome in outcome_weights:
                cfg["outcome_weights"][outcome] = max(0, int(outcome_weights[outcome]))

    if isinstance(shell_reward, dict):
        cfg["shell_reward"] = _normalize_shell_reward(shell_reward)

    if isinstance(refund, dict):
        for rarity in SUPPORTED_RARITIES:
            key = str(rarity)
            if key in refund:
                cfg["refund"][key] = round(max(0.0, float(refund[key])), 1)

    data["lottery_config"] = cfg
    save_role_data(data)
    return cfg


def get_collection_config(role_data: dict | None = None) -> dict:
    data = role_data if role_data is not None else load_role_data()
    return _normalize_collection_config(data.get("collection_config"), data.get("lottery_roles", []))


def save_collection_config(config_data: dict) -> dict:
    data = load_role_data()
    data["collection_config"] = _normalize_collection_config(config_data, data.get("lottery_roles", []))
    save_role_data(data)
    return data["collection_config"]


def get_collection_reward_role_ids(role_data: dict | None = None) -> list[int]:
    cfg = get_collection_config(role_data)
    ids = [g.get("reward_role_id", 0) for g in cfg.get("groups", [])]
    ids.append(cfg.get("full_reward", {}).get("reward_role_id", 0))
    return [rid for rid in _uniq_ids(ids) if rid > 0]


def load_collection_reward_claims() -> dict:
    raw = load_json_namespace(
        "role_collection_rewards", legacy_file=COLLECTION_REWARDS_DATA_FILE, default={}
    )
    if not isinstance(raw, dict):
        return {}
    return {str(uid): {"groups": [str(v) for v in rec.get("groups", [])], "full": bool(rec.get("full", False))}
            for uid, rec in raw.items() if isinstance(rec, dict)}


def _save_collection_reward_claims(data: dict) -> None:
    save_json_namespace("role_collection_rewards", data)


def claim_completed_collection_rewards(user_id: int, owned_role_ids, role_data: dict | None = None) -> list[dict]:
    """Reserve newly completed achievements atomically; each reward is returned once."""
    data = role_data if role_data is not None else load_role_data()
    cfg = get_collection_config(data)
    owned, pool_ids, eligible = set(_uniq_ids(owned_role_ids)), set(data.get("lottery_roles", [])), []
    with _collection_reward_lock:
        claims = load_collection_reward_claims()
        record = claims.setdefault(str(user_id), {"groups": [], "full": False})
        claimed = set(str(v) for v in record.get("groups", []))
        for group in cfg.get("groups", []):
            required = set(group.get("role_ids", [])) & pool_ids
            group_id = str(group.get("id", ""))
            has_reward = float(group.get("reward_shells", 0) or 0) > 0 or int(group.get("reward_role_id", 0) or 0) > 0
            if required and required <= owned and has_reward and group_id not in claimed:
                eligible.append({"key": f"group:{group_id}", **group})
                claimed.add(group_id)
        record["groups"] = sorted(claimed)
        full_reward = cfg.get("full_reward", {})
        has_full_reward = float(full_reward.get("reward_shells", 0) or 0) > 0 or int(full_reward.get("reward_role_id", 0) or 0) > 0
        if pool_ids and pool_ids <= owned and has_full_reward and not record.get("full", False):
            eligible.append({"key": "full", **full_reward})
            record["full"] = True
        if eligible:
            _save_collection_reward_claims(claims)
    return eligible


def get_collection_reward_claim_status(user_id: int) -> dict:
    return load_collection_reward_claims().get(str(user_id), {"groups": [], "full": False})


def _connect_role_state_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(ROLE_STATE_DB_FILE), exist_ok=True)
    connection = sqlite3.connect(ROLE_STATE_DB_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


@contextmanager
def _role_state_connection():
    connection = _connect_role_state_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _read_json_dict(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _ensure_role_state_db() -> None:
    global _role_state_ready
    if _role_state_ready:
        return
    with _ownership_lock:
        if _role_state_ready:
            return
        with _role_state_connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS role_state_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS role_user_state (
                    namespace TEXT NOT NULL,
                    user_key TEXT NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY(namespace, user_key)
                );
                """
            )
            migrated = connection.execute(
                "SELECT value FROM role_state_meta WHERE key='json_migrated'"
            ).fetchone()
            if migrated is None:
                sources = {
                    "collections": _read_json_dict(COLLECTIONS_DATA_FILE),
                    "redeem": _read_json_dict(REDEEM_OWNERSHIP_DATA_FILE),
                    "lottery_stats": _read_json_dict(LOTTERY_STATS_DATA_FILE),
                }
                for namespace, rows in sources.items():
                    for user_key, value in rows.items():
                        if namespace in {"collections", "redeem"}:
                            value = _uniq_ids(value)
                        else:
                            value = _normalize_lottery_stats(value)
                        connection.execute(
                            "INSERT OR REPLACE INTO role_user_state(namespace, user_key, data) VALUES (?, ?, ?)",
                            (namespace, str(user_key), json.dumps(value, ensure_ascii=False, separators=(",", ":"))),
                        )
                connection.execute(
                    "INSERT INTO role_state_meta(key, value) VALUES ('json_migrated', '1')"
                )
                for path in (COLLECTIONS_DATA_FILE, REDEEM_OWNERSHIP_DATA_FILE, LOTTERY_STATS_DATA_FILE):
                    if os.path.exists(path) and not os.path.exists(f"{path}.pre_sqlite.bak"):
                        import shutil
                        shutil.copy2(path, f"{path}.pre_sqlite.bak")
        _role_state_ready = True


def initialize_role_state_storage() -> None:
    """启动期主动迁移抽卡藏品、兑换归属和保底统计。"""
    _ensure_role_state_db()


def _load_role_namespace(namespace: str) -> dict:
    _ensure_role_state_db()
    with _role_state_connection() as connection:
        return {
            row["user_key"]: json.loads(row["data"])
            for row in connection.execute(
                "SELECT user_key, data FROM role_user_state WHERE namespace=?", (namespace,)
            )
        }


def _save_role_namespace(namespace: str, data: dict) -> None:
    _ensure_role_state_db()
    with _role_state_write_lock:
        with _role_state_connection() as connection:
            connection.execute("DELETE FROM role_user_state WHERE namespace=?", (namespace,))
            connection.executemany(
                "INSERT INTO role_user_state(namespace, user_key, data) VALUES (?, ?, ?)",
                (
                    (namespace, str(key), json.dumps(value, ensure_ascii=False, separators=(",", ":")))
                    for key, value in (data or {}).items()
                ),
            )


def load_collections_data():
    """兼容批量管理调用；抽卡热路径使用单用户查询。"""
    return {str(uid): _uniq_ids(role_ids) for uid, role_ids in _load_role_namespace("collections").items()}


def save_collections_data(data):
    _save_role_namespace("collections", {str(uid): _uniq_ids(ids) for uid, ids in (data or {}).items()})

def add_to_collection(user_id: int, role_id: int):
    """将一个稀有身份组添加到用户的永久藏品中。"""
    add_many_to_collection(user_id, [role_id])


def add_many_to_collection(user_id: int, role_ids) -> list[int]:
    """一次事务加入多个藏品，避免十连抽逐次读写。"""
    _ensure_role_state_db()
    with _ownership_lock, _role_state_write_lock:
        with _role_state_connection() as connection:
            uid = str(user_id)
            row = connection.execute(
                "SELECT data FROM role_user_state WHERE namespace='collections' AND user_key=?", (uid,)
            ).fetchone()
            owned = set(_uniq_ids(json.loads(row["data"]) if row else []))
            owned.update(_uniq_ids(role_ids))
            normalized = sorted(owned)
            connection.execute(
                """INSERT INTO role_user_state(namespace, user_key, data) VALUES ('collections', ?, ?)
                   ON CONFLICT(namespace, user_key) DO UPDATE SET data=excluded.data""",
                (uid, json.dumps(normalized, separators=(",", ":"))),
            )
            return normalized

def get_user_collection(user_id: int) -> list:
    """获取一个用户的所有藏品ID列表。"""
    _ensure_role_state_db()
    with _role_state_connection() as connection:
        row = connection.execute(
            "SELECT data FROM role_user_state WHERE namespace='collections' AND user_key=?", (str(user_id),)
        ).fetchone()
        return _uniq_ids(json.loads(row["data"]) if row else [])


def load_redeem_ownership_data():
    return {str(uid): _uniq_ids(role_ids) for uid, role_ids in _load_role_namespace("redeem").items()}


def save_redeem_ownership_data(data):
    _save_role_namespace("redeem", {str(uid): _uniq_ids(role_ids) for uid, role_ids in (data or {}).items()})


def add_redeem_ownership(user_id: int, role_id: int):
    _ensure_role_state_db()
    with _ownership_lock, _role_state_write_lock:
        with _role_state_connection() as connection:
            uid = str(user_id)
            row = connection.execute(
                "SELECT data FROM role_user_state WHERE namespace='redeem' AND user_key=?", (uid,)
            ).fetchone()
            roles = set(_uniq_ids(json.loads(row["data"]) if row else []))
            roles.add(int(role_id))
            connection.execute(
                """INSERT INTO role_user_state(namespace, user_key, data) VALUES ('redeem', ?, ?)
                   ON CONFLICT(namespace, user_key) DO UPDATE SET data=excluded.data""",
                (uid, json.dumps(sorted(roles), separators=(",", ":"))),
            )


def get_user_redeem_ownership(user_id: int) -> list[int]:
    _ensure_role_state_db()
    with _role_state_connection() as connection:
        row = connection.execute(
            "SELECT data FROM role_user_state WHERE namespace='redeem' AND user_key=?", (str(user_id),)
        ).fetchone()
        return _uniq_ids(json.loads(row["data"]) if row else [])


def reconcile_cached_member_ownership(member_role_ids: dict[int, set[int]], role_data: dict | None = None) -> dict:
    """Bulk-import configured roles already present on cached guild members.

    This function performs only local JSON reads/writes. It never calls Discord.
    """
    data = role_data if role_data is not None else load_role_data()
    collectible_ids = set(data.get("lottery_roles", [])) | set(get_collection_reward_role_ids(data))
    redeem_ids = set(data.get("redeem_roles", []))
    collection_added = redeem_added = users_changed = 0

    with _ownership_lock, _role_state_write_lock:
        collections = load_collections_data()
        redeem_ownership = load_redeem_ownership_data()
        collections_changed = redeem_changed = False

        for user_id, raw_role_ids in member_role_ids.items():
            role_ids = set(_uniq_ids(raw_role_ids))
            found_collection = role_ids & collectible_ids
            found_redeem = role_ids & redeem_ids
            user_changed = False

            if found_collection:
                owned = set(_uniq_ids(collections.get(str(user_id), [])))
                missing = found_collection - owned
                if missing:
                    collections[str(user_id)] = sorted(owned | missing)
                    collection_added += len(missing)
                    collections_changed = user_changed = True

            if found_redeem:
                owned = set(_uniq_ids(redeem_ownership.get(str(user_id), [])))
                missing = found_redeem - owned
                if missing:
                    redeem_ownership[str(user_id)] = sorted(owned | missing)
                    redeem_added += len(missing)
                    redeem_changed = user_changed = True

            if user_changed:
                users_changed += 1

        if collections_changed:
            save_collections_data(collections)
        if redeem_changed:
            save_redeem_ownership_data(redeem_ownership)

    return {
        "users_changed": users_changed,
        "collection_roles_added": collection_added,
        "redeem_roles_added": redeem_added,
    }


def _make_lottery_user_key(user_id: int, guild_id: int | None = None) -> str:
    if guild_id is None:
        return str(user_id)
    return f"{guild_id}:{user_id}"


def _empty_lottery_stats() -> dict:
    return {
        "total_draws": 0,
        "role_hits": 0,
        "shell_hits": 0,
        "empty_hits": 0,
        "empty_streak": 0,
        "no_role_streak": 0,
        "no_legendary_streak": 0,
        "new_roles": 0,
        "duplicate_roles": 0,
        "spent_shells": 0.0,
        "refund_shells": 0.0,
        "reward_shells": 0.0,
        "rarity_hits": {
            str(RARITY_JUNK): 0,
            str(RARITY_NORMAL): 0,
            str(RARITY_RARE): 0,
            str(RARITY_LEGENDARY): 0,
        },
        "kind_hits": {
            LOTTERY_KIND_COLOR: 0,
            LOTTERY_KIND_ICON: 0,
        },
        "last_draw_at": "",
    }


def _normalize_lottery_stats(raw: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    base = _empty_lottery_stats()
    for key in (
        "total_draws",
        "role_hits",
        "shell_hits",
        "empty_hits",
        "empty_streak",
        "no_role_streak",
        "no_legendary_streak",
        "new_roles",
        "duplicate_roles",
    ):
        try:
            base[key] = max(0, int(raw.get(key, base[key])))
        except (TypeError, ValueError):
            pass
    for key in ("spent_shells", "refund_shells", "reward_shells"):
        base[key] = _normalize_shell_amount(raw.get(key, base[key]), base[key])

    rarity_raw = raw.get("rarity_hits", {}) if isinstance(raw.get("rarity_hits", {}), dict) else {}
    for rarity in SUPPORTED_RARITIES:
        key = str(rarity)
        try:
            base["rarity_hits"][key] = max(0, int(rarity_raw.get(key, base["rarity_hits"][key])))
        except (TypeError, ValueError):
            pass

    kind_raw = raw.get("kind_hits", {}) if isinstance(raw.get("kind_hits", {}), dict) else {}
    for kind in SUPPORTED_LOTTERY_KINDS:
        try:
            base["kind_hits"][kind] = max(0, int(kind_raw.get(kind, base["kind_hits"][kind])))
        except (TypeError, ValueError):
            pass

    base["last_draw_at"] = str(raw.get("last_draw_at", "") or "")
    return base


def load_lottery_stats_data() -> dict:
    return {str(key): _normalize_lottery_stats(value) for key, value in _load_role_namespace("lottery_stats").items()}


def save_lottery_stats_data(data: dict):
    _save_role_namespace(
        "lottery_stats",
        {str(key): _normalize_lottery_stats(value) for key, value in (data or {}).items()},
    )


def get_lottery_stats(user_id: int, guild_id: int | None = None) -> dict:
    _ensure_role_state_db()
    with _lottery_stats_lock:
        with _role_state_connection() as connection:
            row = connection.execute(
                "SELECT data FROM role_user_state WHERE namespace='lottery_stats' AND user_key=?",
                (_make_lottery_user_key(user_id, guild_id),),
            ).fetchone()
            return _normalize_lottery_stats(json.loads(row["data"]) if row else {})


def record_lottery_draw(
    user_id: int,
    guild_id: int | None,
    *,
    results: list[dict],
    spent_shells: float,
    refund_shells: float,
    reward_shells: float,
    drawn_at: str,
) -> dict:
    _ensure_role_state_db()
    with _lottery_stats_lock, _role_state_write_lock:
        key = _make_lottery_user_key(user_id, guild_id)
        with _role_state_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT data FROM role_user_state WHERE namespace='lottery_stats' AND user_key=?", (key,)
            ).fetchone()
            stats = _normalize_lottery_stats(json.loads(existing["data"]) if existing else {})
            stats["total_draws"] += len(results or [])
            stats["spent_shells"] = _normalize_shell_amount(stats["spent_shells"] + float(spent_shells or 0), 0.0)
            stats["refund_shells"] = _normalize_shell_amount(stats["refund_shells"] + float(refund_shells or 0), 0.0)
            stats["reward_shells"] = _normalize_shell_amount(stats["reward_shells"] + float(reward_shells or 0), 0.0)

            for row in results or []:
                row_type = row.get("type")
                if row_type == LOTTERY_OUTCOME_EMPTY or row_type == "empty":
                    stats["empty_hits"] += 1
                    stats["empty_streak"] += 1
                    stats["no_role_streak"] += 1
                    stats["no_legendary_streak"] += 1
                    continue
                if row_type == LOTTERY_OUTCOME_SHELLS or row_type == "shells":
                    stats["shell_hits"] += 1
                    stats["empty_streak"] = 0
                    stats["no_role_streak"] += 1
                    stats["no_legendary_streak"] += 1
                    continue
                if row_type == LOTTERY_OUTCOME_ROLE or row_type == "role":
                    stats["role_hits"] += 1
                    stats["empty_streak"] = 0
                    stats["no_role_streak"] = 0
                    stats["duplicate_roles"] += int(bool(row.get("dupe")))
                    stats["new_roles"] += int(not bool(row.get("dupe")))
                    rarity = str(row.get("rarity", ""))
                    if rarity in stats["rarity_hits"]:
                        stats["rarity_hits"][rarity] += 1
                    if rarity == str(RARITY_LEGENDARY):
                        stats["no_legendary_streak"] = 0
                    else:
                        stats["no_legendary_streak"] += 1
                    kind = str(row.get("kind", ""))
                    if kind in stats["kind_hits"]:
                        stats["kind_hits"][kind] += 1

            stats["last_draw_at"] = str(drawn_at or "")
            connection.execute(
                """INSERT INTO role_user_state(namespace, user_key, data) VALUES ('lottery_stats', ?, ?)
                   ON CONFLICT(namespace, user_key) DO UPDATE SET data=excluded.data""",
                (key, json.dumps(stats, ensure_ascii=False, separators=(",", ":"))),
            )
            return stats
