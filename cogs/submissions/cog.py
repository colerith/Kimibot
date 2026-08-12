import asyncio
import datetime
import io

import discord
from discord.ext import commands

from .views import (
    OwnerReplyView,
    RecommendationActionView,
    SubmissionPanelView,
    refresh_all_submission_panels,
)


class CachedSubmissionAttachment:
    def __init__(self, attachment: discord.Attachment, data: bytes):
        self.url = attachment.url
        self.proxy_url = getattr(attachment, "proxy_url", None)
        self.filename = attachment.filename
        self.content_type = getattr(attachment, "content_type", None)
        self.size = getattr(attachment, "size", len(data))
        self._data = data

    async def to_file(self, *, spoiler: bool = False):
        return discord.File(io.BytesIO(self._data), filename=self.filename, spoiler=spoiler)


class SubmissionsCog(commands.Cog):
    """奇米蛋投稿面板。"""

    def __init__(self, bot):
        self.bot = bot
        self.attachment_sessions = {}
        self.submission_panels_refreshed = False

    def _session_key(self, user_id: int, channel_id: int):
        return (user_id, channel_id)

    def get_attachment_session(self, user_id: int, channel_id: int):
        return self.attachment_sessions.get(self._session_key(user_id, channel_id))

    async def _expire_attachment_session(self, user_id: int, channel_id: int, expires_at: datetime.datetime):
        delay = max((expires_at - discord.utils.utcnow()).total_seconds(), 0)
        try:
            await asyncio.sleep(delay)
            key = self._session_key(user_id, channel_id)
            session = self.attachment_sessions.get(key)
            if not session or session["expires_at"] != expires_at:
                return
            self.attachment_sessions.pop(key, None)
            print(
                f"[Submissions] attachment-session-expired: user={user_id} channel={channel_id} attachments={len(session['attachments'])}"
            )
        except asyncio.CancelledError:
            pass

    def start_attachment_session(self, user_id: int, channel_id: int, *, max_attachments: int = 9, duration_seconds: int = 300):
        key = self._session_key(user_id, channel_id)
        old = self.attachment_sessions.pop(key, None)
        if old and old.get("task"):
            old["task"].cancel()

        expires_at = discord.utils.utcnow() + datetime.timedelta(seconds=duration_seconds)
        task = self.bot.loop.create_task(self._expire_attachment_session(user_id, channel_id, expires_at))
        self.attachment_sessions[key] = {
            "attachments": [],
            "message_ids": set(),
            "expires_at": expires_at,
            "task": task,
            "max_attachments": max_attachments,
        }
        return expires_at

    async def finish_attachment_session(
        self,
        user_id: int,
        channel_id: int,
        cleanup_channel: discord.abc.Messageable | None = None,
    ):
        key = self._session_key(user_id, channel_id)
        session = self.attachment_sessions.pop(key, None)
        if not session:
            return None
        if session.get("task"):
            session["task"].cancel()

        deleted = 0
        failed = 0
        if cleanup_channel and session["message_ids"]:
            for message_id in session["message_ids"]:
                try:
                    partial = cleanup_channel.get_partial_message(message_id)
                    await partial.delete(reason="投稿附件收集完成后自动清理原消息")
                    deleted += 1
                except (AttributeError, discord.Forbidden, discord.NotFound, discord.HTTPException):
                    failed += 1

        return {
            "attachments": list(session["attachments"]),
            "deleted_messages": deleted,
            "failed_deletions": failed,
        }

    def cancel_attachment_session(self, user_id: int, channel_id: int):
        key = self._session_key(user_id, channel_id)
        session = self.attachment_sessions.pop(key, None)
        if not session:
            return 0
        if session.get("task"):
            session["task"].cancel()
        return len(session["attachments"])

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(SubmissionPanelView())
        self.bot.add_view(OwnerReplyView())
        self.bot.add_view(RecommendationActionView())
        print("[Submissions] Cog loaded and persistent views registered.")
        self.bot.loop.create_task(self._refresh_submission_panels_on_ready())

    async def _refresh_submission_panels_on_ready(self):
        if self.submission_panels_refreshed:
            return
        self.submission_panels_refreshed = True
        await self.bot.wait_until_ready()
        try:
            result = await refresh_all_submission_panels(self.bot)
            print(
                f"[Submissions] refreshed {result['refreshed']} submission panels, skipped={result['skipped']}."
            )
        except Exception as e:
            print(f"[Submissions] submission-panel-refresh-failed: {e}")

    def cog_unload(self):
        for session in self.attachment_sessions.values():
            task = session.get("task")
            if task:
                task.cancel()
        self.attachment_sessions.clear()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.attachments:
            return

        key = self._session_key(message.author.id, message.channel.id)
        session = self.attachment_sessions.get(key)
        if not session:
            return

        now = discord.utils.utcnow()
        if now >= session["expires_at"]:
            self.attachment_sessions.pop(key, None)
            return

        if message.id in session["message_ids"]:
            return

        session["message_ids"].add(message.id)
        before_count = len(session["attachments"])
        max_attachments = int(session.get("max_attachments", 9) or 9)

        for att in message.attachments:
            if len(session["attachments"]) >= max_attachments:
                break
            if att.url and any(saved.url == att.url for saved in session["attachments"]):
                continue
            try:
                try:
                    data = await att.read(use_cached=True)
                except discord.NotFound:
                    data = await att.read(use_cached=False)
            except (discord.NotFound, discord.HTTPException) as e:
                print(
                    f"[Submissions] attachment-read-failed: message={message.id} attachment={att.id} error={e}"
                )
                continue
            session["attachments"].append(CachedSubmissionAttachment(att, data))

        collected = len(session["attachments"]) - before_count
        if collected <= 0:
            return

        try:
            await message.reply(
                f"📎 已收纳 {collected} 个投稿附件，目前共 {len(session['attachments'])}/{max_attachments} 个。收齐后回到投稿确认面板点“完成投稿”。",
                mention_author=False,
                delete_after=12,
            )
        except Exception:
            pass
