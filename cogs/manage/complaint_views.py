import discord
from discord import ui

from config import IDS

DEFAULT_NOTICE = (
    "1. 受理范围：本社区相关 & 跨平台「商业化红线」\n"
    "原则上，本社区仅受理发生在**社区内**的违规行为，不处理社区外的争议，请勿引入外部社区纠纷。\n"
    "**__【红线特例】__**\n"
    "若本社区成员在其他平台涉及商业化行为（如贩卖/倒卖 API、利用 SillyTavern 进行商业盈利等），此为最高红线。\n"
    "只要证据确凿，一律受理并直接予以封禁。\n\n"
    "2. 提供完整、详细的证据链\n"
    "若需投诉，请**务必**提供详细说明与直接截图证据\n"
    "__尤其是跨平台商业化举报，需提供明确的交易或引流实锤__\n"
    "管理组无法跨平台为您进行“调查取证”\n\n"
    "3. 证据不足将直接驳回\n"
    "若投诉仅有模糊描述、无上下文的截图内容，或单纯要求自行核实，管理组将认定为“证据不足”关闭工单，不再另行通知。\n\n"
    "4. 请附上对方的 Discord 个人资料\n"
    "为防同名混淆，请务必附上被投诉人完整的 Discord 个人资料截图。\n\n"
    "**请如实填写投诉信息，恶意或滥用举报可能面临处罚。**\n"
    "**投诉内容仅管理组可见。**"
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
        super().__init__(title="✒️ 编辑投诉面板文案")
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
