# cogs/forum_tracker/utils.py

import discord
from .db import db

async def get_task_autocomplete(ctx: discord.AutocompleteContext):
    """为统计任务命令提供自动补全选项。"""
    tasks_data = db.get_tasks()
    user_input = ctx.value.lower()
    return [
        discord.OptionChoice(name=f"{task[1]} (ID: {task[0]})", value=str(task[0]))
        for task in tasks_data if user_input in task[1].lower() or str(task[0]) in user_input
    ]

def check_keywords(text: str, keywords_str: str, logic: str) -> bool:
    """
    检查文本是否符合关键词逻辑。
    :param text: 要检查的文本内容。
    :param keywords_str: 用逗号分隔的关键词字符串。
    :param logic: 'OR' 或 'AND'。
    """
    if not text or not keywords_str:
        return False

    # 统一中英文逗号为标准逗号
    keywords = [k.strip() for k in keywords_str.replace("，", ",").split(",") if k.strip()]

    if not keywords:
        return True # 如果关键词为空，视为无需过滤，直接通过

    text_lower = text.lower() # 统一转为小写进行不区分大小写的匹配

    if logic == 'AND':
        # 必须包含所有关键词
        return all(k.lower() in text_lower for k in keywords)
    else: # 'OR'
        # 包含任意一个关键词即可
        return any(k.lower() in text_lower for k in keywords)