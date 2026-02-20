# cogs/lottery/storage.py

import json
import os

LOTTERY_DATA_FILE = "data/general_lottery.json"

def load_lottery_data():
    """加载抽奖数据文件。"""
    if not os.path.exists(LOTTERY_DATA_FILE):
        return {"active_lotteries": {}}
    try:
        with open(LOTTERY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"active_lotteries": {}}

def save_lottery_data(data):
    """保存抽奖数据文件。"""
    os.makedirs(os.path.dirname(LOTTERY_DATA_FILE), exist_ok=True)
    with open(LOTTERY_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)