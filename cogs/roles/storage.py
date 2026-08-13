# cogs/roles/storage.py

import json
import os
from typing import Dict, List

ROLES_DATA_FILE = "data/general_roles.json"
COLLECTIONS_DATA_FILE = "data/user_collections.json"
LOTTERY_STATS_DATA_FILE = "data/role_lottery_stats.json"
REDEEM_OWNERSHIP_DATA_FILE = "data/role_redeem_ownership.json"

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
    "discount_price": 0.0,
    "discount_start": "",
    "discount_end": "",
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
    return {
        "price": _normalize_shell_amount(raw.get("price", DEFAULT_REDEEM_ROLE_CONFIG["price"]), DEFAULT_REDEEM_ROLE_CONFIG["price"]),
        "discount_price": _normalize_shell_amount(raw.get("discount_price", DEFAULT_REDEEM_ROLE_CONFIG["discount_price"]), DEFAULT_REDEEM_ROLE_CONFIG["discount_price"]),
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

    return {
        "claimable_roles": claimable,
        "lottery_roles": lottery,
        "notification_roles": notify,
        "redeem_roles": redeem,
        "panel_info": panel_info,
        "lottery_role_meta": role_meta,
        "redeem_role_meta": redeem_meta,
        "lottery_config": lottery_config,
    }

# --- 身份组配置数据 ---
def load_role_data():
    if not os.path.exists(ROLES_DATA_FILE):
        return _normalize_role_data({})
    try:
        with open(ROLES_DATA_FILE, "r", encoding="utf-8") as f:
            return _normalize_role_data(json.load(f))
    except Exception:
        return _normalize_role_data({})


def save_role_data(data):
    """保存身份组配置文件。"""
    normalized = _normalize_role_data(data)
    os.makedirs(os.path.dirname(ROLES_DATA_FILE), exist_ok=True)
    with open(ROLES_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=4, ensure_ascii=False)


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

def load_collections_data():
    """加载用户藏品数据。"""
    if not os.path.exists(COLLECTIONS_DATA_FILE):
        return {}
    try:
        with open(COLLECTIONS_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_collections_data(data):
    """保存用户藏品数据。"""
    os.makedirs(os.path.dirname(COLLECTIONS_DATA_FILE), exist_ok=True)
    with open(COLLECTIONS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def add_to_collection(user_id: int, role_id: int):
    """将一个稀有身份组添加到用户的永久藏品中。"""
    uid_str = str(user_id)
    data = load_collections_data()
    if uid_str not in data:
        data[uid_str] = []

    if role_id not in data[uid_str]:
        data[uid_str].append(role_id)
        save_collections_data(data)

def get_user_collection(user_id: int) -> list:
    """获取一个用户的所有藏品ID列表。"""
    uid_str = str(user_id)
    data = load_collections_data()
    return data.get(uid_str, [])


def load_redeem_ownership_data():
    if not os.path.exists(REDEEM_OWNERSHIP_DATA_FILE):
        return {}
    try:
        with open(REDEEM_OWNERSHIP_DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(uid): _uniq_ids(role_ids) for uid, role_ids in raw.items()}


def save_redeem_ownership_data(data):
    os.makedirs(os.path.dirname(REDEEM_OWNERSHIP_DATA_FILE), exist_ok=True)
    normalized = {str(uid): _uniq_ids(role_ids) for uid, role_ids in (data or {}).items()}
    with open(REDEEM_OWNERSHIP_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=4, ensure_ascii=False)


def add_redeem_ownership(user_id: int, role_id: int):
    uid_str = str(user_id)
    data = load_redeem_ownership_data()
    roles = data.setdefault(uid_str, [])
    if role_id not in roles:
        roles.append(role_id)
        save_redeem_ownership_data(data)


def get_user_redeem_ownership(user_id: int) -> list[int]:
    return load_redeem_ownership_data().get(str(user_id), [])


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
    if not os.path.exists(LOTTERY_STATS_DATA_FILE):
        return {}
    try:
        with open(LOTTERY_STATS_DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): _normalize_lottery_stats(v) for k, v in raw.items()}


def save_lottery_stats_data(data: dict):
    os.makedirs(os.path.dirname(LOTTERY_STATS_DATA_FILE), exist_ok=True)
    normalized = {str(k): _normalize_lottery_stats(v) for k, v in (data or {}).items()}
    with open(LOTTERY_STATS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=4, ensure_ascii=False)


def get_lottery_stats(user_id: int, guild_id: int | None = None) -> dict:
    data = load_lottery_stats_data()
    return _normalize_lottery_stats(data.get(_make_lottery_user_key(user_id, guild_id), {}))


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
    data = load_lottery_stats_data()
    key = _make_lottery_user_key(user_id, guild_id)
    stats = _normalize_lottery_stats(data.get(key, {}))

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
            if row.get("dupe"):
                stats["duplicate_roles"] += 1
            else:
                stats["new_roles"] += 1

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
    data[key] = stats
    save_lottery_stats_data(data)
    return stats
