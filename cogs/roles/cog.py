# cogs/roles/cog.py

import discord
from discord.ext import commands
from discord import SlashCommandGroup

from .views import (
    CommunityPanelManageView,
    RoleClaimView,
    build_community_manage_embed,
    NotificationEntranceView,
)
from cogs.shared.utils import is_super_egg

class RolesCog(commands.Cog):
    """负责自助身份组领取、通知订阅和相关管理命令。"""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # 注册持久化视图，这样机器人重启后按钮也能继续工作
        self.bot.add_view(RoleClaimView())
        self.bot.add_view(NotificationEntranceView())
        print("[Roles] Cog loaded and persistent views registered.")

    # --- 命令组定义 ---
    community_group = SlashCommandGroup("社区面板", "管理小蛋报到与社区蛋壳面板")

    @community_group.command(name="管理", description="打开社区面板管理台")
    @is_super_egg()
    async def manage_community_panel(self, ctx: discord.ApplicationContext):
        try:
            await ctx.defer(ephemeral=True)
        except discord.NotFound:
            return
        embed = build_community_manage_embed(ctx.guild)
        view = CommunityPanelManageView(ctx, self.bot)
        try:
            await ctx.followup.send(embed=embed, view=view, ephemeral=True)
        except discord.NotFound:
            return
