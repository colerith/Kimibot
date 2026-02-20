# cogs/manage/moderation_views.py

import discord
from discord import ui

class AnnouncementModal(ui.Modal):
    def __init__(self, channel: discord.TextChannel, mention_role, attachments):
        super().__init__(title="📢 编辑公告内容")
        self.channel = channel
        self.mention_role = mention_role
        self.attachments = attachments

        self.add_item(ui.InputText(label="公告标题", placeholder="例如：服务器维护通知", required=True))
        self.add_item(ui.InputText(label="公告正文", style=discord.InputTextStyle.paragraph, placeholder="请在此处输入详细内容...", required=True))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        title = self.children[0].value
        content = self.children[1].value

        embed = discord.Embed(title=f"📢 {title}", description=content, color=0xFFD700)
        embed.set_footer(text=f"由 {interaction.user.display_name} 发布")
        embed.timestamp = discord.utils.utcnow()

        files_to_send = [await f.to_file() for f in self.attachments]

        mention_content = self.mention_role.mention if self.mention_role else ""

        try:
            await self.channel.send(content=mention_content, embed=embed, files=files_to_send)
            await interaction.followup.send("✅ 公告已成功发送！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 发送失败: {e}", ephemeral=True)