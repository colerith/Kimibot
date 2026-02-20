# cogs/poll/cog.py

import discord
from discord.ext import commands
from discord import SlashCommandGroup, Option
import asyncio
import datetime

from .views import PollView
from config import TZ_CN
from cogs.shared.utils import is_super_egg, parse_duration

class PollsCog(commands.Cog, name="投票系统"):
    """负责所有投票相关的功能。"""

    def __init__(self, bot):
        self.bot = bot
        # 用于存储活跃的投票任务 {message_id: (task, view)}
        self.active_polls = {}

    def cog_unload(self):
        """当 Cog 被卸载时，取消所有正在进行的投票任务。"""
        for task, view in self.active_polls.values():
            task.cancel()
        print("[Polls] Cog unloaded and all active poll tasks cancelled.")


    # --- 命令组 ---
    vote = SlashCommandGroup("投票", "大家快来告诉本大王你的想法嘛！")

    @vote.command(name="发起", description="创建一个支持多选项、自动截止的投票！")
    async def start_vote(self, ctx: discord.ApplicationContext,
        question: Option(str, "投票的问题是什么呢？", required=True), # pyright: ignore[reportInvalidTypeForm]
        options_text: Option(str, "选项列表 (用 | 竖线分隔，最多20个)", required=True), # pyright: ignore[reportInvalidTypeForm]
        duration: Option(str, "持续时间 (例如: 10m, 1h, 24h)", required=True) # pyright: ignore[reportInvalidTypeForm]
    ):
        seconds = parse_duration(duration)
        if seconds <= 0:
            await ctx.respond("呜...时间格式不对哦！请用 '10m', '1h' 这种格式捏！", ephemeral=True)
            return
        if seconds < 60:
            await ctx.respond("投票时间太短啦！至少要1分钟哦！", ephemeral=True)
            return

        options = [opt.strip() for opt in options_text.split('|') if opt.strip()]
        if len(options) < 2:
            await ctx.respond("投票至少要有两个选项嘛！笨蛋！", ephemeral=True)
            return
        if len(options) > 20:
            await ctx.respond("选项太多啦！本大王记不住，最多只能20个哦！", ephemeral=True)
            return

        await ctx.defer()

        now_cn = datetime.datetime.now(TZ_CN)
        end_time = now_cn + datetime.timedelta(seconds=seconds)

        view = PollView(question, options, end_time, ctx.author.id)
        embed = view.build_embed(is_ended=False)

        message = await ctx.respond(embed=embed, view=view)
        
        if isinstance(message, discord.Interaction):
             message = await message.original_response()

        self.bot.loop.create_task(self.poll_timer(view, message, seconds))

    @vote.command(name="提前结束", description="（管理员）强制结束正在进行的投票")
    @is_super_egg()
    async def force_end_vote(self, ctx: discord.ApplicationContext, message_id: str):
        try:
            message = await ctx.channel.fetch_message(int(message_id))
        except:
            await ctx.respond("呜...找不到这个消息ID，或者本大王在那个频道没有权限！", ephemeral=True)
            return

        if not message.author == self.bot.user or not message.embeds:
            await ctx.respond("这好像不是本大王发的投票消息哦！", ephemeral=True)
            return
        
        embed = message.embeds[0]
        if "已截止" in (embed.footer.text or ""):
            await ctx.respond("这个投票已经结束了呀！", ephemeral=True)
            return

        new_view = discord.ui.View.from_message(message)
        for child in new_view.children:
            child.disabled = True
            child.style = discord.ButtonStyle.secondary
        
        embed.color = 0x99AAB5
        embed.title = f"🔴 (管理员强制结束) {embed.title.strip('📊 ')}"
        embed.set_footer(text=f"被管理员 {ctx.author.display_name} 强制截止")

        await message.edit(embed=embed, view=new_view)
        await ctx.respond("好哒！本大王已经把这个投票强制关掉惹！😤", ephemeral=True)


    async def poll_timer(self, message_id: int, view: PollView, duration: int):
        """后台计时器，在时间结束后调用 end_poll。"""
        await asyncio.sleep(duration)
        channel_id = view.end_time.astimezone(TZ_CN).tzinfo 
        try:
            message = None
            for guild in self.bot.guilds:
                try:
                    channel = guild.get_channel(view.end_time.tzinfo) # Should be in cog init
                    if channel:
                         message = await channel.fetch_message(message_id)
                         break
                except (discord.NotFound, discord.Forbidden):
                     continue
            if message:
                await view.end_poll(message)
        except Exception as e:
            print(f"Error ending poll {message_id}: {e}")
        finally:
            if message_id in self.active_polls:
                del self.active_polls[message_id]
