import asyncio

import discord
from discord.ext import commands

import config
from cogs.points.storage import grant_monthly_eligible_reward

from .storage import claim_reply_reward, find_question_by_message, list_panels, remove_panel, revoke_reply_reward
from .views import EggQAEntryView, EggQAPanelView, deploy_egg_qa_panel, refresh_bottom_egg_qa_panel


REWARD_NUMBER_EMOJIS = {
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


def _reward_reactions(amount: int) -> list[str]:
    """用 Discord 数字反应表达 3～15；11～15 表示为 10 加余数。"""
    if amount <= 10:
        emoji = REWARD_NUMBER_EMOJIS.get(amount)
        return [emoji] if emoji else []
    remainder = amount - 10
    return [REWARD_NUMBER_EMOJIS[10], REWARD_NUMBER_EMOJIS[remainder]]


class EggQACog(commands.Cog, name="小蛋问答"):
    def __init__(self, bot):
        self.bot = bot
        self.panels_refreshed = False
        self.bottom_refresh_task = None
        self.bottom_refresh_lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(EggQAPanelView())
        self.bot.add_view(EggQAEntryView())
        print("[EggQA] Cog loaded and persistent view registered.")
        if not self.panels_refreshed:
            self.panels_refreshed = True
            self.bot.loop.create_task(self._refresh_saved_panels())

    def cog_unload(self):
        if self.bottom_refresh_task:
            self.bottom_refresh_task.cancel()

    def _bottom_channel_id(self) -> int:
        cfg = getattr(config, "EGG_QA", {})
        return int(cfg.get("BOTTOM_PANEL_CHANNEL_ID", 0) or 0) if isinstance(cfg, dict) else 0

    async def _fetch_channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel:
            return channel
        try:
            return await self.bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _refresh_saved_panels(self):
        await self.bot.wait_until_ready()
        refreshed = 0
        saved_panels = await asyncio.to_thread(list_panels)
        for panel in saved_panels:
            channel_id = int(panel.get("channel_id") or 0)
            message_id = int(panel.get("message_id") or 0)
            if not channel_id or not message_id:
                continue
            channel = await self._fetch_channel(channel_id)
            if not channel:
                continue
            try:
                await deploy_egg_qa_panel(channel)
                refreshed += 1
            except discord.NotFound:
                await asyncio.to_thread(remove_panel, channel_id, message_id)
            except (discord.Forbidden, discord.HTTPException):
                continue

        bottom_channel_id = self._bottom_channel_id()
        if bottom_channel_id and not any(
            int(panel.get("channel_id") or 0) == bottom_channel_id for panel in saved_panels
        ):
            channel = await self._fetch_channel(bottom_channel_id)
            if channel:
                try:
                    await deploy_egg_qa_panel(channel)
                    refreshed += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass
        print(f"[EggQA] refreshed {refreshed} saved panels.")

    async def _delayed_bottom_refresh(self):
        try:
            await asyncio.sleep(1.5)
            async with self.bottom_refresh_lock:
                channel = await self._fetch_channel(self._bottom_channel_id())
                if channel:
                    await refresh_bottom_egg_qa_panel(channel)
        except asyncio.CancelledError:
            pass
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"[EggQA] bottom panel refresh failed: {error}")

    def _schedule_bottom_refresh(self):
        if self.bottom_refresh_task and not self.bottom_refresh_task.done():
            return
        self.bottom_refresh_task = self.bot.loop.create_task(self._delayed_bottom_refresh())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return

        if not message.author.bot and message.channel.id == self._bottom_channel_id():
            self._schedule_bottom_refresh()

        if message.author.bot or not message.reference:
            return
        if not message.content.strip() and not message.attachments:
            return

        referenced_id = message.reference.message_id
        if not referenced_id:
            return
        question = await asyncio.to_thread(find_question_by_message, referenced_id)
        if not question:
            return
        if question.get("guild_id") != str(message.guild.id):
            return
        if question.get("channel_id") != str(message.channel.id):
            return
        is_self_answer = question.get("author_id") == str(message.author.id)

        reward = await asyncio.to_thread(
            claim_reply_reward,
            question_id=question["id"],
            user_id=message.author.id,
            reply_message_id=message.id,
            is_self_answer=is_self_answer,
        )
        if not reward:
            return

        amount = int(reward["amount"])
        try:
            credited = await asyncio.to_thread(
                grant_monthly_eligible_reward,
                message.author.id,
                message.guild.id,
                amount,
                source="egg_qa_self_reply" if is_self_answer else "egg_qa_reply",
                reason=(
                    f"question_id={question['id']};reply_message_id={message.id};"
                    f"self_answer={str(is_self_answer).lower()}"
                ),
            )
            monthly_bonus = float(credited.get("monthly_bonus", 0) or 0)
            if monthly_bonus > 0:
                print(
                    f"[EggQA] monthly card bonus: user={message.author.id} reply={message.id} "
                    f"base={amount} bonus={monthly_bonus} total={credited.get('amount')}"
                )
        except Exception as error:
            await asyncio.to_thread(
                revoke_reply_reward,
                question_id=question["id"],
                user_id=message.author.id,
                reply_message_id=message.id,
            )
            print(f"[EggQA] reward failed: reply={message.id} error={error}")
            return

        for emoji in _reward_reactions(amount):
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                pass
