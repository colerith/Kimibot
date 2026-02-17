# cogs/points/storage.py

import json
import os

POINTS_DATA_FILE = "data/user_points.json"
LOTTERY_DATA_FILE = "data/general_lottery.json"

def load_points_data():
    """加载用户积分数据，如果文件不存在则返回空字典。"""
    if not os.path.exists(POINTS_DATA_FILE):
        return {}
    try:
        with open(POINTS_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_points_data(data):
    """保存用户积分数据到文件。"""
    os.makedirs(os.path.dirname(POINTS_DATA_FILE), exist_ok=True)
    with open(POINTS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def modify_user_points(user_id: int, amount: int) -> int:
    """
    修改单个用户的积分。

    Args:
        user_id (int): 用户的ID。
        amount (int): 要增加或减少的积分量 (可以为负数)。

    Returns:
        int: 用户修改后的最新总积分。
    """
    data = load_points_data()
    uid = str(user_id)
    current_points = data.get(uid, 0)

    new_points = max(0, current_points + amount)

    data[uid] = new_points
    save_points_data(data)
    return new_points

def get_user_points(user_id: int) -> int:
    """
    获取单个用户的积分。

    Args:
        user_id (int): 用户的ID。

    Returns:
        int: 用户的当前积分，如果不存在则为0。
    """
    data = load_points_data()
    return data.get(str(user_id), 0)
