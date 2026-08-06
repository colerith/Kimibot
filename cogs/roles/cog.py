# cogs/roles/cog.py

import discord
from discord.ext import commands
from discord import SlashCommandGroup

# 从同目录的模块导入
from .storage import load_role_data, save_role_data
from .views import (
    CommunityPanelManageView,
    RoleManagerView,
    RoleClaimView,
    build_community_manage_embed,
    deploy_role_panel,
    NotificationEntranceView,
)
# 从全局配置导入
from config import IDS, STYLE
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
    role_group = SlashCommandGroup("百变小蛋", "管理自助领取的装饰身份组和通知")

    @community_group.command(name="管理", description="打开社区面板管理台")
    @is_super_egg()
    async def manage_community_panel(self, ctx: discord.ApplicationContext):
        embed = build_community_manage_embed(ctx.guild)
        view = CommunityPanelManageView(ctx, self.bot)
        await ctx.respond(embed=embed, view=view, ephemeral=True)

    @role_group.command(name="管理身份组", description="打开身份组管理控制台（添加/移除身份组）")
    @is_super_egg()
    async def manage_roles(self, ctx):
        view = RoleManagerView(ctx)
        embed = view.build_dashboard_embed()
        await ctx.respond(embed=embed, view=view, ephemeral=True)

    @role_group.command(name="换装面板", description="（管理）在当前频道发送或更新自助换装面板")
    @is_super_egg()
    async def send_role_panel_cmd(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        status = await deploy_role_panel(ctx.channel, ctx.guild, self.bot.user.display_avatar.url)

        if status == "updated":
            await ctx.followup.send("✅ 检测到已有面板，已同步最新数据并 **更新**！", ephemeral=True)
        else:
            await ctx.followup.send("✅ 全新的换装面板已 **发送**！", ephemeral=True)

    @role_group.command(name="通知面板", description="（管理）发送通知订阅功能的入口面板")
    @is_super_egg()
    async def send_notify_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        embed = discord.Embed(
            title="📬 **社区通知中心**",
            description="不想错过重要消息？\n在这里，你可以订阅你感兴趣的通知类型。\n\n"
                        "✨ **如何使用：**\n"
                        "点击下方按钮，勾选你想要接收的通知，我们会自动为你添加对应的身份组。\n"
                        "再次点击并取消勾选，即可更新你的订阅。",
            color=STYLE["KIMI_YELLOW"]
        )
        embed.set_footer(text="按需订阅，拒绝打扰。")

        await ctx.channel.send(embed=embed, view=NotificationEntranceView())
        await ctx.followup.send("✅ 通知订阅面板已发送！", ephemeral=True)
