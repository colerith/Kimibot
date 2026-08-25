# cogs/manage/punishment_cog.py

import datetime
import asyncio
import io

import discord
from discord.ext import commands

from config import IDS, STYLE
from .punishment_db import db
from .punishment_style import (
    LOG_COLOR,
    beautify_historical_notice,
    build_dm_embed,
    build_public_notice_embed,
    is_public_punishment_embed,
)
from .punishment_views import ManagementControlView
from ..shared.utils import is_super_egg

PUBLIC_NOTICE_CHANNEL_ID = IDS.get("PUBLIC_NOTICE_CHANNEL_ID")
LOG_CHANNEL_ID = IDS.get("LOG_CHANNEL_ID", 1468508677144055818)
NEWBIE_ROLE_ID = IDS.get("VERIFICATION_ROLE_ID")
THIRD_PARTY_REASON = "使用第三方商业化API站点提问，违反社区规范"
THIRD_PARTY_MUTE_SECONDS = 24 * 60 * 60

ACTION_LABELS = {
    "warn": "警告",
    "unwarn": "撤销警告",
    "mute": "禁言",
    "kick": "踢出服务器",
    "ban": "封禁",
    "unmute": "解除禁言",
    "unban": "解除封禁",
    "third_party_quick": "第三方快速处罚",
}


