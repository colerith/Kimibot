import re

import discord
from discord.ext import commands

import config
from cogs.manage.punishment_style import build_public_notice_embed
from cogs.points.storage import format_shells, modify_user_points
from cogs.shared.utils import is_super_egg

from .storage import (
    find_by_attachment_urls,
    find_by_message_id,
    get_submission,
    mark_meaningless_warning_issued,
    record_meaningless_withdrawal,
    recover_submission_from_embed_data,
)

from .views import (
    OwnerReplyView,
    RecommendationActionView,
    SubmissionPanelView,
    refresh_all_submission_panels,
    refresh_submission_main_panel,
)


WITHDRAWAL_REASON_TEMPLATES = {
    "repetitive": "投稿正文包含大量重复字符或重复片段，属于无意义灌水投稿。",
    "too_short": "投稿正文有效内容不足 15 个文字，且未提供可判断的具体信息。",
    "no_details": "投稿未说明具体对象、问题或推荐理由，内容缺少实际信息。",
    "irrelevant": "投稿内容与所选投稿类型或社区投稿范围无关。",
    "reward_abuse": "投稿存在明显凑字或批量刷取蛋壳奖励的行为。",
}


class WithdrawalReasonModal(discord.ui.Modal):
    def __init__(self, cog: "SubmissionsCog", message: discord.Message, default_reason: str = ""):
        super().__init__(title="🚫 确认撤回投稿")
        self.cog = cog
        self.message = message
        self.add_item(
            discord.ui.InputText(
                label="撤回理由",
                style=discord.InputTextStyle.paragraph,
                value=str(default_reason or "")[:500],
                placeholder="请填写会发送给投稿人的具体撤回理由",
                required=True,
                min_length=2,
                max_length=500,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        reason = str(self.children[0].value or "").strip()
        if len(reason) < 2:
            return await interaction.response.send_message("❌ 撤回理由至少需要 2 个文字。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.cog._execute_meaningless_withdrawal(interaction, self.message, reason)


class WithdrawalReasonSelect(discord.ui.Select):
    def __init__(self, parent_view: "WithdrawalReasonView"):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(
                label="重复字符 / 重复片段",
                value="repetitive",
                emoji="🔁",
                description="适用于截图中反复复制同一片段的水投稿",
            ),
            discord.SelectOption(
                label="有效内容不足 15 字",
                value="too_short",
                emoji="📏",
                description="正文过短或只有符号、表情",
            ),
            discord.SelectOption(
                label="未提供具体信息",
                value="no_details",
                emoji="📝",
                description="没有说明对象、问题或推荐理由",
            ),
            discord.SelectOption(
                label="投稿内容不相关",
                value="irrelevant",
                emoji="🧭",
                description="内容与投稿类型或社区范围无关",
            ),
            discord.SelectOption(
                label="疑似刷取蛋壳奖励",
                value="reward_abuse",
                emoji="🥚",
                description="存在批量凑字、刷奖励行为",
            ),
        ]
        super().__init__(
            placeholder="选择理由模板并打开弹窗",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        reason = WITHDRAWAL_REASON_TEMPLATES.get(self.values[0], "")
        await interaction.response.send_modal(
            WithdrawalReasonModal(self.parent_view.cog, self.parent_view.message, reason)
        )


class WithdrawalReasonView(discord.ui.View):
    def __init__(self, cog: "SubmissionsCog", message: discord.Message, owner_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.message = message
        self.owner_id = owner_id
        self.add_item(WithdrawalReasonSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ 这个撤回面板不属于你。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="自定义理由", emoji="✍️", style=discord.ButtonStyle.secondary)
    async def custom_reason(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(WithdrawalReasonModal(self.cog, self.message))


class SubmissionsCog(commands.Cog):
    """奇米蛋投稿面板。"""

    def __init__(self, bot):
        self.bot = bot
        self.submission_panels_refreshed = False

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
            main_panel_refreshed = await refresh_submission_main_panel(self.bot)
            result = await refresh_all_submission_panels(self.bot)
            print(
                f"[Submissions] main panel refreshed={main_panel_refreshed}; "
                f"refreshed {result['refreshed']} submission panels, skipped={result['skipped']}."
            )
        except Exception as e:
            print(f"[Submissions] submission-panel-refresh-failed: {e}")

    async def _find_submission_for_message(self, message: discord.Message) -> dict | None:
        # 上下文菜单的 resolved message 偶尔不带完整 embeds/attachments，重新抓取权威消息。
        try:
            message = await message.channel.fetch_message(message.id)
        except (AttributeError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        record = find_by_message_id(message.id)
        if record:
            return record

        for embed in message.embeds or []:
            footer_text = str(getattr(getattr(embed, "footer", None), "text", "") or "")
            match = re.search(r"投稿\s*#([0-9]+)", footer_text)
            if match:
                record = get_submission(match.group(1))
                if record:
                    return record

            if message.guild and message.author.id == self.bot.user.id:
                attachment_urls = [
                    str(getattr(attachment, "url", "") or "")
                    for attachment in (message.attachments or [])
                    if getattr(attachment, "url", None)
                ]
                record = recover_submission_from_embed_data(
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    message_id=message.id,
                    embed_data=embed.to_dict(),
                    attachment_urls=attachment_urls,
                )
                if record:
                    return record

        attachment_urls = []
        for attachment in message.attachments or []:
            attachment_urls.extend(
                url
                for url in (
                    getattr(attachment, "url", ""),
                    getattr(attachment, "proxy_url", ""),
                )
                if url
            )
        return find_by_attachment_urls(attachment_urls)

    async def _delete_submission_messages(self, message: discord.Message, record: dict) -> bool:
        """删除权威投稿消息，并兼容清理被右键选中的附件代理消息。"""
        canonical_id = int(record.get("message_id") or 0)
        canonical_channel_id = int(record.get("channel_id") or 0)
        canonical_deleted = False

        if canonical_id and canonical_channel_id:
            try:
                channel = self.bot.get_channel(canonical_channel_id) or await self.bot.fetch_channel(canonical_channel_id)
                canonical_message = await channel.fetch_message(canonical_id)
                await canonical_message.delete(reason=f"水投稿撤回 #{record['id']}")
                canonical_deleted = True
            except discord.NotFound:
                canonical_deleted = True
            except (discord.Forbidden, discord.HTTPException):
                canonical_deleted = False

        if message.id != canonical_id:
            try:
                await message.delete(reason=f"投稿附件随主投稿撤回 #{record['id']}")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        return canonical_deleted

    @staticmethod
    def _build_withdrawal_dm(
        *,
        guild: discord.Guild,
        user: discord.abc.User,
        submission_id: str,
        penalty: float,
        count: int,
        warning_triggered: bool,
        reason: str,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="🥚 小蛋投稿提醒・投稿已撤回",
            description=(
                f"你在 **{guild.name}** 的一条投稿被管理组判定为无意义灌水并撤回。\n\n"
                "### 📮 本次撤回理由\n"
                f"> {reason}"
            ),
            color=0xF0A24A,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="👤 投稿人", value=getattr(user, "mention", f"<@{user.id}>"), inline=True)
        embed.add_field(name="🧾 投稿 ID", value=f"`#{submission_id}`", inline=True)
        embed.add_field(name="🥚 扣回奖励", value=f"**-{format_shells(penalty)}** 蛋壳", inline=True)
        embed.add_field(name="🚫 投稿限制", value="今日禁止继续投稿（北京时间次日解除）", inline=False)
        embed.add_field(name="📌 水投稿累计", value=f"**{count}** 次", inline=True)
        embed.add_field(
            name="⚖️ 本次结果",
            value="已自动追加一次正式警告处罚" if warning_triggered else "本次为水投稿记录与私信提醒",
            inline=True,
        )
        embed.add_field(
            name="🌱 下次投稿前",
            value="请写明对象、问题/推荐理由和必要细节，正文至少 15 个有效文字。",
            inline=False,
        )
        if getattr(user, "display_avatar", None):
            embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="奇米蛋投稿管理中心 · 如有异议请通过社区工单联系管理组")
        return embed

    async def _send_warning_announcement(
        self,
        *,
        guild: discord.Guild,
        user: discord.abc.User,
        submission_id: str,
        count: int,
        penalty: float,
        punishment_result: dict,
        reason: str,
    ) -> bool:
        channel_id = int(config.IDS.get("PUBLIC_NOTICE_CHANNEL_ID", 0) or 0)
        channel = guild.get_channel(channel_id) or self.bot.get_channel(channel_id)
        if channel is None and channel_id:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        if channel is None:
            return False

        linked_action = punishment_result.get("linked_action") or "无"
        punishment_id = int(punishment_result.get("punishment_id", 0) or 0)
        strike = int(punishment_result.get("strike", 0) or 0)
        embed = build_public_notice_embed(
            action="水投稿累计警告",
            reason=f"累计 {count} 次提交无意义水投稿；本次撤回理由：{reason}",
        )
        embed.add_field(name="👤 被处罚人", value=getattr(user, "mention", f"<@{user.id}>"), inline=True)
        embed.add_field(name="🧾 处罚编号", value=f"`#{punishment_id:06d}`", inline=True)
        embed.add_field(name="📮 关联投稿", value=f"`#{submission_id}`", inline=False)
        embed.add_field(name="📌 水投稿累计", value=f"**{count}** 次", inline=True)
        embed.add_field(name="⚠️ 当前正式警告", value=f"**{strike}** 次", inline=True)
        embed.add_field(name="🥚 扣回奖励", value=f"**{format_shells(penalty)}** 蛋壳", inline=True)
        embed.add_field(name="⚙️ 自动处罚结果", value=str(linked_action)[:1024], inline=False)
        if getattr(user, "display_avatar", None):
            embed.set_thumbnail(url=user.display_avatar.url)
        try:
            await channel.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    @discord.message_command(name="🚫撤回投稿")
    @is_super_egg()
    async def withdraw_meaningless_submission(
        self,
        ctx: discord.ApplicationContext,
        message: discord.Message,
    ):
        """管理员右键选择理由并撤回机器人代发的无意义投稿。"""
        if not ctx.guild:
            return await ctx.respond("❌ 该指令只能在服务器中使用。", ephemeral=True)

        record = await self._find_submission_for_message(message)
        if not record or str(record.get("guild_id")) != str(ctx.guild.id):
            return await ctx.respond("❌ 这不是投稿系统发布的有效投稿消息。", ephemeral=True)
        if record.get("status") == "deleted":
            return await ctx.respond("ℹ️ 这条投稿已经撤回或删除。", ephemeral=True)

        await ctx.respond(
            "### 🚫 撤回投稿\n"
            "从下拉菜单选择常用理由，系统会打开已预填的弹窗供你修改；也可以点击“自定义理由”。",
            view=WithdrawalReasonView(self, message, ctx.user.id),
            ephemeral=True,
        )

    async def _execute_meaningless_withdrawal(
        self,
        ctx: discord.Interaction,
        message: discord.Message,
        reason: str,
    ):
        if not ctx.guild:
            return await ctx.followup.send("❌ 该指令只能在服务器中使用。", ephemeral=True)

        record = await self._find_submission_for_message(message)
        if not record or str(record.get("guild_id")) != str(ctx.guild.id):
            return await ctx.followup.send("❌ 这不是投稿系统发布的有效投稿消息。", ephemeral=True)

        reason = str(reason or "").strip()[:500]
        result = record_meaningless_withdrawal(str(record["id"]), ctx.user.id, reason)
        if not result:
            return await ctx.followup.send("❌ 投稿不存在或已经通过其他方式删除。", ephemeral=True)
        if result["duplicate"]:
            return await ctx.followup.send("ℹ️ 这条水投稿已经撤回并处理过了，不会重复扣款。", ephemeral=True)

        record = result["record"]
        author_id = int(record["author_id"])
        penalty = float(result["penalty"])
        count = int(result["count"])
        if penalty > 0:
            modify_user_points(
                author_id,
                -penalty,
                ctx.guild.id,
                source="submission_meaningless_withdrawal",
                reason=f"submission_id={record['id']};count={count};reason={reason}",
            )

        deleted = await self._delete_submission_messages(message, record)

        user = ctx.guild.get_member(author_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(author_id)
            except (discord.NotFound, discord.HTTPException):
                user = discord.Object(id=author_id)

        punishment_result = None
        announcement_sent = False
        if result["should_warn"]:
            punish_cog = self.bot.get_cog("处罚系统") or self.bot.get_cog("PunishmentCog")
            if punish_cog:
                punishment_result = await punish_cog._apply_single_action(
                    ctx.guild,
                    author_id,
                    "warn",
                    f"累计 {count} 次提交无意义水投稿（投稿 #{record['id']}）；本次理由：{reason}",
                    0,
                )
                if punishment_result.get("ok"):
                    threshold = max(1, int(config.SUBMISSIONS.get("MEANINGLESS_WARNING_THRESHOLD", 3)))
                    mark_meaningless_warning_issued(
                        guild_id=ctx.guild.id,
                        user_id=author_id,
                        warning_count=count // threshold,
                    )
                    announcement_sent = await self._send_warning_announcement(
                        guild=ctx.guild,
                        user=user,
                        submission_id=str(record["id"]),
                        count=count,
                        penalty=penalty,
                        punishment_result=punishment_result,
                        reason=reason,
                    )

        dm_sent = False
        if hasattr(user, "send"):
            try:
                await user.send(
                    embed=self._build_withdrawal_dm(
                        guild=ctx.guild,
                        user=user,
                        submission_id=str(record["id"]),
                        penalty=penalty,
                        count=count,
                        warning_triggered=bool(punishment_result and punishment_result.get("ok")),
                        reason=reason,
                    )
                )
                dm_sent = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        details = [
            f"✅ 已撤回投稿 `#{record['id']}`并扣回 **{format_shells(penalty)}** 蛋壳。",
            f"📝 撤回理由：{reason}",
            f"📌 该用户累计水投稿 **{count}** 次，今日已禁止继续投稿。",
            "💌 私信警告已发送。" if dm_sent else "⚠️ 用户关闭了私信，警告私信未送达。",
        ]
        if not deleted:
            details.append("⚠️ 投稿记录已撤回，但原消息删除失败，请检查机器人频道权限。")
        if result["should_warn"]:
            if punishment_result and punishment_result.get("ok"):
                details.append("⚖️ 已自动追加一次正式警告处罚。")
                details.append("📢 处罚结果已发到公告频道。" if announcement_sent else "⚠️ 正式警告已执行，但公告频道发送失败。")
            else:
                error = punishment_result.get("error", "找不到处罚模块") if punishment_result else "找不到处罚模块"
                details.append(f"⚠️ 达到自动警告阈值，但处罚执行失败：{error}")
        await ctx.followup.send("\n".join(details), ephemeral=True)
