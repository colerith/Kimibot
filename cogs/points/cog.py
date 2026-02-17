# cogs/points/cog.py

import discord
from discord.ext import commands, tasks
import time
import random
import re

from .storage import modify_user_points
from config import COOLDOWN_SECONDS

def is_valid_comment(content: str) -> bool:
    """
    严格的发言质量检测，用于判断是否应该给予积分。
    (此函数已从 general/core.py 移入，可根据需要启用)
    1. 移除 emoji、链接、空白
    2. 长度必须 > 5
    3. 不能纯数字
    4. 不能有大量重复字符 (如 aaaaa)
    5. 字符种类必须丰富 (避免 ababab)
    """
    if not content: return False

    content_no_emoji = re.sub(r'<a?:.+?:\d+>', '', content)
    content_clean = re.sub(r'http\S+', '', content_no_emoji).strip()
    content_clean = re.sub(r'\s+', '', content_clean)

    if len(content_clean) <= 5: return False
    if content_clean.isdigit(): return False
    if re.search(r'(.)\1{4,}', content_clean): return False
    if len(set(content_clean)) < 4: return False

    return True


class PointListener(commands.Cog):
    """一个专门负责监听用户发言并自动发放积分的Cog。"""

    def __init__(self, bot):
        self.bot = bot
        self.user_cooldowns = {}    
        self.point_cache = {} 
        self.batch_save_task.start()

    def cog_unload(self):
        """当Cog被卸载时，取消后台任务。"""
        self.batch_save_task.cancel()

    @tasks.loop(minutes=2.0)
    async def batch_save_task(self):
        """每2分钟执行一次，将缓存中的积分批量写入文件。"""
        if not self.point_cache:
            return

        print(f"🌊 [积分系统] 开始批量保存积分... (共 {len(self.point_cache)} 位用户)")

        points_to_save = self.point_cache.copy()
        self.point_cache.clear()

        for user_id, points in points_to_save.items():
            if points > 0:
                new_total = modify_user_points(user_id, points)
                print(f"  └─ 用户 {user_id}: 结算 +{points} 积分 -> 当前总分 {new_total}")

        print(f"✨ [积分系统] 周期性保存完成。")

    @batch_save_task.before_loop
    async def before_batch_save(self):
        """在任务开始前，等待机器人完全准备好。"""
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        now = time.time()
        last_time = self.user_cooldowns.get(message.author.id, 0)
        if (now - last_time) < COOLDOWN_SECONDS:
            return 

        if len(message.content) > 2:
            self.user_cooldowns[message.author.id] = now

            points_to_add = random.randint(1, 3)
            current_cache = self.point_cache.get(message.author.id, 0)
            self.point_cache[message.author.id] = current_cache + points_to_add

            print(f"💰 [积分缓存] {message.author.name} 发言有效，暂存 +{points_to_add} 积分。")