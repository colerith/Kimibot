# cogs/general/core.py

import discord
from discord import SlashCommandGroup, Option
from discord.ext import commands
import asyncio
import datetime
import random

from config import IDS, STYLE, WISH_CHANNEL_ID
from .utils import parse_duration, is_super_egg, TZ_CN
from .storage import load_role_data, save_role_data, load_lottery_data, save_lottery_data
from .views import (
    WishPanelView, WishActionView, AnnouncementModal, PollView,
    RoleClaimView, LotteryCreateModal, LotteryJoinView, RoleManagerView,
    deploy_role_panel 
)

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.wish_panel_message_id = None

    @commands.Cog.listener()
    async def on_ready(self):
        # 注册持久化视图
        self.bot.add_view(WishPanelView())
        self.bot.add_view(WishActionView())
        self.bot.add_view(LotteryJoinView("Prize")) 
        self.bot.add_view(RoleClaimView()) 
        print("General Cog Layout Loaded.")
        asyncio.create_task(self.check_and_post_wish_panel())
        asyncio.create_task(self.resume_lotteries())

    # --- 欢迎消息 ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # 0. 基础过滤：不欢迎机器人
        if member.bot: return

        print(f"检测到新成员加入: {member.name} (ID: {member.id})") # 妈妈加的调试日志

        # 1. 尝试获取配置的频道，如果没有就尝试系统频道，再没有就放弃
        targeted_channel_id = 1397629013152894978 

        channel = member.guild.get_channel(targeted_channel_id)

        # 如果找不到指定频道，再尝试系统默认频道
        if not channel:
            channel = member.guild.system_channel

        if not channel:
            print("找不到合适的欢迎频道，放弃发送欢迎消息。")
            return

        # 2. 准备频道ID
        # 答题频道 ID
        quiz_channel_id = IDS.get("QUIZ_CHANNEL_ID", 1467034060026286090)
        # 审核频道 ID
        ticket_channel_id = IDS.get("TICKET_PANEL_CHANNEL_ID", 0) # 确保config里有这个

        embed = discord.Embed(
            title="🎉 欢迎来到\"🔮LOFI-加载中\"社区！",
            description=f"你好呀，{member.mention}！欢迎你加入🔮LOFI-加载中大家庭！\n\n"
                        f"🚪 **第一步：获取基础权限**\n"
                        f"请前往 <#{quiz_channel_id}> 参与答题，答对后即可获得【新兵蛋子】身份。\n\n"
                        f"🔑 **第二步：解锁全区**\n"
                        f"获得身份后，如需访问卡区等更多内容，请前往 <#{ticket_channel_id}> 申请人工审核。\n\n"
                        f"祝你玩得开心捏！✨",
            color=STYLE["KIMI_YELLOW"]
        )

        if member.avatar:
             embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text="记得先看社区守则哦~")

        try:
            await channel.send(content=member.mention, embed=embed) # 加上@提醒，这样他能听到
            print(f"已向 {channel.name} 发送欢迎消息。")
        except discord.Forbidden:
            print(f"权限不足：无法在频道 {channel.name} 发送消息。")
        except Exception as e:
            print(f"发送欢迎消息时发生未知错误: {e}")
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id != WISH_CHANNEL_ID or message.author == self.bot.user:
            return

        if self.wish_panel_message_id:
            try:
                channel = self.bot.get_channel(WISH_CHANNEL_ID)
                if not channel: return
                old_panel_message = await channel.fetch_message(self.wish_panel_message_id)
                await old_panel_message.delete()
            except discord.NotFound:
                print("旧的许愿面板消息找不到了，可能已被删除。")
            except discord.Forbidden:
                print("错误：本大王没有权限删除许愿频道的消息！")
            except Exception as e:
                print(f"删除旧许愿面板时发生未知错误: {e}")

        await self.post_wish_panel()

    # --- 许愿池管理 ---
    async def post_wish_panel(self):
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if not channel:
            print("错误：找不到许愿池频道！")
            return
        embed = discord.Embed(
            title="✨ 奇米大王的许愿池",
            description="有什么想要的新功能、角色卡、或者对社区的建议吗？\n\n**点击下方的菜单选择你的愿望类型，然后告诉本大王吧！**",
            color=STYLE["KIMI_YELLOW"]
        )
        panel_message = await channel.send(embed=embed, view=WishPanelView())
        self.wish_panel_message_id = panel_message.id

    async def check_and_post_wish_panel(self):
        """机器人启动时运行，清理所有旧面板并发送一个新的。"""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if not channel:
            print("错误：找不到许愿池频道，无法设置持久化面板！")
            return

        try:
            async for message in channel.history(limit=100):
                if message.author == self.bot.user and message.embeds:
                    if "奇米大王的许愿池" in message.embeds[0].title:
                        await message.delete()
            
            print("已清理所有旧的许愿面板。")

        except discord.Forbidden:
            print(f"呜...本大王没有权限清理频道 {channel.name} 的旧面板！")
        except Exception as e:
            print(f"清理旧许愿面板时发生错误: {e}")

        await self.post_wish_panel()
        print("已成功发送全新的许愿面板到频道底部。")

    @discord.slash_command(name="刷新许愿面板", description="（仅限超级小蛋）手动发送或刷新许愿面板！")
    @is_super_egg()
    async def setup_wish_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if channel:
            try:
                await self.post_wish_panel()
                await ctx.followup.send("许愿面板已经成功发送惹！✨", ephemeral=True)
            except discord.Forbidden:
                await ctx.followup.send(f"呜...本大王没有权限在频道 {channel.name} 发送消息！", ephemeral=True)
        else:
            await ctx.followup.send("呜...找不到许愿池频道！", ephemeral=True)

    # ==================== 身份组领取 (Refactored) ====================
    role_group = SlashCommandGroup("百变小蛋", "管理自助领取的装饰身份组")

    @role_group.command(name="管理", description="打开身份组管理控制台（添加/移除身份组）")
    @is_super_egg()
    
    async def manage_roles(self, ctx):
        # 初始化 View
        view = RoleManagerView(ctx)

        # 初始 Embed
        roles = view.get_current_roles()
        embed = discord.Embed(title="⚙️ 身份组池管理控制台", color=discord.Color.blue())
        desc = "**当前已上架的身份组：**\n"
        if roles:
            desc += "\n".join([f"• {r.mention} (ID: {r.id})" for r in roles])
        else:
            desc += "*(空空如也，快添加一些吧！)*"

        desc += "\n\n**操作说明：**\n➕ 使用第一行菜单添加新身份组\n➖ 使用第二行菜单移除已有身份组"
        embed.description = desc

        await ctx.respond(embed=embed, view=view, ephemeral=True)

    @role_group.command(name="发送", description="直接在当前频道发送用户领取面板")
    @is_super_egg()
    async def send_role_panel_cmd(self, ctx):
        await ctx.defer(ephemeral=True)
        
        status = await deploy_role_panel(ctx.channel, ctx.guild, ctx.me.display_avatar.url)
        
        if status == "updated":
            await ctx.followup.send("✅ 检测到当前频道已有面板，已同步最新数据并 **更新** 成功！", ephemeral=True)
        else:
            await ctx.followup.send("✅ 面板已 **发送** 成功！", ephemeral=True)

    # ==================== 抽奖 ====================
    lottery_group = SlashCommandGroup("抽奖", "激动人心的抽奖功能！")

    @lottery_group.command(name="发起")
    @is_super_egg()
    async def start_lottery(self, ctx):
        await ctx.send_modal(LotteryCreateModal(self))

    async def lottery_timer(self, message_id, seconds):
        await asyncio.sleep(seconds)
        await self.end_lottery(message_id)

    async def end_lottery(self, message_id):
        # 1. 读数据
        data = load_lottery_data()
        msg_id_str = str(message_id)
        if msg_id_str not in data["active_lotteries"]: return

        lottery = data["active_lotteries"][msg_id_str]
        channel_id = lottery["channel_id"]
        participants = lottery["participants"]
        winners_count = lottery["winners"]
        prize = lottery["prize"]
        # 兼容旧数据，如果没有provider字段则设为官方
        provider = lottery.get("provider", "奇米大王官方")

        channel = self.bot.get_channel(channel_id)
        if not channel: return

        # 2. 选人
        winners = []
        if len(participants) > 0:
            count = min(len(participants), winners_count)
            winners = random.sample(participants, count)

        # 3. 更新原消息状态
        try:
            msg = await channel.fetch_message(message_id)

            # 更新原消息Embed：改成灰色，标题加[已结束]
            embed = msg.embeds[0]
            embed.color = 0x99AAB5 # 变灰
            embed.title = f"🏁 [已结束] {prize}"

            # 移除“点击下方按钮”那行
            lines = embed.description.split("\n")
            # 过滤掉包含"⬇️"的行
            new_lines = [line for line in lines if "⬇️" not in line]
            embed.description = "\n".join(new_lines)

            embed.set_footer(text=f"已结束 | 共 {len(participants)} 人参与")

            # 禁用按钮
            view = discord.ui.View.from_message(msg)
            for child in view.children:
                child.disabled = True
                child.style = discord.ButtonStyle.secondary # 按钮也变灰
                child.label = "活动已结束"

            await msg.edit(embed=embed, view=view)

            # 4. 发送开奖公告 (引用原消息)
            if winners:
                winner_mentions = " ".join([f"<@{uid}>" for uid in winners])
                # 构造开奖 Embed
                result_embed = discord.Embed(
                    title=f"🎉 恭喜中奖！",
                    description=f"关于 **{prize}** 的抽奖已经结束啦！\n\n🏆 **获奖者名单**：\n{winner_mentions}\n\n请获奖的小饱饱留意私信或者联系 **{provider}** 领奖哦！",
                    color=0xFFD700
                )
                await channel.send(content=f"开奖啦！{winner_mentions}", embed=result_embed, reference=msg)
            else:
                await channel.send(f"🥀 关于 **{prize}** 的抽奖结束啦，可惜没人参与，奖品只能自己吃掉惹...", reference=msg)

        except Exception as e:
            print(f"开奖失败 {message_id}: {e}")

        # 5. 删数据
        del data["active_lotteries"][msg_id_str]
        save_lottery_data(data)

    async def resume_lotteries(self):
        await self.bot.wait_until_ready()
        data = load_lottery_data()
        now_ts = datetime.datetime.now(TZ_CN).timestamp()
        to_remove = []
        for msg_id, info in data["active_lotteries"].items():
            end_ts = info["end_timestamp"]
            remaining = end_ts - now_ts
            if remaining <= 0: await self.end_lottery(int(msg_id))
            else: self.bot.loop.create_task(self.lottery_timer(int(msg_id), remaining))

    @lottery_group.command(name="结束", description="强制结束某个抽奖")
    @is_super_egg()
    async def force_end_lottery(self, ctx, message_id: str):
        await ctx.defer(ephemeral=True)
        data = load_lottery_data()
        if message_id not in data["active_lotteries"]: return await ctx.followup.send("找不到数据！", ephemeral=True)
        await self.end_lottery(int(message_id))
        await ctx.followup.send("已强制结束！", ephemeral=True)

    # ====== 辅助工具命令 (回顶) =======

    # 1. 斜杠命令版本 (/回顶)
    @discord.slash_command(name="回顶", description="本大王带你坐穿梭机回到帖子最顶上！咻~")
    async def back_to_top(self, ctx: discord.ApplicationContext):
        await self._back_to_top_logic(ctx)

    # 2. 右键菜单版本 (右键消息 -> Apps -> 🚀 回到帖子顶部)
    @discord.message_command(name="🚀 回到帖子顶部")
    async def back_to_top_ctx(self, ctx: discord.ApplicationContext, message: discord.Message):
        await self._back_to_top_logic(ctx)

    # 共用逻辑函数
    async def _back_to_top_logic(self, ctx: discord.ApplicationContext):
        # 检查是否在帖子频道 (Thread)
        if not isinstance(ctx.channel, discord.Thread):
            await ctx.respond("呜...这个魔法只能在帖子频道里用啦！", ephemeral=True)
            return
        
        try:
            # 帖子的ID通常就是起始消息的ID
            starter_message = await ctx.channel.fetch_message(ctx.channel.id)
            
            view = discord.ui.View()
            button = discord.ui.Button(label="🚀 点我回到顶部！", style=discord.ButtonStyle.link, url=starter_message.jump_url)
            view.add_item(button)
            
            await ctx.respond("顶！🆙 本大王帮你创建了回到顶部嘟快速通道惹！", view=view, ephemeral=True)
            
        except discord.NotFound:
            await ctx.respond("咦？本大王找不到这个帖子的第一条消息惹...好奇怪！", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"呜...发生错误惹: {e}", ephemeral=True)

    @discord.slash_command(name="发布公告", description="奇米大王的特别广播时间到惹！(会弹出编辑器哦)")
    @is_super_egg()
    async def publish_announcement(self, ctx: discord.ApplicationContext, 
        channel: discord.TextChannel, 
        mention_role: Option(discord.Role, "要@的身份组", required=False) = None,  # pyright: ignore[reportInvalidTypeForm]
        image1: Option(discord.Attachment, "图片附件1", required=False) = None,  # type: ignore
        image2: Option(discord.Attachment, "图片附件2", required=False) = None, # type: ignore
        image3: Option(discord.Attachment, "图片附件3", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image4: Option(discord.Attachment, "图片附件4", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image5: Option(discord.Attachment, "图片附件5", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image6: Option(discord.Attachment, "图片附件6", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image7: Option(discord.Attachment, "图片附件7", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image8: Option(discord.Attachment, "图片附件8", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image9: Option(discord.Attachment, "图片附件9", required=False) = None # pyright: ignore[reportInvalidTypeForm]
    ):
        attachments = [img for img in [image1, image2, image3, image4, image5, image6, image7, image8, image9] if img]
        modal = AnnouncementModal(channel, mention_role, attachments)
        await ctx.send_modal(modal)

    @discord.slash_command(name="清空消息", description="本大王来帮你打扫卫生惹！可以定时清理唷~")
    @is_super_egg()
    async def clear_messages(self, ctx: discord.ApplicationContext, 
        channel: discord.TextChannel, 
        amount: Option(int, "要删除的消息数量", required=True),  # pyright: ignore[reportInvalidTypeForm]
        schedule: Option(str, "延迟执行 (例如: 10s, 5m, 1h)", required=False) = None # pyright: ignore[reportInvalidTypeForm]
    ):
        await ctx.defer(ephemeral=True) 
        if schedule:
            delay = parse_duration(schedule)
            if delay > 0:
                await ctx.followup.send(f"收到唷呐！本大王已经把小闹钟定好惹，{delay}秒后开始大扫除！🕰️✨", ephemeral=True)
                await asyncio.sleep(delay)
                deleted_messages = await channel.purge(limit=amount)
                await channel.send(f"咻~！✨ 本大王施展惹清洁魔法，赶跑了 {len(deleted_messages)} 条坏蛋消息！", delete_after=10)
            else:
                await ctx.followup.send("呜...这个时间格式本大王看不懂捏！要用's', 'm', 'h'结尾才可以嘛！", ephemeral=True)
        else:
            deleted_messages = await channel.purge(limit=amount)
            await ctx.followup.send(f"咻~！✨ 本大王施展惹清洁魔法，赶跑了 {len(deleted_messages)} 条坏蛋消息！", ephemeral=True)

    @discord.slash_command(name="慢速模式", description="让大家冷静一点，优雅地聊天嘛~")
    @is_super_egg()
    async def slowmode(self, ctx: discord.ApplicationContext, seconds: int):
        if seconds < 0:
            await ctx.respond("秒数不能是负数啦，笨蛋饱饱！", ephemeral=True)
            return
        if seconds > 21600: 
            await ctx.respond("最长时间不能超过6小时(21600秒)哦！", ephemeral=True)
            return

        await ctx.channel.edit(slowmode_delay=seconds)

        if seconds > 0:
            await ctx.respond(f"大家冷静一点捏~本大王开启了 **{seconds}秒** 慢速魔法！🐢")
        else:
            await ctx.respond("好惹！封印解除！大家可以尽情地聊天惹！冲鸭！🚀")

    # --- 投票命令组 ---
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

    async def poll_timer(self, view: PollView, message: discord.Message, duration: int):
        try:
            await asyncio.sleep(duration)
            await view.end_poll(message)
        except Exception as e:
            print(f"投票计时器出错: {e}")

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

def setup(bot):
    bot.add_cog(General(bot))
