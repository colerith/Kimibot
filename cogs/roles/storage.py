# cogs/roles/storage.py

import json
import os

ROLES_DATA_FILE = "data/general_roles.json"

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
