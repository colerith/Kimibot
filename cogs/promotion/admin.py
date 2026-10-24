"""Community management's promotion configuration, preview and review statistics."""
import asyncio
import discord
from discord import ui
from . import storage as store
from .views import DEFAULT_COPY, entry_embed


class PromotionAdminView(ui.View):
    def __init__(self, cog, owner_id, guild_id, parent=None):
        super().__init__(timeout=600)
        self.cog, self.owner_id, self.guild_id, self.parent = cog, owner_id, guild_id, parent
        self.cfg = {}

    async def allowed(self, interaction):
        allowed = (interaction.guild_id == self.guild_id and interaction.user.id == self.owner_id
                   and store.is_staff(interaction.user))
        if not allowed:
            await interaction.response.send_message('仅打开此管理台的管理员 / 服主可操作。', ephemeral=True)
        return allowed

    async def interaction_check(self, interaction):
        return await self.allowed(interaction)

    async def embed(self):
        self.cfg, stats = await asyncio.gather(asyncio.to_thread(store.settings),
                                             asyncio.to_thread(store.statistics, self.guild_id))
        channel = await self.cog.channel(self.cfg['channel_id'])
        if channel.guild.id != self.guild_id:
            raise ValueError('小蛋晋升配置属于另一个服务器，无法从这里修改。')
        embed = discord.Embed(title='🐣 小蛋晋升 · 管理控制台', color=0xEBCB8B,
            description=f'申请与入口：<#{self.cfg["channel_id"]}>\n审批记录：<#{self.cfg["log_channel_id"]}>\n'
                        '编辑后保留当前管理台。文案编辑只修改展示文字，权益和审核规则保持原设置。')
        def summary(counts):
            return (f'总计 **{sum(counts.values())}** · 待投递 **{counts["publishing"]}** · 待审 **{counts["pending"]}**\n'
                    f'发放中 **{counts["granting"]}** · 通过 **{counts["approved"]}** · 驳回 **{counts["rejected"]}**')
        embed.add_field(name=f'今日正式申请 · {store.today()}', value=summary(stats['today']), inline=False)
        embed.add_field(name='累计正式申请', value=summary(stats['total']), inline=False)
        embed.add_field(name='管理员 / 服主测试记录（不占名额）', value=summary(stats['tests']), inline=False)
        embed.add_field(name='每日名额', value=f'剩余 **{max(0, store.DAILY_LIMIT-stats["used"])} / {store.DAILY_LIMIT}** · 北京时间 0 点刷新')
        embed.add_field(name='私信异常 / 待确认', value=str(stats['dm_failed']))
        embed.set_footer(text='申请审批仍仅限服主 · 历史申请保留原频道与链接')
        return embed

    async def refresh(self, interaction):
        await interaction.edit_original_response(embed=await self.embed(), view=self)

    @ui.button(label='编辑面板文案', emoji='📝', style=discord.ButtonStyle.primary)
    async def edit_copy(self, button, interaction):
        await interaction.response.send_modal(CopyModal(self))

    @ui.button(label='修改发送频道', emoji='📍', style=discord.ButtonStyle.primary)
    async def edit_channels(self, button, interaction):
        await interaction.response.send_modal(ChannelModal(self))

    @ui.button(label='手动刷新面板', emoji='🔄', style=discord.ButtonStyle.success)
    async def deploy(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        self.cog.entry_signature = self.cog.panel_signature = None
        try:
            await self.cog.refresh_panels()
        except Exception as error:
            self.cog.report('手动刷新面板', error)
            return await interaction.followup.send('刷新未完成，请检查频道权限；后台会继续尝试。', ephemeral=True)
        await self.refresh(interaction)
        await interaction.followup.send('✅ 晋升入口与置底导航已刷新。', ephemeral=True)

    @ui.button(label='刷新审批统计', emoji='📊', row=1)
    async def stats(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        await self.refresh(interaction)

    @ui.button(label='预览面板', emoji='👀', row=1)
    async def preview(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        cfg, used = await asyncio.gather(asyncio.to_thread(store.settings), asyncio.to_thread(store.quota, self.guild_id))
        await interaction.followup.send(embed=entry_embed(used, cfg), ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @ui.button(label='返回社区管理', emoji='↩️', row=1)
    async def back(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        from cogs.roles.views import build_community_manage_embed
        await interaction.edit_original_response(embed=build_community_manage_embed(interaction.guild), view=self.parent)


class SettingsModal(ui.Modal):
    async def save(self, interaction, changes):
        saved = False
        try:
            await self.panel.cog.configure(changes)
            saved = True
            await self.panel.cog.refresh_panels()
        except Exception as error:
            self.panel.cog.report('更新晋升设置', error)
            await self.panel.refresh(interaction)
            return await interaction.followup.send(
                '设置已保存，频道刷新暂未完成，后台会重试。' if saved else f'保存未完成：{error}', ephemeral=True)
        await self.panel.refresh(interaction)
        await interaction.followup.send('✅ 设置已保存，晋升面板已更新。', ephemeral=True)


class CopyModal(SettingsModal):
    def __init__(self, panel):
        super().__init__(title='小蛋晋升 · 编辑面板文案')
        self.panel = panel
        cfg = DEFAULT_COPY | panel.cfg
        self.inputs = {}
        for key, label, limit in [('title', '面板标题', 256), ('intro', '欢迎说明', 1500),
                                  ('benefits', '权益说明（只改文案）', 1024),
                                  ('requirements', '申请条件说明', 1024), ('notes', '申请须知', 1024)]:
            item = ui.InputText(label=label, value=cfg[key], required=True, max_length=limit,
                                style=discord.InputTextStyle.short if key == 'title' else discord.InputTextStyle.paragraph)
            self.inputs[key] = item
            self.add_item(item)

    async def callback(self, interaction):
        if not await self.panel.allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await self.save(interaction, {key: item.value for key, item in self.inputs.items()})


class ChannelModal(SettingsModal):
    def __init__(self, panel):
        super().__init__(title='小蛋晋升 · 修改发送频道')
        self.panel = panel
        self.entry = ui.InputText(label='申请与面板频道 ID', value=str(panel.cfg['channel_id']))
        self.audit = ui.InputText(label='审批记录频道 ID', value=str(panel.cfg['log_channel_id']))
        self.add_item(self.entry)
        self.add_item(self.audit)

    async def callback(self, interaction):
        if not await self.panel.allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            changes = {'channel_id': int(self.entry.value.strip().strip('<#>')),
                       'log_channel_id': int(self.audit.value.strip().strip('<#>'))}
            for key, channel_id in changes.items():
                channel = await self.panel.cog.channel(channel_id)
                if not isinstance(channel, discord.TextChannel) or channel.guild.id != interaction.guild_id:
                    raise ValueError('请选择当前服务器的文字频道。')
                perms = channel.permissions_for(interaction.guild.me)
                needed = ['view_channel', 'send_messages', 'embed_links', 'read_message_history']
                if key == 'channel_id':
                    needed.append('attach_files')
                if not all(getattr(perms, name) for name in needed):
                    raise ValueError(f'机器人在 <#{channel_id}> 缺少发送消息、嵌入链接、读取历史或上传附件权限。')
        except (ValueError, discord.HTTPException) as error:
            return await interaction.followup.send(f'频道设置未保存：{error}', ephemeral=True)
        await self.save(interaction, changes)
