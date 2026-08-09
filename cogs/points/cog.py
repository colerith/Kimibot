# cogs/points/cog.py

import discord
from discord.ext import commands
import time
import re

import config
from .storage import (
    format_shells,
    record_message_activity,
    reward_daily_forum_post,
    reward_daily_kimi_praise,
)

FORUM_REWARD_CHANNEL_IDS = set(int(x) for x in getattr(config, "FORUM_REWARD_CHANNEL_IDS", []))
FORUM_REWARD_AMOUNT = float(getattr(config, "FORUM_REWARD_AMOUNT", getattr(config, "POINTS_POST_REWARD", 5.0)))
FORUM_REWARD_DAILY_POST_LIMIT = int(getattr(config, "FORUM_REWARD_DAILY_POST_LIMIT", 3))
POINTS_MSG_COOLDOWN = getattr(
    config,
    "POINTS_MSG_COOLDOWN",
    getattr(config, "COOLDOWN_SECONDS", 30),
)
PRAISE_KIMI_CHANNEL_ID = int(getattr(config, "PRAISE_KIMI_CHANNEL_ID", 1450480250210484357))
PRAISE_KIMI_TRIGGER = str(getattr(config, "PRAISE_KIMI_TRIGGER", "赞美奇米蛋！")).strip()
PRAISE_REWARD_EMOJIS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
}

def is_valid_comment(content: str) -> bool:
    """
    严格的发言质量检测，用于判断是否应该计入发言活跃。
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
    """监听社区活跃行为，记录发言活跃并发放指定帖子蛋壳。"""

    def __init__(self, bot):
        self.bot = bot
        self.user_cooldowns = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if (
            message.channel.id == PRAISE_KIMI_CHANNEL_ID
            and message.content.strip() == PRAISE_KIMI_TRIGGER
        ):
            reward = reward_daily_kimi_praise(
                user_id=message.author.id,
                guild_id=message.guild.id,
                message_id=message.id,
            )
            if reward.get("success"):
                amount = int(float(reward.get("amount", 0) or 0))
                emoji = PRAISE_REWARD_EMOJIS.get(amount)
                if emoji:
                    try:
                        await message.add_reaction(emoji)
                    except discord.HTTPException:
                        pass
                print(
                    f"🥚 [蛋壳系统] {message.author.name} 赞美奇米蛋奖励 +{format_shells(amount)} 蛋壳 (Message {message.id})"
                )
            return

        now = time.time()
        last_time = self.user_cooldowns.get(message.author.id, 0)
        if (now - last_time) < POINTS_MSG_COOLDOWN:
            return

        if not is_valid_comment(message.content):
            return

        self.user_cooldowns[message.author.id] = now
        count = record_message_activity(
            user_id=message.author.id,
            guild_id=message.guild.id,
        )
        print(
            f"🥚 [蛋壳系统] {message.author.name} 今日有效发言 {count} 条 (Guild {message.guild.id})"
        )

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """社区发帖积分：仅统计论坛帖，避免普通讨论串滥用。"""
        if not thread or not thread.guild:
            return

        parent = thread.parent
        if not isinstance(parent, discord.ForumChannel):
            return

        author_id = getattr(thread, "owner_id", None)
        if not author_id:
            return

        member = thread.guild.get_member(author_id)
        if not member or member.bot:
            return

        if parent.id not in FORUM_REWARD_CHANNEL_IDS:
            return

        reward = reward_daily_forum_post(
            user_id=author_id,
            guild_id=thread.guild.id,
            channel_id=parent.id,
            thread_id=thread.id,
            amount=FORUM_REWARD_AMOUNT,
            daily_limit=FORUM_REWARD_DAILY_POST_LIMIT,
        )
        if reward.get("success"):
            print(
                f"🧵 [蛋壳系统] {member.name} 第 {reward['rank']} 帖奖励 +{format_shells(reward['amount'])} 蛋壳 (Channel {parent.id})"
            )
