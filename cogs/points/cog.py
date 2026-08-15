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
    get_successful_praise_scan_record,
    record_message_activity,
    record_praise_scan_log,
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
PRAISE_INVALID_REACTION = "❌"
PRAISE_DUPLICATE_REACTION = "⭕"
PRAISE_PENDING_REACTION = "⏩"

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

    @staticmethod
    async def _add_reaction_once(message: discord.Message, emoji: str) -> bool:
        if not emoji:
            return False
        if any(str(reaction.emoji) == emoji for reaction in message.reactions):
            return True
        try:
            await message.add_reaction(emoji)
            return True
        except discord.HTTPException as error:
            print(f"[蛋壳系统][赞美奇米蛋] 添加反应失败 message={message.id} emoji={emoji!r} error={error}")
            return False

    async def _remove_own_reaction(self, message: discord.Message, emoji: str) -> bool:
        if not emoji or not self.bot.user:
            return False
        try:
            await message.remove_reaction(emoji, self.bot.user)
            return True
        except discord.HTTPException as error:
            print(f"[蛋壳系统][赞美奇米蛋] 移除反应失败 message={message.id} emoji={emoji!r} error={error}")
            return False

    async def _clear_praise_status_reactions(self, message: discord.Message) -> None:
        await self._remove_own_reaction(message, PRAISE_PENDING_REACTION)
        for emoji in (PRAISE_INVALID_REACTION, PRAISE_DUPLICATE_REACTION):
            if any(str(reaction.emoji) == emoji and reaction.me for reaction in message.reactions):
                await self._remove_own_reaction(message, emoji)

    @staticmethod
    def _print_praise_log(row: dict) -> None:
        print(
            "[蛋壳系统][赞美奇米蛋] "
            f"status={row.get('status')} reason={row.get('reason')} "
            f"guild={row.get('guild_id')} channel={row.get('channel_id')} "
            f"message={row.get('message_id')} author={row.get('author_id')}({row.get('author_name')}) "
            f"rule={row.get('rule_id') or '-'} amount={format_shells(row.get('amount', 0))} "
            f"recovered={row.get('recovered')} created_at={row.get('message_created_at')} "
            f"content={row.get('content')!r}"
        )

    async def _record_praise_log(
        self,
        message: discord.Message,
        *,
        status: str,
        reason: str,
        recovered: bool,
        rule: dict | None = None,
        amount: float = 0.0,
    ) -> dict:
        occurred_at = getattr(message, "created_at", None)
        created_at = occurred_at.isoformat() if occurred_at else ""
        fields = {
            "guild_id": message.guild.id if message.guild else 0,
            "channel_id": message.channel.id,
            "message_id": message.id,
            "author_id": message.author.id,
            "author_name": getattr(message.author, "name", ""),
            "content": message.content,
            "status": status,
            "reason": reason,
            "rule_id": (rule or {}).get("id", ""),
            "rule_field": (rule or {}).get("field", ""),
            "amount": amount,
            "recovered": recovered,
            "message_created_at": created_at,
        }
        try:
            row = await asyncio.to_thread(record_praise_scan_log, **fields)
        except Exception as error:
            row = fields
            print(
                f"[蛋壳系统][赞美奇米蛋] 扫描日志写入失败 message={message.id} "
                f"error={error!r} content={message.content!r}"
            )
        self._print_praise_log(row)
        return row

    async def _mark_praise_pending(
        self,
        message: discord.Message,
        *,
        reason: str,
        recovered: bool,
        rule: dict | None = None,
    ) -> None:
        await self._add_reaction_once(message, PRAISE_PENDING_REACTION)
        try:
            await self._record_praise_log(
                message,
                status="pending",
                reason=reason,
                recovered=recovered,
                rule=rule,
            )
        except Exception as log_error:
            print(
                f"[蛋壳系统][赞美奇米蛋] 待结算日志写入失败 message={message.id} "
                f"reason={reason} error={log_error!r} content={message.content!r}"
            )

    async def _reward_praise_message(self, message: discord.Message, *, recovered: bool = False, rules: list[dict] | None = None) -> bool | str | None:
        if not message.guild:
            return None
        if message.channel.id != PRAISE_KIMI_CHANNEL_ID:
            return None
        if message.author.bot:
            if recovered:
                await self._record_praise_log(
                    message,
                    status="skipped",
                    reason="bot_author",
                    recovered=recovered,
                )
            return None

        occurred_at = getattr(message, "created_at", None)
        try:
            rule = await asyncio.to_thread(match_praise_rule, message.content, occurred_at, rules)
        except Exception as error:
            await self._mark_praise_pending(
                message,
                reason=f"rule_match_error:{type(error).__name__}:{error}",
                recovered=recovered,
            )
            return "pending"
        if not rule:
            await self._remove_own_reaction(message, PRAISE_PENDING_REACTION)
            await self._record_praise_log(
                message,
                status="failed",
                reason="content_not_matched",
                recovered=recovered,
            )
            await self._add_reaction_once(message, PRAISE_INVALID_REACTION)
            return False

        if recovered:
            try:
                already_recorded = await asyncio.to_thread(
                    get_successful_praise_scan_record,
                    message.guild.id,
                    message.id,
                    rule["id"],
                )
            except Exception as error:
                await self._mark_praise_pending(
                    message,
                    reason=f"scan_record_error:{type(error).__name__}:{error}",
                    recovered=recovered,
                    rule=rule,
                )
                return "pending"
            if already_recorded:
                emoji = self._reward_emoji(float(already_recorded.get("amount", 0) or 0))
                marker_ready = not emoji or await self._add_reaction_once(message, emoji)
                if marker_ready:
                    await self._clear_praise_status_reactions(message)
                await self._record_praise_log(
                    message,
                    status="skipped",
                    reason="already_rewarded_in_scan_record",
                    recovered=recovered,
                    rule=rule,
                )
                return None

        await self._add_reaction_once(message, PRAISE_PENDING_REACTION)
        try:
            reward = await asyncio.to_thread(
                reward_daily_kimi_praise,
                user_id=message.author.id,
                guild_id=message.guild.id,
                message_id=message.id,
                rule_id=rule["id"],
                min_reward=rule["min_reward"],
                max_reward=rule["max_reward"],
                occurred_at=occurred_at,
            )
        except Exception as error:
            await self._mark_praise_pending(
                message,
                reason=f"reward_error:{type(error).__name__}:{error}",
                recovered=recovered,
                rule=rule,
            )
            return "pending"
        if not reward.get("success"):
            reason = str(reward.get("reason") or "reward_failed")
            amount = float(reward.get("amount", 0) or 0)

            # The balance write may have succeeded before a previous run was
            # interrupted while updating reactions. Restore that result instead
            # of treating the same message as a second claim.
            if reason == "duplicate_message":
                emoji = self._reward_emoji(amount)
                marker_ready = not emoji or await self._add_reaction_once(message, emoji)
                if marker_ready:
                    await self._clear_praise_status_reactions(message)
                await self._record_praise_log(
                    message,
                    status="rewarded",
                    reason="reward_reaction_recovered",
                    recovered=recovered,
                    rule=rule,
                    amount=amount,
                )
                return True

            await self._remove_own_reaction(message, PRAISE_PENDING_REACTION)
            await self._record_praise_log(
                message,
                status="failed",
                reason=reason,
                recovered=recovered,
                rule=rule,
                amount=amount,
            )
            marker = PRAISE_DUPLICATE_REACTION if reason == "already_claimed" else PRAISE_INVALID_REACTION
            await self._add_reaction_once(message, marker)
            return False

        amount = float(reward.get("amount", 0) or 0)
        emoji = self._reward_emoji(amount)
        marker_ready = not emoji or await self._add_reaction_once(message, emoji)
        if marker_ready:
            await self._clear_praise_status_reactions(message)
        await self._record_praise_log(
            message,
            status="rewarded",
            reason="rewarded",
            recovered=recovered,
            rule=rule,
            amount=amount,
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
            scanned = rewarded = pending = skipped = failed = 0
            async for message in channel.history(limit=None, after=after_utc, oldest_first=True):
                scanned += 1
                try:
                    result = await self._reward_praise_message(message, recovered=True, rules=rules)
                except Exception as error:
                    await self._mark_praise_pending(
                        message,
                        reason=f"unexpected_scan_error:{type(error).__name__}:{error}",
                        recovered=True,
                    )
                    result = "pending"
                if result is True:
                    rewarded += 1
                elif result is False:
                    failed += 1
                elif result == "pending":
                    pending += 1
                else:
                    skipped += 1
            print(
                f"[蛋壳系统][赞美奇米蛋] 今日重扫完成 channel={PRAISE_KIMI_CHANNEL_ID} "
                f"scanned={scanned} rewarded={rewarded} pending={pending} failed={failed} skipped={skipped}"
            )
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
            try:
                matched = await self._reward_praise_message(message)
            except Exception as error:
                await self._mark_praise_pending(
                    message,
                    reason=f"unexpected_live_error:{type(error).__name__}:{error}",
                    recovered=False,
                )
                return
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
