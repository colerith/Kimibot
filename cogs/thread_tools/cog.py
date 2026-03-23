# cogs/thread_tools/cog.py

import discord
from discord.ext import commands

class ThreadToolsCog(commands.Cog, name="帖子工具"):
    """
    提供帖子 (Thread) 相关的实用工具命令。
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- 通用校验 ---

    async def _get_thread_owner_id(self, thread: discord.Thread):
        if thread.owner_id:
            return thread.owner_id
        try:
            starter_message = await thread.fetch_message(thread.id)
            return starter_message.author.id
        except Exception:
            return None

    async def _ensure_thread_owner(self, ctx: discord.ApplicationContext):
        if not isinstance(ctx.channel, discord.Thread):
            await ctx.respond("呜...这个魔法只能在帖子频道里用啦！", ephemeral=True)
            return False

        owner_id = await self._get_thread_owner_id(ctx.channel)
        if not owner_id:
            await ctx.respond("呜...本大王找不到帖子的贴主信息惹。", ephemeral=True)
            return False

        if owner_id != ctx.author.id:
            await ctx.respond("呜...只有贴主才能使用这个功能哦！", ephemeral=True)
            return False

        return True

    async def _toggle_mark(self, ctx: discord.ApplicationContext, message: discord.Message):
        try:
            message = await ctx.channel.fetch_message(message.id)
        except Exception:
            pass

        try:
            if message.pinned:
                await message.unpin(reason=f"贴主 {ctx.author} 取消标注")
                await ctx.respond("已取消标注。", ephemeral=True)
            else:
                await message.pin(reason=f"贴主 {ctx.author} 标注消息")
                await ctx.respond("已标注。", ephemeral=True)
        except discord.Forbidden:
            await ctx.respond("呜...本大王没有权限标注消息（需要管理消息权限）。", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"标注失败: {e}", ephemeral=True)

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

    # --- 贴主命令组 ---

    thread_owner = discord.SlashCommandGroup("贴主", "贴主相关功能")

    @thread_owner.command(name="自助删帖", description="贴主自助删除当前帖子")
    async def thread_owner_delete(self, ctx: discord.ApplicationContext):
        if not await self._ensure_thread_owner(ctx):
            return

        await ctx.respond("正在删除该帖子...", ephemeral=True)
        try:
            await ctx.channel.delete(reason=f"贴主 {ctx.author} 自助删帖")
        except Exception as e:
            await ctx.followup.send(f"删除失败: {e}", ephemeral=True)

    @thread_owner.command(name="修改贴名", description="贴主修改当前帖子标题")
    async def thread_owner_rename(self, ctx: discord.ApplicationContext, new_name: discord.Option(str, "新标题")):
        if not await self._ensure_thread_owner(ctx):
            return

        if len(new_name) > 100:
            await ctx.respond("标题太长啦，控制在 100 字以内哦。", ephemeral=True)
            return

        try:
            await ctx.channel.edit(name=new_name, reason=f"贴主 {ctx.author} 修改贴名")
            await ctx.respond("已更新帖子标题。", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"修改失败: {e}", ephemeral=True)

    @thread_owner.command(name="标注消息", description="标注/取消标注当前帖子内的消息")
    async def thread_owner_mark_message(self, ctx: discord.ApplicationContext, message: discord.Option(str, "消息链接或ID")):
        if not await self._ensure_thread_owner(ctx):
            return

        msg_id = None
        try:
            msg_id = int(message.strip().split("/")[-1])
        except Exception:
            pass

        if not msg_id:
            await ctx.respond("请提供消息链接或消息ID。", ephemeral=True)
            return

        try:
            target = await ctx.channel.fetch_message(msg_id)
        except Exception:
            await ctx.respond("找不到这条消息，请确认在当前帖子内。", ephemeral=True)
            return

        await self._toggle_mark(ctx, target)

    @discord.message_command(name="标注消息")
    async def mark_message_context_menu(self, ctx: discord.ApplicationContext, message: discord.Message):
        if not await self._ensure_thread_owner(ctx):
            return

        if not isinstance(ctx.channel, discord.Thread):
            await ctx.respond("呜...这个魔法只能在帖子频道里用啦！", ephemeral=True)
            return

        if message.channel.id != ctx.channel.id:
            await ctx.respond("请在当前帖子内选择要标注的消息。", ephemeral=True)
            return

        await self._toggle_mark(ctx, message)
