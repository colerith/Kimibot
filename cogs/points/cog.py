# cogs/points/cog.py

import discord
from discord.ext import commands
import time
import random
import re

import config
from .storage import add_message_points

POINTS_DAILY_MSG_CAP = getattr(config, "POINTS_DAILY_MSG_CAP", 70)
POINTS_PER_MSG_MIN = getattr(config, "POINTS_PER_MSG_MIN", 1)
POINTS_PER_MSG_MAX = getattr(config, "POINTS_PER_MSG_MAX", 3)
POINTS_MSG_COOLDOWN = getattr(
    config,
    "POINTS_MSG_COOLDOWN",
    getattr(config, "COOLDOWN_SECONDS", 30),
)

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        now = time.time()
        last_time = self.user_cooldowns.get(message.author.id, 0)
        if (now - last_time) < POINTS_MSG_COOLDOWN:
            return

        if not is_valid_comment(message.content):
            return

        self.user_cooldowns[message.author.id] = now
        points_to_add = random.randint(POINTS_PER_MSG_MIN, POINTS_PER_MSG_MAX)

        gained = add_message_points(
            user_id=message.author.id,
            guild_id=message.guild.id,
            amount=points_to_add,
            daily_cap=POINTS_DAILY_MSG_CAP,
        )

        if gained > 0:
            print(
                f"💰 [积分系统] {message.author.name} 发言有效，+{gained} 积分 (Guild {message.guild.id})"
            )