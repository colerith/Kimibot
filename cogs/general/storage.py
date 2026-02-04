import json
import os
import datetime

ROLES_DATA_FILE = "data/general_roles.json"
LOTTERY_DATA_FILE = "data/general_lottery.json"

# --- 身份组数据 ---
def load_role_data():
    if not os.path.exists(ROLES_DATA_FILE):
        return {"claimable_roles": []} # 存 Role ID
    try:
        with open(ROLES_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"claimable_roles": []}

def save_role_data(data):
    os.makedirs(os.path.dirname(ROLES_DATA_FILE), exist_ok=True)
    with open(ROLES_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- 抽奖数据 ---
# 结构: {"active_lotteries": { "message_id": { "channel_id": int, "end_timestamp": float, "prize": str, "winners": int, "text": str, "participants": [] } }}
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