# cogs/wish_pool/cog.py

import discord
from discord.ext import commands
import asyncio

from .views import WishPanelView, WishActionView
from config import IDS, STYLE, WISH_CHANNEL_ID
from cogs.shared.utils import is_super_egg

class WishPoolCog(commands.Cog):
    """管理许愿池相关功能的 Cog。"""

    def __init__(self, bot):
        self.bot = bot
        # 用于追踪当前面板消息的ID，避免重复发送
        self.wish_panel_message_id = None

    @commands.Cog.listener()
    async def on_ready(self):
        # 注册持久化视图
        self.bot.add_view(WishPanelView())
        self.bot.add_view(WishActionView())
        print("[Wish Pool] Cog loaded and views registered.")
        # 启动时自动检查并发送面板
        asyncio.create_task(self.check_and_post_wish_panel())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """监听许愿池频道的消息，自动将面板移动到底部。"""
        # 过滤无关消息
        if message.channel.id != WISH_CHANNEL_ID or message.author == self.bot.user:
            return

        # 如果有旧面板消息，先删除
        if self.wish_panel_message_id:
            try:
                channel = self.bot.get_channel(WISH_CHANNEL_ID)
                if not channel: return
                old_panel_message = await channel.fetch_message(self.wish_panel_message_id)
                await old_panel_message.delete()
            except discord.NotFound:
                pass # 找不到了说明已经被删了，正好
            except discord.Forbidden:
                print("权限不足：无法删除旧的许愿池面板！")
            except Exception as e:
                print(f"删除旧许愿面板时发生未知错误: {e}")

        # 发送新面板
        await self.post_wish_panel()

    async def post_wish_panel(self):
        """发送一个新的许愿池面板到频道。"""
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if not channel:
            print("错误：找不到许愿池频道！")
            return

        embed = discord.Embed(
            title="✨ 奇米大王的许愿池",
            description="有什么想要的新功能、角色卡、或者对社区的建议吗？\n\n"
                        "**点击下方的按钮选择你的愿望类型，然后告诉本大王吧！**",
            color=STYLE["KIMI_YELLOW"]
        )
        try:
            panel_message = await channel.send(embed=embed, view=WishPanelView())
            self.wish_panel_message_id = panel_message.id
        except discord.Forbidden:
             print(f"权限不足：无法在许愿池频道 {channel.name} 发送消息！")


    async def check_and_post_wish_panel(self):
        """机器人启动时运行，清理所有旧面板并发送一个新的。"""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if not channel:
            print("错误：找不到许愿池频道，无法设置持久化面板！")
            return

        # 清理历史面板
        try:
            async for message in channel.history(limit=50):
                if message.author == self.bot.user and message.embeds:
                    if "奇米大王的许愿池" in message.embeds[0].title:
                        await message.delete()
            print("已清理所有旧的许愿面板。")
        except discord.Forbidden:
            print(f"权限不足：无法清理频道 {channel.name} 的旧面板！")
        except Exception as e:
            print(f"清理旧许愿面板时发生错误: {e}")

        # 发送新面板
        await self.post_wish_panel()
        print("已成功发送全新的许愿面板到频道底部。")

    @discord.slash_command(name="刷新许愿面板", description="（仅限超级小蛋）手动发送或刷新许愿面板！")
    @is_super_egg()
    async def setup_wish_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        await self.check_and_post_wish_panel()
        await ctx.followup.send("✨ 许愿面板已经成功刷新惹！", ephemeral=True)