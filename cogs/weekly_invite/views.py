import asyncio
import discord
from discord import ui
from . import storage as store
from .cog import public_panel


class InviteAdminView(ui.View):
    def __init__(self, cog, user_id, guild_id, parent=None):
        super().__init__(timeout=600)
        self.cog, self.user_id, self.guild_id, self.parent = cog, user_id, guild_id, parent
        self.state = {}

    async def allowed(self, interaction):
        ok = (interaction.guild_id == self.guild_id and interaction.user.id == self.user_id and
              (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator))
        if not ok:
            await interaction.response.send_message('仅打开管理台的管理员 / 服主可操作。', ephemeral=True)
        return ok

    async def interaction_check(self, interaction):
        return await self.allowed(interaction)

    async def embed(self):
        channel = await self.cog.channel()
        if channel.guild.id != self.guild_id:
            raise ValueError('邀请面板不属于当前服务器。')
        self.state = await asyncio.to_thread(store.load)
        invite = store.active_invite(self.state)
        pauses = '\n'.join(f'{start} ~ {end}' for start, end in self.state['pauses']) or '尚未设置，请按实际寒暑假日期配置。'
        embed = discord.Embed(title='🌱 定期邀请 · 管理台', color=0xB8C9C1,
            description=f'发送位置：<#{store.CHANNEL_ID}>\n**北京时间**每周一 00:00 创建，周六 00:00 失效。\n'
            '恢复上线时可在本周开放时段补建，截止时间不顺延。')
        embed.add_field(name='自动发布', value='已开启' if self.state['enabled'] else '已撤销 / 停止')
        embed.add_field(name='目前允许创建', value='是' if store.creation_allowed(self.state) else '否（周末、暂停区间或已撤销）')
        embed.add_field(name='当前链接', value=invite['url'] if invite else '暂无有效链接', inline=False)
        embed.add_field(name='停止创建区间（含起止日期）', value=pauses, inline=False)
        embed.add_field(name='操作说明', value='发送 / 恢复会发布或刷新面板，仍遵守周末及暂停区间。撤销会使当前链接失效并移除面板，自动发布也会停止。暂停区间只阻止新链接，不提前撤销现有链接。', inline=False)
        return embed

    async def refresh(self, interaction):
        await interaction.edit_original_response(embed=await self.embed(), view=self)

    async def run(self, interaction, **kwargs):
        try:
            await self.cog.manage(**kwargs)
            text = '✅ 操作已完成。'
        except Exception as error:
            text = f'操作暂未全部完成，已保存的设置会由后台重试。请检查频道权限。错误：{type(error).__name__}'
        await self.refresh(interaction)
        await interaction.followup.send(text, ephemeral=True)

    @ui.button(label='发送 / 恢复面板', emoji='📨', style=discord.ButtonStyle.success)
    async def send(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        await self.run(interaction, send=True)

    @ui.button(label='撤销面板与链接', emoji='🛑', style=discord.ButtonStyle.danger)
    async def revoke(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        await self.run(interaction, revoke=True)

    @ui.button(label='编辑文案', emoji='📝')
    async def copy(self, button, interaction):
        await interaction.response.send_modal(InviteCopyModal(self))

    @ui.button(label='设置停止创建区间', emoji='📅', row=1)
    async def pauses(self, button, interaction):
        await interaction.response.send_modal(PausesModal(self))

    @ui.button(label='刷新状态', emoji='🔄', row=1)
    async def status(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        await self.refresh(interaction)

    @ui.button(label='预览文案', emoji='👀', row=1)
    async def preview(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        embed, _ = public_panel(await asyncio.to_thread(store.load))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label='返回社区管理', emoji='↩️', row=1)
    async def back(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        from cogs.roles.views import build_community_manage_embed
        await interaction.edit_original_response(embed=build_community_manage_embed(interaction.guild), view=self.parent)


class InviteCopyModal(ui.Modal):
    def __init__(self, panel):
        super().__init__(title='定期邀请 · 面板文案')
        self.panel = panel
        self.heading = ui.InputText(label='面板标题', value=panel.state['title'], max_length=256)
        self.body = ui.InputText(label='邀请说明（具体截止时间由系统追加）', value=panel.state['copy'],
                                 style=discord.InputTextStyle.paragraph, max_length=3000)
        self.add_item(self.heading)
        self.add_item(self.body)

    async def callback(self, interaction):
        if not await self.panel.allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not self.heading.value.strip() or not self.body.value.strip():
            return await interaction.followup.send('标题和说明不能为空。', ephemeral=True)
        await self.panel.run(interaction, changes={'title': self.heading.value, 'copy': self.body.value})


class PausesModal(ui.Modal):
    def __init__(self, panel):
        super().__init__(title='定期邀请 · 停止创建区间')
        self.panel = panel
        self.dates = ui.InputText(label='每行：YYYY-MM-DD ~ YYYY-MM-DD',
            value='\n'.join(f'{start} ~ {end}' for start, end in panel.state['pauses']),
            placeholder='含起止日期，均为北京时间；填写“清空”可移除所有区间。',
            style=discord.InputTextStyle.paragraph, required=True, max_length=1000)
        self.add_item(self.dates)

    async def callback(self, interaction):
        if not await self.panel.allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            pauses = store.parse_pauses('' if self.dates.value.strip() == '清空' else self.dates.value)
        except ValueError as error:
            return await interaction.followup.send(str(error), ephemeral=True)
        await self.panel.run(interaction, changes={'pauses': pauses})
