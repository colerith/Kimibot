import math
import re
import time
from collections import defaultdict

import discord
from discord import Option
from discord.ext import commands, tasks

from config import IDS
from .blocker_db import scam_db
from .blocker_ui import (
    build_context_feedback,
    build_log_embed,
    build_manage_regex_embed,
    build_notice_embed,
)
from .punishment_db import db as punishment_db
from ..shared.utils import is_super_egg

PUBLIC_NOTICE_CHANNEL_ID = IDS.get("PUBLIC_NOTICE_CHANNEL_ID")
LOG_CHANNEL_ID = IDS.get("LOG_CHANNEL_ID")


class ScamBlockerCog(commands.Cog, name="广告拦截"):
    ITEMS_PER_PAGE = 15

    def __init__(self, bot):
        self.bot = bot
        self.rules_cache: list[re.Pattern] = []
        self._punishing: set[int] = set()

        self.message_tracker: dict[int, list[dict]] = defaultdict(list)
        self.spam_time_window = 10
        self.spam_channel_limit = 8

    async def cog_load(self):
        await self.refresh_rules_cache()
        self.clean_db_task.start()

    def cog_unload(self):
        if self.clean_db_task.is_running():
            self.clean_db_task.cancel()

    @tasks.loop(hours=1)
    async def clean_db_task(self):
        await scam_db.clean_old_logs()
        self.message_tracker.clear()

    async def refresh_rules_cache(self):
        rules = await scam_db.get_all_rules()
        compiled = []
        for _, pattern in rules:
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                continue
        self.rules_cache = compiled

    async def punish_user(
        self,
        guild: discord.Guild,
        user_id: int,
        reason: str,
        executor: discord.User | discord.Member | None = None,
        member: discord.Member | None = None,
        trigger_detail: str | None = None,
    ) -> dict | None:
        if user_id in self._punishing:
            return None

        self._punishing.add(user_id)
        try:
            result = await self._remove_role_and_messages(guild, user_id, reason, member)

            if result["role_removed"] or result["deleted_count"] > 0:
                punishment_db.add_strike(user_id)
                await self._send_notifications(
                    guild=guild,
                    user_id=user_id,
                    reason=reason,
                    result=result,
                    executor=executor,
                    member=member,
                    trigger_detail=trigger_detail,
                )
            return result
        finally:
            self._punishing.discard(user_id)

    async def _remove_role_and_messages(
        self,
        guild: discord.Guild,
        user_id: int,
        reason: str,
        member: discord.Member | None,
    ) -> dict:
        result = {"role_removed": False, "deleted_count": 0, "channel_ids": set()}

        target_member = member
        if target_member is None:
            target_member = guild.get_member(user_id)
            if target_member is None:
                try:
                    target_member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    target_member = None
                except discord.HTTPException:
                    target_member = None

        if target_member:
            removable_roles = [r for r in target_member.roles if r != guild.default_role]
            if removable_roles:
                try:
                    await target_member.remove_roles(*removable_roles, reason=reason)
                    result["role_removed"] = True
                except discord.HTTPException:
                    pass

        records = await scam_db.get_user_messages(user_id)
        channel_msg_map: dict[int, list[discord.Object]] = {}
        for msg_id, ch_id in records:
            channel_msg_map.setdefault(ch_id, []).append(discord.Object(id=msg_id))

        result["channel_ids"] = set(channel_msg_map.keys())

        for ch_id, msg_objs in channel_msg_map.items():
            channel = await self._fetch_channel(guild, ch_id)
            if not channel or not isinstance(
                channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)
            ):
                continue

            for i in range(0, len(msg_objs), 100):
                chunk = msg_objs[i : i + 100]
                try:
                    await channel.delete_messages(chunk, reason=reason)
                    result["deleted_count"] += len(chunk)
                except discord.HTTPException:
                    pass

        await scam_db.delete_user_logs(user_id)
        return result

    async def _send_notifications(
        self,
        guild: discord.Guild,
        user_id: int,
        reason: str,
        result: dict,
        executor: discord.User | discord.Member | None,
        member: discord.Member | None,
        trigger_detail: str | None,
    ):
        real_executor = executor or self.bot.user
        target_user = member or await self._try_fetch_user(user_id)

        target_name = (
            (target_user.global_name or target_user.name)
            if target_user
            else f"未知用户({user_id})"
        )
        target_mention = target_user.mention if target_user else f"<@{user_id}>"

        detail_text = None
        if trigger_detail:
            parts = [f"触发方式: {trigger_detail}"]
            ch_ids = result.get("channel_ids", set())
            if ch_ids:
                ch_names = []
                for cid in ch_ids:
                    ch = guild.get_channel(cid) or guild.get_thread(cid)
                    ch_names.append(f"#{ch.name}" if ch else f"#{cid}")
                parts.append(f"涉及频道: {'  '.join(ch_names)}")
            detail_text = "\n".join(parts)

        notice_url = None
        notice_ch = await self._fetch_channel(guild, PUBLIC_NOTICE_CHANNEL_ID)
        if notice_ch:
            try:
                notice_embed = build_notice_embed(
                    target_name=target_name,
                    target_mention=target_mention,
                    reason=reason,
                    deleted_count=result["deleted_count"],
                )
                msg = await notice_ch.send(embed=notice_embed)
                notice_url = msg.jump_url
            except discord.HTTPException:
                pass

        log_ch = await self._fetch_channel(guild, LOG_CHANNEL_ID)
        if log_ch:
            try:
                log_embed = build_log_embed(
                    reason=reason,
                    executor_mention=real_executor.mention,
                    target_mention=target_mention,
                    notice_url=notice_url,
                    detail_text=detail_text,
                )
                await log_ch.send(
                    embed=log_embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if self._is_privileged(message.author):
            return

        await scam_db.log_message(
            message_id=message.id,
            user_id=message.author.id,
            channel_id=message.channel.id,
        )

        if self.rules_cache and message.content:
            for regex in self.rules_cache:
                if regex.search(message.content):
                    try:
                        await message.delete(reason="命中广告规则")
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        pass

                    pat_display = (
                        regex.pattern if len(regex.pattern) <= 80 else regex.pattern[:77] + "..."
                    )
                    await self.punish_user(
                        guild=message.guild,
                        user_id=message.author.id,
                        reason="恶意广告自动触发",
                        executor=self.bot.user,
                        member=message.author if isinstance(message.author, discord.Member) else None,
                        trigger_detail=f"正则匹配: `{pat_display}`",
                    )
                    return

        spam_contents = self._check_spam(message)
        if spam_contents is not None:
            combined = "\n".join(dict.fromkeys(spam_contents))
            _, extracted_links = await self._extract_and_save_links(combined, self.bot.user.id)

            await self.punish_user(
                guild=message.guild,
                user_id=message.author.id,
                reason="恶意广告自动触发",
                executor=self.bot.user,
                member=message.author if isinstance(message.author, discord.Member) else None,
                trigger_detail="跨频道速率拦截",
            )

            log_ch = await self._fetch_channel(message.guild, LOG_CHANNEL_ID)
            if log_ch:
                try:
                    view_embed = build_manage_regex_embed(
                        target_mention=message.author.mention,
                        extracted_links=extracted_links,
                    )
                    await log_ch.send(
                        embed=view_embed,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    pass

    def _check_spam(self, message: discord.Message) -> list[str] | None:
        user_id = message.author.id
        now = time.time()

        self.message_tracker[user_id].append(
            {
                "time": now,
                "channel_id": message.channel.id,
                "content": message.content or "",
            }
        )

        self.message_tracker[user_id] = [
            r for r in self.message_tracker[user_id] if now - r["time"] <= self.spam_time_window
        ]

        unique_channels = {r["channel_id"] for r in self.message_tracker[user_id]}
        if len(unique_channels) >= self.spam_channel_limit:
            contents = [r["content"] for r in self.message_tracker[user_id] if r["content"]]
            self.message_tracker.pop(user_id, None)
            return contents
        return None

    async def _extract_and_save_links(self, content: str, author_id: int) -> tuple[int, list[str]]:
        link_re = re.compile(r"((?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/[^\s]*)?)", re.IGNORECASE)
        added = 0
        extracted: list[str] = []

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue

            for match in link_re.findall(line):
                clean = match.rstrip(".,!?;:'\"。，！？；：”’])】}")
                if len(clean) < 5:
                    continue
                if await scam_db.add_rule(re.escape(clean), author_id):
                    added += 1
                    extracted.append(clean)

        if added > 0:
            await self.refresh_rules_cache()
        return added, extracted

    @staticmethod
    def _is_privileged(author) -> bool:
        if not isinstance(author, discord.Member):
            return False

        if author.guild_permissions.administrator:
            return True

        super_egg_role_id = IDS.get("SUPER_EGG_ROLE_ID")
        if super_egg_role_id and any(r.id == super_egg_role_id for r in author.roles):
            return True

        return False

    async def _try_fetch_user(self, user_id: int):
        try:
            return await self.bot.fetch_user(user_id)
        except discord.HTTPException:
            return None

    async def _fetch_channel(self, guild: discord.Guild, channel_id: int | None):
        if not channel_id:
            return None

        channel = guild.get_channel(channel_id) or guild.get_thread(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        return channel

    @discord.message_command(name="📢广告处罚")
    @is_super_egg()
    async def ad_punish_ctx(self, ctx: discord.ApplicationContext, message: discord.Message):
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        if not guild:
            await ctx.followup.send("❌ 无法在私信中使用。", ephemeral=True)
            return

        target = message.author
        member = target if isinstance(target, discord.Member) else guild.get_member(target.id)

        added_count, extracted_links = await self._extract_and_save_links(
            message.content or "",
            ctx.user.id,
        )

        result = await self.punish_user(
            guild=guild,
            user_id=target.id,
            reason="标记为盗号广告",
            executor=ctx.user,
            member=member,
            trigger_detail="人工上下文菜单处理",
        )

        try:
            await message.delete(reason="广告处罚触发消息清理")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

        log_ch = await self._fetch_channel(guild, LOG_CHANNEL_ID)
        if log_ch:
            try:
                manage_embed = build_manage_regex_embed(
                    target_mention=target.mention,
                    extracted_links=extracted_links,
                )
                await log_ch.send(
                    embed=manage_embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass

        feedback = build_context_feedback(result, target.mention, added_count)
        await ctx.followup.send(feedback, ephemeral=True)

    @discord.slash_command(name="广告规则列表", description="查看广告拦截规则")
    @is_super_egg()
    async def list_ad_rules(
        self,
        ctx: discord.ApplicationContext,
        page: Option(int, "页码", required=False, default=1),
    ):
        rules = await scam_db.get_all_rules()
        if not rules:
            await ctx.respond("当前没有广告规则。", ephemeral=True)
            return

        max_page = max(1, math.ceil(len(rules) / self.ITEMS_PER_PAGE))
        page = max(1, min(page, max_page))
        start = (page - 1) * self.ITEMS_PER_PAGE
        page_rules = rules[start : start + self.ITEMS_PER_PAGE]

        lines = [f"[{rid}] {pat}" for rid, pat in page_rules]
        embed = discord.Embed(title="广告规则列表", color=0x5865F2)
        embed.description = "```\n" + "\n".join(lines) + "\n```"
        embed.set_footer(text=f"第 {page}/{max_page} 页，总计 {len(rules)} 条")
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="添加广告规则", description="手动添加广告拦截规则")
    @is_super_egg()
    async def add_ad_rule(
        self,
        ctx: discord.ApplicationContext,
        pattern: Option(str, "正则表达式"),
    ):
        try:
            re.compile(pattern)
        except re.error as e:
            await ctx.respond(f"❌ 正则不合法: {e}", ephemeral=True)
            return

        ok = await scam_db.add_rule(pattern, ctx.user.id)
        if not ok:
            await ctx.respond("⚠️ 规则已存在。", ephemeral=True)
            return

        await self.refresh_rules_cache()
        await ctx.respond("✅ 规则添加成功。", ephemeral=True)

    @discord.slash_command(name="删除广告规则", description="按规则ID删除广告拦截规则")
    @is_super_egg()
    async def remove_ad_rule(
        self,
        ctx: discord.ApplicationContext,
        rule_id: Option(int, "规则ID"),
    ):
        rules = await scam_db.get_all_rules()
        exists = any(rid == rule_id for rid, _ in rules)
        if not exists:
            await ctx.respond("❌ 未找到该规则ID。", ephemeral=True)
            return

        await scam_db.delete_rule(rule_id)
        await self.refresh_rules_cache()
        await ctx.respond("✅ 规则删除成功。", ephemeral=True)
