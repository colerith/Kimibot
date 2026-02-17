#general/storage.py

import json
import os

ROLES_DATA_FILE = "data/general_roles.json"
LOTTERY_DATA_FILE = "data/general_lottery.json"

# --- 身份组配置数据 ---
def load_role_data():
    if not os.path.exists(ROLES_DATA_FILE):
        return {
            "claimable_roles": [], # 普通可领取的
            "lottery_roles": [],   # 抽奖池子的
            "panel_info": {}
        }
    try:
        with open(ROLES_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 确保旧数据结构兼容
            if "lottery_roles" not in data: data["lottery_roles"] = []
            return data
    except:
        return {"claimable_roles": [], "lottery_roles": [], "panel_info": {}}

def save_role_data(data):
    os.makedirs(os.path.dirname(ROLES_DATA_FILE), exist_ok=True)
    with open(ROLES_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- 用户积分数据 ---
def load_points_data():
    if not os.path.exists(POINTS_DATA_FILE):
        return {}
    try:
        with open(POINTS_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_points_data(data):
    os.makedirs(os.path.dirname(POINTS_DATA_FILE), exist_ok=True)
    with open(POINTS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def modify_user_points(user_id: int, amount: int):
    """ 修改用户积分，amount可以为负数 """
    data = load_points_data()
    uid = str(user_id)
    current = data.get(uid, 0)
    # 确保不扣成负数
    new_val = max(0, current + amount)
    data[uid] = new_val
    save_points_data(data)
    return new_val

def get_user_points(user_id: int):
    data = load_points_data()
    return data.get(str(user_id), 0)

# --- 抽奖数据 ---
def load_lottery_data():
    if not os.path.exists(LOTTERY_DATA_FILE):
        return {"active_lotteries": {}}
    try:
        with open(LOTTERY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"active_lotteries": {}}

def save_lottery_data(data):
    os.makedirs(os.path.dirname(LOTTERY_DATA_FILE), exist_ok=True)
    with open(LOTTERY_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)