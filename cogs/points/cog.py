# cogs/points/cog.py

import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import time
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import config
from .storage import (
    format_shells,
    record_message_activity,
    reward_daily_forum_post,
    reward_daily_kimi_praise,
    load_praise_rules,
    match_praise_rule,
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
PRAISE_RESCAN_MINUTES = max(1, int(getattr(config, "PRAISE_KIMI_RESCAN_MINUTES", 5)))
PRAISE_REWARD_EMOJIS = {
    0: "0️⃣",
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
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
        self.praise_scanner_started = False
        self.activity_write_lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.praise_scanner_started:
            self.praise_scanner_started = True
            self.praise_reward_rescan.change_interval(minutes=PRAISE_RESCAN_MINUTES)
            self.praise_reward_rescan.start()

    def cog_unload(self):
        self.praise_reward_rescan.cancel()

    @staticmethod
    def _reward_emoji(amount: float) -> str | None:
        try:
            value = Decimal(str(amount or 0))
        except (InvalidOperation, ValueError):
            return None
        if value <= 0:
            return None
        rounded = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return PRAISE_REWARD_EMOJIS.get(rounded, "🥚")

    async def _reward_praise_message(self, message: discord.Message, *, recovered: bool = False, rules: list[dict] | None = None) -> bool | None:
        if message.author.bot or not message.guild:
            return None
        if message.channel.id != PRAISE_KIMI_CHANNEL_ID:
            return None
        occurred_at = getattr(message, "created_at", None)
        rule = await asyncio.to_thread(match_praise_rule, message.content, occurred_at, rules)
        if not rule:
            return None

        reward = await asyncio.to_thread(
            reward_daily_kimi_praise,
            user_id=message.author.id,
            guild_id=message.guild.id,
            message_id=message.id,
            rule_id=rule["id"],
            min_reward=rule["min_reward"],
            max_reward=rule["max_reward"],
        )
        if not reward.get("success"):
            if reward.get("reason") in {"already_claimed", "duplicate_message"} and reward.get("message_id") == str(message.id):
                emoji = self._reward_emoji(reward.get("amount", 0))
                if emoji and not any(str(reaction.emoji) == emoji for reaction in message.reactions):
                    try:
                        await message.add_reaction(emoji)
                    except discord.HTTPException:
                        pass
            return False

        amount = float(reward.get("amount", 0) or 0)
        emoji = self._reward_emoji(amount)
        if emoji:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                pass
        marker = "定期扫描补发" if recovered else "即时奖励"
        print(
            f"🥚 [蛋壳系统] {message.author.name} 触发识别规则{marker} "
            f"+{format_shells(amount)} 蛋壳 (Rule {rule['id']}, Message {message.id})"
        )
        return True

    @tasks.loop(minutes=5)
    async def praise_reward_rescan(self):
        channel = self.bot.get_channel(PRAISE_KIMI_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(PRAISE_KIMI_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return

        today_cn = datetime.datetime.now(config.TZ_CN).date()
        after_cn = datetime.datetime.combine(today_cn, datetime.time.min, tzinfo=config.TZ_CN)
        after_utc = after_cn.astimezone(datetime.timezone.utc)
        try:
            rules = await asyncio.to_thread(load_praise_rules)
            async for message in channel.history(limit=None, after=after_utc, oldest_first=True):
                await self._reward_praise_message(message, recovered=True, rules=rules)
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"[蛋壳系统] 赞美奇米蛋补发扫描失败: {error}")

    @praise_reward_rescan.before_loop
    async def before_praise_reward_rescan(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if message.channel.id == PRAISE_KIMI_CHANNEL_ID:
            matched = await self._reward_praise_message(message)
            if matched is not None:
                return

        now = time.time()
        last_time = self.user_cooldowns.get(message.author.id, 0)
        if (now - last_time) < POINTS_MSG_COOLDOWN:
            return

        if not is_valid_comment(message.content):
            return

        self.user_cooldowns[message.author.id] = now
        # user_points.json 会随用户量增长。整文件读写不能占用 Discord 的
        # asyncio 事件循环，否则同一时刻到达的按钮交互可能错过首次响应。
        # 串行化写入也可避免两条并发消息互相覆盖数据。
        async with self.activity_write_lock:
            await asyncio.to_thread(
                record_message_activity,
                user_id=message.author.id,
                guild_id=message.guild.id,
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
