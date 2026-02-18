# cogs/roles/storage.py

import json
import os

ROLES_DATA_FILE = "data/general_roles.json"
COLLECTIONS_DATA_FILE = "data/user_collections.json"

# --- 身份组配置数据 ---
def load_role_data():
    if not os.path.exists(ROLES_DATA_FILE):
        return {
            "claimable_roles": [], 
            "lottery_roles": [],  
            "panel_info": {}
        }
    try:
        with open(ROLES_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "lottery_roles" not in data: data["lottery_roles"] = []
            return data
    except:
        return {"claimable_roles": [], "lottery_roles": [], "panel_info": {}}

def save_role_data(data):
    os.makedirs(os.path.dirname(ROLES_DATA_FILE), exist_ok=True)
    with open(ROLES_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def save_role_data(data):
    """保存身份组配置文件。"""
    os.makedirs(os.path.dirname(ROLES_DATA_FILE), exist_ok=True)
    with open(ROLES_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

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
