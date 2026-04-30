# cogs/roles/storage.py

import json
import os
from typing import Dict, List

ROLES_DATA_FILE = "data/general_roles.json"
COLLECTIONS_DATA_FILE = "data/user_collections.json"

RARITY_NORMAL = 1
RARITY_RARE = 2
RARITY_LEGENDARY = 3
RARITY_JUNK = 4
SUPPORTED_RARITIES = (RARITY_NORMAL, RARITY_RARE, RARITY_LEGENDARY, RARITY_JUNK)
LOTTERY_KIND_COLOR = "color"
LOTTERY_KIND_ICON = "icon"
SUPPORTED_LOTTERY_KINDS = (LOTTERY_KIND_COLOR, LOTTERY_KIND_ICON)

DEFAULT_LOTTERY_CONFIG = {
    "cost_single": 50,
    "cost_ten": 888,
    "weights": {
        str(RARITY_JUNK): 40,
        str(RARITY_NORMAL): 40,
        str(RARITY_RARE): 15,
        str(RARITY_LEGENDARY): 5,
    },
    "refund": {
        str(RARITY_JUNK): 8,
        str(RARITY_NORMAL): 20,
        str(RARITY_RARE): 40,
        str(RARITY_LEGENDARY): 100,
    },
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

    cfg = data.get("lottery_config", {})
    if not isinstance(cfg, dict):
        cfg = {}

    weights = cfg.get("weights", {}) if isinstance(cfg.get("weights", {}), dict) else {}
    refund = cfg.get("refund", {}) if isinstance(cfg.get("refund", {}), dict) else {}
    lottery_config = {
        "cost_single": int(cfg.get("cost_single", DEFAULT_LOTTERY_CONFIG["cost_single"])),
        "cost_ten": max(888, int(cfg.get("cost_ten", DEFAULT_LOTTERY_CONFIG["cost_ten"]))),
        "weights": {
            str(r): int(weights.get(str(r), DEFAULT_LOTTERY_CONFIG["weights"][str(r)]))
            for r in SUPPORTED_RARITIES
        },
        "refund": {
            str(r): int(refund.get(str(r), DEFAULT_LOTTERY_CONFIG["refund"][str(r)]))
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
        "panel_info": panel_info,
        "lottery_role_meta": role_meta,
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
    cost_single: int | None = None,
    cost_ten: int | None = None,
    weights: dict | None = None,
    refund: dict | None = None,
) -> dict:
    data = load_role_data()
    cfg = get_lottery_config(data)

    if cost_single is not None:
        cfg["cost_single"] = max(1, int(cost_single))
    if cost_ten is not None:
        cfg["cost_ten"] = max(888, cfg["cost_single"], int(cost_ten))

    if isinstance(weights, dict):
        for rarity in SUPPORTED_RARITIES:
            key = str(rarity)
            if key in weights:
                cfg["weights"][key] = max(0, int(weights[key]))

    if isinstance(refund, dict):
        for rarity in SUPPORTED_RARITIES:
            key = str(rarity)
            if key in refund:
                cfg["refund"][key] = max(0, int(refund[key]))

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
