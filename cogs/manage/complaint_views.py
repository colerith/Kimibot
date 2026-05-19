import discord
from discord import ui

from config import IDS

DEFAULT_NOTICE = (
    "### ⚠️ 投诉须知\n\n"
    "1. 请提供清晰且完整的证据链（时间线、截图、原始上下文）。\n"
    "2. 举报内容需真实，恶意举报将按规则处理。\n"
    "3. 工单仅管理可见，请勿在公开频道扩散个人隐私。\n"
    "4. 建议附上对方 Discord 资料页截图，避免同名误判。\n"
)

PANEL_BUTTON_ID = "manage:complaint:create"


def build_complaint_panel_embed(notice_text: str) -> discord.Embed:
    embed = discord.Embed(
        title="📮 投诉中心",
        description="如果你需要举报违规行为，请点击下方按钮提交投诉。",
        color=0x4DA3FF,
    )
    embed.add_field(name="注意事项", value=notice_text, inline=False)
    embed.set_footer(text="投诉内容仅管理组可见")
    return embed


class ComplaintSubmitModal(ui.Modal):
    def __init__(self):
        super().__init__(title="📝 提交投诉")
        self.add_item(
            ui.InputText(
                label="投诉内容",
                style=discord.InputTextStyle.paragraph,
                placeholder="请描述违规行为、发生时间、涉及人员与关键信息...",
                required=True,
                max_length=2000,
            )
        )
        self.add_item(
            ui.InputText(
                label="补充信息（可填ID/链接）",
                style=discord.InputTextStyle.paragraph,
                required=False,
                max_length=1000,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.followup.send("❌ 仅支持在文字频道投诉面板中使用。", ephemeral=True)

        content = self.children[0].value.strip()
        extra = self.children[1].value.strip() if self.children[1].value else ""

        try:
            thread = await interaction.channel.create_thread(
                name=f"🎫 {interaction.user.display_name} 的投诉",
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason=f"投诉创建 by {interaction.user}",
            )
        except Exception as e:
            return await interaction.followup.send(f"❌ 创建投诉工单失败: {e}", ephemeral=True)

        detail_embed = discord.Embed(title="📌 投诉详情", color=0xF5A623)
        detail_embed.add_field(name="投诉人", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
        detail_embed.add_field(name="工单号", value=f"`{thread.id}`", inline=True)
        detail_embed.add_field(name="投诉内容", value=content, inline=False)
        if extra:
            detail_embed.add_field(name="补充信息", value=extra[:1024], inline=False)
        detail_embed.timestamp = discord.utils.utcnow()

        await thread.send(embed=detail_embed, allowed_mentions=discord.AllowedMentions.none())

        manage_role_id = IDS.get("SUPER_EGG_ROLE_ID")
        if manage_role_id:
            await thread.send(
                content=f"<@&{manage_role_id}> 有新投诉工单，请尽快处理。",
                allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),
            )

        jump_view = ui.View()
        jump_view.add_item(ui.Button(label="前往工单", url=thread.jump_url, style=discord.ButtonStyle.link))
        await interaction.followup.send("✅ 投诉已提交，管理组会尽快处理。", view=jump_view, ephemeral=True)


class ComplaintPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="提交投诉",
        emoji="📩",
        style=discord.ButtonStyle.primary,
        custom_id=PANEL_BUTTON_ID,
    )
    async def create_ticket(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(ComplaintSubmitModal())


class EditComplaintNoticeModal(ui.Modal):
    def __init__(self, cog, panel_message: discord.Message, current_notice: str):
        super().__init__(title="📝 编辑投诉面板文案")
        self.cog = cog
        self.panel_message = panel_message
        self.add_item(
            ui.InputText(
                label="投诉须知文案",
                style=discord.InputTextStyle.paragraph,
                default=current_notice,
                required=True,
                max_length=2000,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_notice = self.children[0].value.strip()
        if not new_notice:
            return await interaction.followup.send("❌ 文案不能为空。", ephemeral=True)

        self.cog.set_notice_for_message(self.panel_message.id, new_notice)
        await self.cog.refresh_panel_message(self.panel_message, new_notice)
        await interaction.followup.send("✅ 投诉面板文案已更新。", ephemeral=True)
