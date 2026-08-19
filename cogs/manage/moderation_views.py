# cogs/manage/moderation_views.py

import discord
from discord import ui


ANNOUNCEMENT_COLOR = 0xFFD45A


def build_announcement_embed(
    interaction: discord.Interaction,
    title: str,
    content: str,
    *,
    hero_filename: str | None = None,
) -> discord.Embed:
    """构建统一的社区公告卡片。"""
    guild = interaction.guild
    guild_name = guild.name if guild else "奇米大王社区"
    guild_icon = guild.icon.url if guild and guild.icon else None

    embed = discord.Embed(
        title=f"📣｜{title.strip()}",
        description=content.strip(),
        color=ANNOUNCEMENT_COLOR,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(name=f"{guild_name} · 社区公告", icon_url=guild_icon)
    embed.set_footer(
        text=f"由 {interaction.user.display_name} 发布 · 请留意公告后续更新",
        icon_url=interaction.user.display_avatar.url,
    )

    if hero_filename:
        embed.set_image(url=f"attachment://{hero_filename}")

    return embed


class AnnouncementModal(ui.Modal):
    def __init__(
        self,
        channel: discord.TextChannel,
        mention_roles: list[discord.Role],
        mention_everyone: bool,
        attachments,
    ):
        super().__init__(title="📣 发布社区公告")
        self.channel = channel
        self.mention_roles = mention_roles
        self.mention_everyone = mention_everyone
        self.attachments = attachments

        self.add_item(
            ui.InputText(
                label="公告标题",
                placeholder="用一句话概括公告，例如：服务器维护通知",
                min_length=2,
                max_length=240,
                required=True,
            )
        )
        self.add_item(
            ui.InputText(
                label="公告正文",
                style=discord.InputTextStyle.paragraph,
                placeholder="填写公告详情，可使用 Discord Markdown 排版……",
                min_length=2,
                max_length=4000,
                required=True,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        title = self.children[0].value.strip()
        content = self.children[1].value.strip()

        # 去重，避免重复@同一个身份组
        unique_roles = list({role.id: role for role in self.mention_roles}.values())
        mention_parts = []
        if self.mention_everyone:
            mention_parts.append("@everyone")
        mention_parts.extend(role.mention for role in unique_roles)
        mention_content = " ".join(mention_parts)

        allowed_mentions = discord.AllowedMentions(
            everyone=self.mention_everyone,
            roles=unique_roles,
            users=False,
            replied_user=False,
        )

        try:
            files_to_send = [await attachment.to_file() for attachment in self.attachments]
            hero_filename = files_to_send[0].filename if files_to_send else None
            embed = build_announcement_embed(
                interaction,
                title,
                content,
                hero_filename=hero_filename,
            )
            await self.channel.send(
                content=mention_content,
                embed=embed,
                files=files_to_send,
                allowed_mentions=allowed_mentions,
            )
            await interaction.followup.send(
                f"✅ 公告已发布到 {self.channel.mention}",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 公告发布失败：{e}", ephemeral=True)
