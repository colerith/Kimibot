# cogs/thread_tools/cog.py

import discord
from discord.ext import commands

class ThreadToolsCog(commands.Cog, name="帖子工具"):
    """
    提供帖子 (Thread) 相关的实用工具命令。
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- 命令 ---

    # 1. 斜杠命令版本 (/回顶)
    @discord.slash_command(name="回顶", description="本大王带你坐穿梭机回到帖子最顶上！咻~")
    async def back_to_top_slash(self, ctx: discord.ApplicationContext):
        """处理 /回顶 命令。"""
        await self._back_to_top_logic(ctx)

    # 2. 右键菜单版本 (右键消息 -> Apps -> 🚀回到帖子顶部)
    @discord.message_command(name="🚀回到帖子顶部")
    async def back_to_top_context_menu(self, ctx: discord.ApplicationContext, message: discord.Message):
        """处理右键消息上下文菜单命令。"""
        # message 参数是上下文菜单必须的，但我们的逻辑不需要它
        await self._back_to_top_logic(ctx)

    # 共用逻辑函数
    async def _back_to_top_logic(self, ctx: discord.ApplicationContext):
        """“回到顶部”功能的通用实现。"""
        # 检查是否在帖子频道 (Thread)
        if not isinstance(ctx.channel, discord.Thread):
            await ctx.respond("呜...这个魔法只能在帖子频道里用啦！", ephemeral=True)
            return

        try:
            # 获取帖子的起始消息 (其ID与帖子本身的ID相同)
            starter_message = await ctx.channel.fetch_message(ctx.channel.id)

            view = discord.ui.View()
            button = discord.ui.Button(
                label="🚀 点我回到顶部！",
                style=discord.ButtonStyle.link,
                url=starter_message.jump_url
            )
            view.add_item(button)

            await ctx.respond("顶！🆙 本大王帮你创建了回到顶部嘟快速通道惹！", view=view, ephemeral=True)

        except discord.NotFound:
            await ctx.respond("咦？本大王找不到这个帖子的第一条消息惹...好奇怪！", ephemeral=True)
        except discord.Forbidden:
             await ctx.respond("呜...本大王没有权限读取这个帖子的起始消息！", ephemeral=True)
        except Exception as e:
            print(f"Error in 'back_to_top' command: {e}")
            await ctx.respond(f"呜...发生未知错误惹: {e}", ephemeral=True)