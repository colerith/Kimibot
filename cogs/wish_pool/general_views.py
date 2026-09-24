import asyncio
import datetime
import random

import discord

from config import SERVER_OWNER_ID, STYLE, WISH_CHANNEL_ID


GENERAL_PANEL_MARKER = "奇米大王的许愿池"


def build_general_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✨ 奇米大王的许愿池",
        description=(
            "有什么想要的电波系实现的预设新功能，或者对社区的建议吗？\n\n"
            "**点击下方的菜单选择你的愿望类型，然后告诉本大王吧！**"
        ),
        color=STYLE["KIMI_YELLOW"],
    )
    embed.set_footer(text="通用许愿池 · 可匿名投稿")
    return embed


class DetailedWishModal(discord.ui.Modal):
    def __init__(self, wish_type: str):
        title = f"📝 许愿: {wish_type}"
        super().__init__(title=title if len(title) <= 45 else title[:42] + "...")
        self.wish_type = wish_type
        self.add_item(discord.ui.InputText(
            label="详细描述你的愿望/建议",
            placeholder=f"关于【{wish_type}】的想法...",
            style=discord.InputTextStyle.paragraph,
            min_length=5,
            max_length=2000,
            required=True,
        ))
        self.add_item(discord.ui.InputText(
            label="是否匿名？(填 是/否)",
            placeholder="默认匿名。填“否”则公开许愿者身份。",
            style=discord.InputTextStyle.short,
            required=False,
            max_length=1,
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        content = self.children[0].value.strip()
        anonymous_value = (self.children[1].value or "").strip().lower()
        is_anonymous = anonymous_value not in {"否", "n"}

        channel = interaction.client.get_channel(int(WISH_CHANNEL_ID))
        if channel is None:
            try:
                channel = await interaction.client.fetch_channel(int(WISH_CHANNEL_ID))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return await interaction.followup.send("找不到通用许愿池频道，请联系管理组。", ephemeral=True)

        wish_id = random.randint(100000, 999999)
        safe_type = self.wish_type.replace(" ", "")
        try:
            thread = await channel.create_thread(
                name=f"💌-{safe_type}-{wish_id}",
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            await thread.add_user(interaction.user)
            try:
                owner = await interaction.client.fetch_user(int(SERVER_OWNER_ID))
                await thread.add_user(owner)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            embed = discord.Embed(
                title="💌 收到了一个新愿望！",
                description=f"**类型：** {self.wish_type}\n\n**内容：**\n```{content}```",
                color=STYLE["KIMI_YELLOW"],
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            embed.add_field(name="处理状态", value="⏳ 待受理", inline=False)
            if is_anonymous:
                embed.set_footer(text="来自一位匿名小饱饱")
            else:
                embed.set_author(
                    name=f"来自 {interaction.user.display_name}",
                    icon_url=interaction.user.display_avatar.url,
                )
            await thread.send(embed=embed, view=WishActionView())
            await interaction.followup.send(f"愿望已发送！快去 {thread.mention} 看看吧！", ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as error:
            await interaction.followup.send(
                f"创建许愿子区失败，请联系管理组。`{type(error).__name__}`",
                ephemeral=True,
            )


class WishActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == int(SERVER_OWNER_ID):
            return True
        await interaction.response.send_message("只有服主大人能操作哦！", ephemeral=True)
        return False

    async def update_status(self, interaction: discord.Interaction, status: str, close: bool = False):
        if not interaction.message.embeds:
            return await interaction.response.send_message("愿望卡片不存在。", ephemeral=True)
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="处理状态", value=status, inline=False)
        if close:
            for child in self.children:
                child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        if close:
            await interaction.channel.send(f"已标记为 **{status}**，10 秒后锁定本子区。")
            await asyncio.sleep(10)
            await interaction.channel.edit(archived=True, locked=True)

    @discord.ui.button(label="受理", emoji="✅", style=discord.ButtonStyle.success, custom_id="wish_accept")
    async def accept(self, button, interaction: discord.Interaction):
        await self.update_status(interaction, "✅ 已受理")

    @discord.ui.button(label="暂不考虑", emoji="🤔", style=discord.ButtonStyle.secondary, custom_id="wish_reject")
    async def reject(self, button, interaction: discord.Interaction):
        await self.update_status(interaction, "🤔 暂不考虑", True)

    @discord.ui.button(label="已实现", emoji="🎉", style=discord.ButtonStyle.primary, custom_id="wish_done")
    async def done(self, button, interaction: discord.Interaction):
        await self.update_status(interaction, "🎉 已实现！", True)


class PresetFeatureView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="极光", emoji="🌌", style=discord.ButtonStyle.primary)
    async def aurora(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(DetailedWishModal("预设功能-极光"))

    @discord.ui.button(label="象牙塔", emoji="🏛️", style=discord.ButtonStyle.secondary)
    async def ivory(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(DetailedWishModal("预设功能-象牙塔"))

    @discord.ui.button(label="日月西", emoji="⚖️", style=discord.ButtonStyle.secondary)
    async def sun_moon_west(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(DetailedWishModal("预设功能-日月西"))


class WishSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="👇 选择愿望类型...",
            min_values=1,
            max_values=1,
            custom_id="wish_panel_select",
            options=[
                discord.SelectOption(label="预设新功能", emoji="💡", value="preset_feature"),
                discord.SelectOption(label="社区建设", emoji="🏗️", value="社区建设"),
                discord.SelectOption(label="其他", emoji="💭", value="其他"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "preset_feature":
            await interaction.response.send_message("请选择功能：", view=PresetFeatureView(), ephemeral=True)
        else:
            await interaction.response.send_modal(DetailedWishModal(self.values[0]))


class GeneralWishPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WishSelect())