class ThirdPartyQuickPunishmentModal(discord.ui.Modal):
    def __init__(self, cog, message: discord.Message):
        super().__init__(title="第三方快速处罚")
        self.cog = cog
        self.message = message
        self.add_item(
            discord.ui.InputText(
                label="违规原因",
                style=discord.InputTextStyle.paragraph,
                value=THIRD_PARTY_REASON,
                required=True,
                max_length=1000,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog._execute_third_party_quick_punishment(
            interaction,
            self.message,
            self.children[0].value.strip(),
        )


class CachedEvidenceAttachment:
    def __init__(self, attachment: discord.Attachment, data: bytes):
        self.url = attachment.url
        self.proxy_url = getattr(attachment, "proxy_url", None)
        self.filename = attachment.filename
        self.content_type = getattr(attachment, "content_type", None)
        self.size = getattr(attachment, "size", len(data))
        self._data = data

    async def to_file(self, *, spoiler: bool = False):
        return discord.File(
            io.BytesIO(self._data),
            filename=self.filename,
            spoiler=spoiler,
        )


class PunishmentCog(commands.Cog, name="处罚系统"):
    def __init__(self, bot):
        self.bot = bot
        self.persistent_view = None
        self.evidence_sessions = {}
        self._notice_refresh_task = None

    def _session_key(self, user_id: int, channel_id: int):
        return (user_id, channel_id)

    def get_evidence_session(self, user_id: int, channel_id: int):
        return self.evidence_sessions.get(self._session_key(user_id, channel_id))

    @staticmethod
    def _clone_file(src: discord.File):
        try:
            src.fp.seek(0)
        except Exception:
            pass
        data = src.fp.read()
        try:
            src.fp.seek(0)
        except Exception:
            pass
        return discord.File(io.BytesIO(data), filename=src.filename, spoiler=src.spoiler)

    @classmethod
    async def _evidence_files(cls, evidences, *, spoiler: bool = False):
        files = []
        for evidence in evidences or []:
            try:
                if isinstance(evidence, discord.File):
                    file = cls._clone_file(evidence)
                else:
                    file = await evidence.to_file(spoiler=spoiler)
                files.append(file)
            except (discord.NotFound, discord.HTTPException, TypeError, ValueError):
                continue
        return files

    async def send_punishment_dm(
        self,
        *,
        guild: discord.Guild,
        target_id: int,
        action: str,
        reason: str,
        action_detail: str | None = None,
        evidences=None,
        notice_url: str | None = None,
        punishment_id: int,
    ) -> bool:
        """Best-effort DM used by every punishment path."""
        target = guild.get_member(target_id)
        if target is None:
            try:
                target = await self.bot.fetch_user(target_id)
            except (discord.NotFound, discord.HTTPException):
                return False

        label = ACTION_LABELS.get(action, action)
        target_name = (
            getattr(target, "display_name", None)
            or getattr(target, "global_name", None)
            or target.name
        )
        embed = build_dm_embed(
            guild_name=guild.name,
            action=label,
            reason=reason,
            action_detail=action_detail,
            notice_url=notice_url,
            target_mention=target.mention,
            target_name=target_name,
            target_id=target_id,
            punishment_id=punishment_id,
        )

        files = await self._evidence_files(evidences, spoiler=False)
        try:
            await target.send(embed=embed, files=files)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def _expire_evidence_session(
        self,
        user_id: int,
        channel_id: int,
        expires_at: datetime.datetime,
    ):
        delay = max((expires_at - discord.utils.utcnow()).total_seconds(), 0)
        try:
            await asyncio.sleep(delay)
            key = self._session_key(user_id, channel_id)
            session = self.evidence_sessions.get(key)
            if not session or session["expires_at"] != expires_at:
                return
            self.evidence_sessions.pop(key, None)
            print(
                f"[Punishment] evidence-session-expired: user={user_id} channel={channel_id} attachments={len(session['attachments'])}"
            )
        except asyncio.CancelledError:
            pass

    def start_evidence_session(self, user_id: int, channel_id: int, duration_seconds: int = 300):
        key = self._session_key(user_id, channel_id)
        old = self.evidence_sessions.pop(key, None)
        if old and old.get("task"):
            old["task"].cancel()

        expires_at = discord.utils.utcnow() + datetime.timedelta(seconds=duration_seconds)
        task = self.bot.loop.create_task(
            self._expire_evidence_session(user_id, channel_id, expires_at)
        )
        self.evidence_sessions[key] = {
            "attachments": [],
            "message_ids": set(),
            "expires_at": expires_at,
            "task": task,
        }
        return expires_at

    async def finish_evidence_session(
        self,
        user_id: int,
        channel_id: int,
        cleanup_channel: discord.abc.Messageable | None = None,
    ):
        key = self._session_key(user_id, channel_id)
        session = self.evidence_sessions.pop(key, None)
        if not session:
            return None
        if session.get("task"):
            session["task"].cancel()

        deleted = 0
        failed = 0
        if cleanup_channel and session["message_ids"]:
            for message_id in session["message_ids"]:
                try:
                    await cleanup_channel.delete_messages(
                        [discord.Object(id=message_id)],
                        reason="证据收集完成后自动清理原消息",
                    )
                    deleted += 1
                except AttributeError:
                    try:
                        partial = cleanup_channel.get_partial_message(message_id)
                        await partial.delete(reason="证据收集完成后自动清理原消息")
                        deleted += 1
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        failed += 1
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    try:
                        partial = cleanup_channel.get_partial_message(message_id)
                        await partial.delete(reason="证据收集完成后自动清理原消息")
                        deleted += 1
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        failed += 1

        return {
            "attachments": list(session["attachments"]),
            "deleted_messages": deleted,
            "failed_deletions": failed,
        }

    def cancel_evidence_session(self, user_id: int, channel_id: int):
        key = self._session_key(user_id, channel_id)
        session = self.evidence_sessions.pop(key, None)
        if not session:
            return 0
        if session.get("task"):
            session["task"].cancel()
        return len(session["attachments"])

    async def _apply_single_action(
        self,
        guild: discord.Guild,
        target_id: int,
        action: str,
        reason: str,
        duration_secs: int,
    ):
        member = None

        try:
            member = guild.get_member(target_id) or await guild.fetch_member(target_id)
        except discord.NotFound:
            member = None

        punishment_id = db.add_punishment_record(target_id, action, reason)
        try:
            linked_action = ""
            dm_sent_before_action = False
            if action in {"kick", "ban"}:
                dm_sent_before_action = await self.send_punishment_dm(
                    guild=guild,
                    target_id=target_id,
                    action=action,
                    reason=reason,
                    action_detail="该管理操作即将执行",
                    punishment_id=punishment_id,
                )

            if action == "warn":
                if not member:
                    raise ValueError("用户不在服务器内，无法执行警告")

                strike = db.add_strike(target_id)
                linked_action = "无"
                expected_linked_action = (
                    "禁言 1 天" if strike == 1
                    else "禁言 7 天" if strike == 2
                    else "永久封禁"
                )
                await self.send_punishment_dm(
                    guild=guild,
                    target_id=target_id,
                    action=action,
                    reason=reason,
                    action_detail=f"第 {strike} 次警告；{expected_linked_action}",
                    punishment_id=punishment_id,
                )
                try:
                    if strike == 1:
                        await member.timeout(
                            discord.utils.utcnow() + datetime.timedelta(days=1),
                            reason=reason,
                        )
                        linked_action = "禁言 1 天"
                    elif strike == 2:
                        await member.timeout(
                            discord.utils.utcnow() + datetime.timedelta(days=7),
                            reason=reason,
                        )
                        linked_action = "禁言 7 天"
                    elif strike >= 3:
                        await guild.ban(discord.Object(id=target_id), reason=reason)
                        linked_action = "永久封禁"
                except (discord.Forbidden, discord.HTTPException, ValueError) as linked_err:
                    linked_action = f"自动处罚失败: {linked_err}"

                result = {
                    "ok": True,
                    "target_id": target_id,
                    "member": member,
                    "strike": strike,
                    "linked_action": linked_action,
                    "punishment_id": punishment_id,
                }
                return result

            elif action == "unwarn":
                strike = db.remove_strike(target_id)
                linked_action = "仅撤销累计，不自动反向解除处罚"

            elif action == "mute":
                if not member:
                    raise ValueError("用户不在服务器内，无法禁言")
                await member.timeout(
                    discord.utils.utcnow() + datetime.timedelta(seconds=duration_secs),
                    reason=reason,
                )

            elif action == "kick":
                if not member:
                    raise ValueError("用户不在服务器内，无法踢出")
                await member.kick(reason=reason)

            elif action == "ban":
                await guild.ban(discord.Object(id=target_id), reason=reason)

            elif action == "unmute":
                if not member:
                    raise ValueError("用户不在服务器内，无法解除禁言")
                await member.timeout(None, reason=reason)

            elif action == "unban":
                await guild.unban(discord.Object(id=target_id), reason=reason)

            else:
                raise ValueError("不支持的处罚动作")

            strike = db.get_strikes(target_id)

            action_detail = None
            if action == "mute":
                action_detail = f"已禁言 {max(duration_secs, 0)} 秒"
            elif action == "unwarn":
                action_detail = f"当前警告累计 {strike} 次"
            if not dm_sent_before_action:
                await self.send_punishment_dm(
                    guild=guild,
                    target_id=target_id,
                    action=action,
                    reason=reason,
                    action_detail=action_detail,
                    punishment_id=punishment_id,
                )

            return {
                "ok": True,
                "target_id": target_id,
                "member": member,
                "strike": strike,
                "linked_action": linked_action,
                "punishment_id": punishment_id,
            }

        except (discord.Forbidden, discord.HTTPException, ValueError) as e:
            return {
                "ok": False,
                "target_id": target_id,
                "member": member,
                "error": str(e),
            }

    @commands.Cog.listener()
    async def on_ready(self):
        if self.persistent_view is None:
            self.persistent_view = ManagementControlView(
                ctx=None,
                public_channel_id=PUBLIC_NOTICE_CHANNEL_ID,
                log_channel_id=LOG_CHANNEL_ID,
                timeout=None,
            )
            self.bot.add_view(self.persistent_view)

        if self._notice_refresh_task is None or self._notice_refresh_task.done():
            self._notice_refresh_task = self.bot.loop.create_task(
                self.refresh_public_notice_history()
            )

        print("[Punishment] Cog loaded and view registered (if persistent).")

    async def refresh_public_notice_history(self):
        channel = self.bot.get_channel(PUBLIC_NOTICE_CHANNEL_ID) if PUBLIC_NOTICE_CHANNEL_ID else None
        if channel is None and PUBLIC_NOTICE_CHANNEL_ID:
            try:
                channel = await self.bot.fetch_channel(PUBLIC_NOTICE_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        if channel is None or not hasattr(channel, "history"):
            print(f"[Punishment] notice-style-refresh-skipped: channel={PUBLIC_NOTICE_CHANNEL_ID}")
            return

        scanned = updated = failed = 0
        try:
            async for message in channel.history(limit=None, oldest_first=True):
                if not self.bot.user or message.author.id != self.bot.user.id or not message.embeds:
                    continue
                scanned += 1
                changed = False
                styled_embeds = []
                for embed in message.embeds:
                    if is_public_punishment_embed(embed):
                        styled = beautify_historical_notice(embed)
                        styled_embeds.append(styled)
                        changed = changed or styled.to_dict() != embed.to_dict()
                    else:
                        styled_embeds.append(embed)
                if not changed:
                    continue
                try:
                    await message.edit(embeds=styled_embeds)
                    updated += 1
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    failed += 1
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"[Punishment] notice-style-refresh-failed: {error}")
            return
        print(
            f"[Punishment] notice-style-refresh-complete: scanned={scanned} "
            f"updated={updated} failed={failed}"
        )

    def cog_unload(self):
        for session in self.evidence_sessions.values():
            task = session.get("task")
            if task:
                task.cancel()
        self.evidence_sessions.clear()
        if self._notice_refresh_task and not self._notice_refresh_task.done():
            self._notice_refresh_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.attachments:
            return

        key = self._session_key(message.author.id, message.channel.id)
        session = self.evidence_sessions.get(key)
        if not session:
            return

        now = discord.utils.utcnow()
        if now >= session["expires_at"]:
            self.evidence_sessions.pop(key, None)
            return

        if message.id in session["message_ids"]:
            return

        session["message_ids"].add(message.id)

        before_count = len(session["attachments"])
        for att in message.attachments:
            if att.url and any(saved.url == att.url for saved in session["attachments"]):
                continue

            try:
                try:
                    data = await att.read(use_cached=True)
                except discord.NotFound:
                    data = await att.read(use_cached=False)
            except (discord.NotFound, discord.HTTPException) as e:
                print(
                    f"[Punishment] evidence-attachment-read-failed: "
                    f"message={message.id} attachment={att.id} error={e}"
                )
                continue

            session["attachments"].append(CachedEvidenceAttachment(att, data))

        collected = len(session["attachments"]) - before_count
        if collected <= 0:
            return

        try:
            await message.reply(
                f"📎 已收纳 {collected} 个证据附件。可在处罚面板点击“完成收集”继续。",
                mention_author=False,
                delete_after=12,
            )
        except Exception:
            pass

    @discord.slash_command(name="处罚", description="打开管理面板 (可上传证据)")
    @is_super_egg()
    async def punishment_panel(
        self,
        ctx: discord.ApplicationContext,
    ):
        view = ManagementControlView(
            ctx,
            public_channel_id=PUBLIC_NOTICE_CHANNEL_ID,
            log_channel_id=LOG_CHANNEL_ID,
        )
        await ctx.respond(
            embed=discord.Embed(title="🛡️ 加载中...", color=STYLE["KIMI_YELLOW"]),
            view=view,
            ephemeral=True,
        )
        await view.refresh_view(ctx.interaction)

    @discord.message_command(name="⚡第三方快速处罚")
    @is_super_egg()
    async def third_party_quick_punishment(
        self,
        ctx: discord.ApplicationContext,
        message: discord.Message,
    ):
        await ctx.send_modal(ThirdPartyQuickPunishmentModal(self, message))

    async def _execute_third_party_quick_punishment(
        self,
        ctx: discord.Interaction,
        message: discord.Message,
        reason: str,
    ):
        guild = ctx.guild
        if not guild:
            return await ctx.followup.send("❌ 无法在私信中使用。", ephemeral=True)
        if message.author.bot:
            return await ctx.followup.send("❌ 不能处罚机器人消息。", ephemeral=True)

        target_id = message.author.id
        member = message.author if isinstance(message.author, discord.Member) else guild.get_member(target_id)
        if member is None:
            try:
                member = await guild.fetch_member(target_id)
            except (discord.NotFound, discord.HTTPException):
                return await ctx.followup.send("❌ 违规者已不在服务器内，无法执行标准处罚。", ephemeral=True)

        cached_attachments = []
        for attachment in message.attachments:
            try:
                try:
                    data = await attachment.read(use_cached=True)
                except discord.NotFound:
                    data = await attachment.read(use_cached=False)
                cached_attachments.append(CachedEvidenceAttachment(attachment, data))
            except (discord.NotFound, discord.HTTPException):
                continue

        action_results = []
        errors = []
        try:
            await member.timeout(
                discord.utils.utcnow() + datetime.timedelta(seconds=THIRD_PARTY_MUTE_SECONDS),
                reason=reason,
            )
            action_results.append("禁言一天")
        except (discord.Forbidden, discord.HTTPException) as error:
            errors.append(f"禁言失败：{error}")

        newbie_role = guild.get_role(int(NEWBIE_ROLE_ID)) if NEWBIE_ROLE_ID else None
        if newbie_role and newbie_role in member.roles:
            try:
                await member.remove_roles(newbie_role, reason=reason)
                action_results.append("已撤掉新兵蛋子身份组")
            except (discord.Forbidden, discord.HTTPException) as error:
                errors.append(f"撤身份组失败：{error}")
        elif newbie_role:
            action_results.append("未持有新兵蛋子身份组")
        else:
            errors.append("未配置新兵蛋子身份组")

        strike_count = db.add_strike(target_id)
        punishment_id = db.add_punishment_record(target_id, "third_party_quick", reason)
        action_results.append(f"警告一次（当前累计 {strike_count} 次）")

        public_msg = None
        public_channel = await ManagementControlView._resolve_sendable_channel(
            guild, PUBLIC_NOTICE_CHANNEL_ID
        )
        if public_channel:
            original_text = message.content or "（原消息无文字内容）"
            public_embed = build_public_notice_embed(
                action="第三方快速处罚",
                reason=reason,
            )
            public_embed.description += f"\n\n### 💬 违规消息原文\n{original_text}"
            public_embed.add_field(
                name="👤 违规成员",
                value=message.author.mention,
                inline=True,
            )
            public_embed.add_field(name="🏷️ 昵称", value=member.display_name, inline=True)
            public_embed.add_field(name="🆔 用户 ID", value=f"`{target_id}`", inline=False)
            public_embed.add_field(name="📁 处罚编号", value=f"`#{punishment_id:06d}`", inline=True)
            public_embed.add_field(name="⚖️ 处罚结果", value="\n".join(action_results), inline=False)
            public_embed.add_field(name="🔗 原始消息", value=f"[点击跳转]({message.jump_url})", inline=False)
            if errors:
                public_embed.add_field(name="⚠️ 执行异常", value="\n".join(errors), inline=False)
            public_embed.set_thumbnail(url=message.author.display_avatar.url)
            public_files = await self._evidence_files(cached_attachments, spoiler=False)
            try:
                public_msg = await public_channel.send(
                    embed=public_embed,
                    files=public_files,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException as error:
                errors.append(f"公示发送失败：{error}")

        dm_sent = await self.send_punishment_dm(
            guild=guild,
            target_id=target_id,
            action="third_party_quick",
            reason=reason,
            action_detail="禁言一天 + 撤掉新兵蛋子身份组 + 警告一次",
            evidences=cached_attachments,
            notice_url=public_msg.jump_url if public_msg else None,
            punishment_id=punishment_id,
        )

        log_channel = await ManagementControlView._resolve_sendable_channel(guild, LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(
                title="🛡️ 处罚执行记录・第三方快速处罚",
                description=f"### ⚠️ 执行原因\n> {reason}",
                color=LOG_COLOR,
                timestamp=discord.utils.utcnow(),
            )
            log_embed.add_field(name="执行人", value=ctx.user.mention, inline=True)
            log_embed.add_field(name="目标", value=message.author.mention, inline=True)
            log_embed.add_field(name="昵称", value=member.display_name, inline=True)
            log_embed.add_field(name="用户 ID", value=f"`{target_id}`", inline=False)
            log_embed.add_field(name="处罚编号", value=f"`#{punishment_id:06d}`", inline=True)
            log_embed.add_field(name="原始消息", value=f"[点击跳转]({message.jump_url})", inline=False)
            log_embed.add_field(name="执行结果", value="\n".join(action_results), inline=False)
            log_embed.add_field(name="私信通知", value="已发送" if dm_sent else "发送失败/私信关闭", inline=True)
            if errors:
                log_embed.add_field(name="执行异常", value="\n".join(errors), inline=False)
            log_view = discord.ui.View()
            if public_msg:
                log_view.add_item(discord.ui.Button(label="查看公示", url=public_msg.jump_url))
            try:
                await log_channel.send(
                    embed=log_embed,
                    view=log_view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass

        feedback = f"✅ 已对 {message.author.mention} 执行第三方快速处罚。"
        feedback += "\n📨 私信通知已发送。" if dm_sent else "\n⚠️ 私信通知发送失败（对方可能已关闭私信）。"
        if errors:
            feedback += "\n⚠️ " + "；".join(errors)
        await ctx.followup.send(feedback, ephemeral=True)

