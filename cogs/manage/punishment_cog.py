# cogs/manage/punishment_cog.py

import datetime
import asyncio

import discord
from discord.ext import commands

from config import IDS, STYLE
from .punishment_db import db
from .punishment_views import ManagementControlView
from ..shared.utils import is_super_egg

PUBLIC_NOTICE_CHANNEL_ID = IDS.get("PUBLIC_NOTICE_CHANNEL_ID")
LOG_CHANNEL_ID = IDS.get("LOG_CHANNEL_ID", 1468508677144055818)


class PunishmentCog(commands.Cog, name="处罚系统"):
    def __init__(self, bot):
        self.bot = bot
        self.persistent_view = None
        self.evidence_sessions = {}

    def _session_key(self, user_id: int, channel_id: int):
        return (user_id, channel_id)

    def get_evidence_session(self, user_id: int, channel_id: int):
        return self.evidence_sessions.get(self._session_key(user_id, channel_id))

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

    def finish_evidence_session(self, user_id: int, channel_id: int):
        key = self._session_key(user_id, channel_id)
        session = self.evidence_sessions.pop(key, None)
        if not session:
            return []
        if session.get("task"):
            session["task"].cancel()
        return list(session["attachments"])

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

        try:
            if action == "warn":
                if not member:
                    raise ValueError("用户不在服务器内，无法执行警告")

                if member:
                    try:
                        dm_embed = discord.Embed(
                            title=f"⚠️ {guild.name} 社区警告",
                            description=f"**理由:** {reason}",
                            color=0xFFAA00,
                        )
                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        pass

                strike = db.add_strike(target_id)
                linked_action = "无"
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

                return {
                    "ok": True,
                    "target_id": target_id,
                    "member": member,
                    "strike": strike,
                    "linked_action": linked_action,
                }

            elif action == "unwarn":
                strike = db.remove_strike(target_id)
                return {
                    "ok": True,
                    "target_id": target_id,
                    "member": member,
                    "strike": strike,
                    "linked_action": "仅撤销累计，不自动反向解除处罚",
                }

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

            return {
                "ok": True,
                "target_id": target_id,
                "member": member,
                "strike": strike,
                "linked_action": "",
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

        print("[Punishment] Cog loaded and view registered (if persistent).")

    def cog_unload(self):
        for session in self.evidence_sessions.values():
            task = session.get("task")
            if task:
                task.cancel()
        self.evidence_sessions.clear()

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
            session["attachments"].append(att)

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

