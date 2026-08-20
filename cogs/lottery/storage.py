# cogs/lottery/storage.py

import json
import os
import threading

from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace

LOTTERY_DATA_FILE = "data/general_lottery.json"
_DATA_LOCK = threading.RLock()

def load_lottery_data():
    """加载抽奖数据文件。"""
    raw = load_json_namespace(
        "general_lottery", legacy_file=LOTTERY_DATA_FILE, default={"active_lotteries": {}}
    )
    return raw if isinstance(raw, dict) else {"active_lotteries": {}}

def save_lottery_data(data):
    """保存抽奖数据文件。"""
    with _DATA_LOCK:
        save_json_namespace("general_lottery", data)
