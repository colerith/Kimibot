# tickets.py

import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import random 
import json
import io
import zipfile

# 从中央配置文件导入所有配置
from config import IDS, QUOTA, STYLE

# 从quiz模块导入答题视图
from cogs.quiz import QuizStartView

# ======================================================================================
# --- 常量定义 ---
# ======================================================================================

# 指定的审核员ID (审核小蛋)
SPECIFIC_REVIEWER_ID = 1452321798308888776

# ======================================================================================
# --- 权限与工具函数 ---
# ======================================================================================

def is_super_egg():
    """权限检查：判断命令使用者是否为【超级小蛋】"""
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not isinstance(ctx.author, discord.Member) or not hasattr(ctx.author, 'roles'):
                await ctx.respond("呜...无法识别你的身份组信息！", ephemeral=True)
                return False
        super_egg_role = ctx.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
        if super_egg_role and super_egg_role in ctx.author.roles:
            return True
        await ctx.respond("呜...这个是【超级小蛋】专属嘟魔法，你还不能用捏！QAQ", ephemeral=True)
        return False
    return commands.check(predicate)

def get_ticket_info(channel: discord.TextChannel):
    """从工单频道的Topic中解析出创建者ID、名字和工单ID"""
    info = {}
    if not channel.topic: return info
    try:
        parts = channel.topic.split(" | ")
        for part in parts:
            key, value = part.split(": ", 1)
            info[key] = value
    except Exception: pass
    return info

# ======================================================================================
# --- 工单系统的交互视图 (Views) ---
# ======================================================================================
# 视图1：当用户审核通过后，请求管理员归档的按钮
class ArchiveRequestView(discord.ui.View):
    def __init__(self, reviewer: discord.Member = None):
        super().__init__(timeout=None)
        self.reviewer = reviewer

    async def button_callback(self, interaction: discord.Interaction, choice: str):
        # 先defer响应
        await interaction.response.defer()
        
        # 更新原消息，显示用户的选择
        original_embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if original_embed:
            original_embed.color = 0x00FF00  # 绿色表示已确认
            original_embed.set_footer(text=f"✅ 用户已选择：{choice}")
        
        # 禁用所有按钮
        for item in self.children:
            item.disabled = True
        
        # 编辑消息
        await interaction.message.edit(embed=original_embed, view=self)
        
        # 发送通知
        notify_text = f"📢 {interaction.user.mention} 选择了：**{choice}**\n\n"
        if self.reviewer:
            notify_text += f"{self.reviewer.mention}，这位小饱饱已经确认完毕，可以进行归档操作啦！"
        else:
            notify_text += f"<@&{IDS['SUPER_EGG_ROLE_ID']}>，这位小饱饱已经确认完毕，可以进行归档操作啦！"
        
        await interaction.channel.send(notify_text)

    @discord.ui.button(label="已申请加群", style=discord.ButtonStyle.primary, custom_id="req_archive_1")
    async def applied(self, button, interaction): 
        await self.button_callback(interaction, "已申请加群")

    @discord.ui.button(label="不打算加群，没有别的问题了", style=discord.ButtonStyle.secondary, custom_id="req_archive_2")
    async def no_problem(self, button, interaction): 
        await self.button_callback(interaction, "不打算加群，没有别的问题了")

# 视图：用户提交完材料后，点击按钮呼叫审核员
class NotifyReviewerView(discord.ui.View):
    def __init__(self, reviewer_id: int):
        super().__init__(timeout=None)
        self.reviewer_id = reviewer_id

    @discord.ui.button(label="✅ 材料已备齐，呼叫审核员", style=discord.ButtonStyle.primary, custom_id="notify_reviewer_button")
    async def notify_reviewer(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 只有工单创建者才能点击这个按钮
        ticket_info = get_ticket_info(interaction.channel)
        creator_id = ticket_info.get("创建者ID")
        if str(interaction.user.id) != creator_id:
            await interaction.response.send_message("呜...只有创建这个工单的饱饱才能呼叫审核员哦！", ephemeral=True)
            return
            
        # 禁用按钮，防止重复点击
        button.disabled = True
        button.label = "✅ 已呼叫审核小蛋"
        await interaction.message.edit(view=self)

        # 发送提及消息并给用户一个确认
        # 修改：这里使用了传入的 reviewer_id (即审核小蛋的ID)
        await interaction.response.send_message(f"<@{self.reviewer_id}> 小饱饱的材料准备好啦，快来看看吧！")

# 视图2：管理员在工单内的主要操作按钮面板
class TicketActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """检查点击按钮的是否为【超级小蛋】"""
        super_egg_role = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
        if super_egg_role and super_egg_role in interaction.user.roles:
            return True
        await interaction.response.send_message("呜...只有【超级小蛋】才能操作审核按钮哦！", ephemeral=True)
        return False

    # --- 修改：删除了“等待审核员接收” (claim_review1) 按钮，因为现在自动发送一审条件 ---

    @discord.ui.button(label="▶️ 进入二审", style=discord.ButtonStyle.primary, custom_id="ticket_review2")
    async def review2(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # 获取二审分类
        second_review_category = interaction.guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        if not second_review_category or not isinstance(second_review_category, discord.CategoryChannel):
            await interaction.followup.send("呜...找不到【二审】的频道分类或配置错误！", ephemeral=True)
            return
        
        try:
            # 获取工单信息
            info = get_ticket_info(interaction.channel)
            creator_id = int(info.get("创建者ID", 0))
            creator = interaction.guild.get_member(creator_id)
            
            # 移动频道并改名
            # 注意：因为跳过了接单步骤，可能没有 ReviewerName，这里处理一下
            reviewer_name = interaction.user.name
            new_name = f"二审中-{info.get('工单ID', '未知')}-{info.get('创建者', '未知')}-{reviewer_name}"
            
            await interaction.channel.edit(name=new_name, category=second_review_category)
            
            # 发送答题提示
            embed = discord.Embed(
                title="🎯 二审答题验证",
                description="恭喜通过一审！现在需要完成身份确认答题~",
                color=STYLE["KIMI_YELLOW"]
            )
            embed.add_field(
                name="📝 答题说明",
                value=(
                    "• 随机抽取10道题，每题10分，满分100分\n"
                    "• 限时2分钟完成\n"
                    "• 需要达到60分以上才能通过\n"
                    "• 题目涉及基础酒馆知识和女性生活常识\n"
                    "• **请认真作答，祝你好运！**"
                ),
                inline=False
            )
            embed.set_footer(text="准备好后，请点击下方按钮开始答题")
            
            # @提到待审核用户并发送答题面板
            if creator:
                await interaction.channel.send(
                    f"叮咚！{creator.mention} 小宝，请开始你的二审答题吧~",
                    embed=embed,
                    view=QuizStartView()
                )
            else:
                await interaction.channel.send(embed=embed, view=QuizStartView())
            
            # 禁用按钮
            button.disabled = True
            await interaction.message.edit(view=self)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ **移动失败！** 呜哇！本大王被【二审】分类挡在门外了！快让服主检查我在那个分类的权限！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"移动到二审时发生未知错误: {e}", ephemeral=True)

    @discord.ui.button(label="🎉 已过审", style=discord.ButtonStyle.success, custom_id="ticket_approved")
    async def approved(self, button: discord.ui.Button, interaction: discord.Interaction):
        info = get_ticket_info(interaction.channel)
        creator_id = int(info.get("创建者ID", 0))
        creator = interaction.guild.get_member(creator_id)
        if not creator:
            await interaction.response.send_message("呜...找不到申请工单的饱饱了，他可能已经离开服务器了...", ephemeral=True)
            return

        newbie_role = interaction.guild.get_role(IDS["VERIFICATION_ROLE_ID"])
        hatched_role = interaction.guild.get_role(IDS["HATCHED_ROLE_ID"])
        try:
            if newbie_role: await creator.remove_roles(newbie_role, reason="审核通过")
            if hatched_role: await creator.add_roles(hatched_role, reason="审核通过")
        except discord.Forbidden:
            await interaction.response.send_message("呜哇！本大王没有权限修改身份组！", ephemeral=True)
            return

        embed = discord.Embed(title="🥳 恭喜小宝加入社区", description="如果想来一起闲聊，社区有Q群可以来玩，进群问题也是填写你的【工单编号】就可以惹！\n## 对审核过程没有异议，同意并且阅读完全部东西后请点击下方按钮~身份组已经添加", color=STYLE["KIMI_YELLOW"])
        embed.set_image(url="https://files.catbox.moe/2tytko.jpg")
        embed.set_footer(text="宝宝如果已申请/不打算加群/没有别的问题了，请点击下方对应按钮")
        await interaction.channel.send(f"恭喜 {creator.mention} 通过审核！", embed=embed, view=ArchiveRequestView(reviewer=interaction.user))

        button.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="📦 工单归档", style=discord.ButtonStyle.secondary, custom_id="ticket_archive")
    async def archive(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 

        channel = interaction.channel
        archive_category = interaction.guild.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        if not archive_category or not isinstance(archive_category, discord.CategoryChannel):
            await interaction.followup.send("呜...找不到【归档】的频道分类或配置错误！", ephemeral=True)
            return

        await channel.send("本工单已被归档，将在10秒后移动到归档区并锁定。")
        await asyncio.sleep(10)

        try:
            is_approved = "已过审" in channel.name or "二审中" in channel.name or "一审中" in channel.name
            info = get_ticket_info(channel)
            if is_approved: new_name = f"已过审-{info.get('工单ID', '未知')}-{info.get('创建者', '未知')}"
            else: new_name = f"未通过-{info.get('工单ID', '未知')}-{info.get('创建者', '未知')}"

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"]): discord.PermissionOverwrite(read_messages=True)
            }

            await channel.edit(name=new_name, category=archive_category, overwrites=overwrites, reason="管理员手动归档")
            await interaction.followup.send("工单已成功归档并锁定！✨", ephemeral=True)

        except discord.Forbidden:
            await channel.send("❌ **归档失败！** 呜哇！本大王没有权限移动或修改这个频道！请服主检查我在【始发分类】和【归档分类】的权限！")
        except Exception as e:
            await channel.send(f"❌ **归档失败！** 发生未知错误: {e}")


# 视图3：用户在主频道点击创建工单的面板 (重写为创建频道版本)
class TicketPanelView(discord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @discord.ui.button(label="🥚 创建审核工单", style=discord.ButtonStyle.primary, custom_id="create_ticket_panel_button")
    async def create_ticket_callback(self, button: discord.ui.Button, interaction: discord.Interaction):
        # --- 时间检查 ---
        now = datetime.datetime.now(QUOTA["TIMEZONE"])
        if not (8 <= now.hour < 23):
            await interaction.response.send_message("呜...现在是审核员的休息时间 (08:00 - 23:00)，请在开放时间内再来申请哦！", ephemeral=True)
            return

        user_roles = [role.id for role in interaction.user.roles]
        if IDS["VERIFICATION_ROLE_ID"] not in user_roles and IDS["SUPER_EGG_ROLE_ID"] not in user_roles:
            await interaction.response.send_message(f"呜...只有【新兵蛋子】或【超级小蛋】才能创建审核工单哦！", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)

        # --- 新增：检查用户是否已有工单 ---
        first_review_category = interaction.guild.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"])
        second_review_category = interaction.guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        
        # 遍历一审和二审分类下的所有频道
        categories_to_check = [cat for cat in [first_review_category, second_review_category] if cat]
        for category in categories_to_check:
            for channel in category.text_channels:
                # 检查频道的 topic 是否包含该用户的ID
                if channel.topic and f"创建者ID: {interaction.user.id}" in channel.topic:
                    await interaction.followup.send(f"呜...你已经有一个正在处理的工单 {channel.mention} 惹！请不要重复创建哦~", ephemeral=True)
                    return
        # --- 结束检查 ---

        data = self.cog.load_quota_data()
        
        if data["daily_quota_left"] <= 0:
            await interaction.followup.send("呜...今天的新蛋审核名额已经用完惹，请明天再来吧！", ephemeral=True)
            return
            
        data["daily_quota_left"] -= 1
        self.cog.save_quota_data(data)
        await self.cog.update_ticket_panel()
        
        ticket_channel = None # 先声明变量
        try:
            if not first_review_category or not isinstance(first_review_category, discord.CategoryChannel):
                await interaction.followup.send("呜...找不到【一审】的频道分类！请服主检查配置！", ephemeral=True)
                raise ValueError("一审频道分类配置错误")

            ticket_id = random.randint(100000, 999999)
            channel_name = f"待接单-{ticket_id}-{interaction.user.name}"

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"]): discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            ticket_channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=first_review_category,
                overwrites=overwrites,
                topic=f"创建者ID: {interaction.user.id} | 创建者: {interaction.user.name} | 工单ID: {ticket_id}"
            )

        except (discord.Forbidden, ValueError, Exception) as e:
            print(f"创建工单频道时发生错误: {e}")
            if isinstance(e, discord.Forbidden):
                await interaction.followup.send("呜哇！本大王没有权限创建频道！快让服主检查我的【管理频道】权限！", ephemeral=True)
            elif not isinstance(e, ValueError):
                await interaction.followup.send(f"呜...创建工单时发生了未知错误，请联系服主查看后台日志！", ephemeral=True)

            # 如果创建失败，把名额还回去
            data["daily_quota_left"] += 1
            self.cog.save_quota_data(data)
            await self.cog.update_ticket_panel()
            return

        embed = discord.Embed(title=f"🎫 工单 #{ticket_id} 已创建", description=f"饱饱你好呀！请按照审核要求提交相关材料哦~", color=STYLE["KIMI_YELLOW"])
        super_egg_role_mention = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"]).mention
        
        # --- 修改：创建频道后直接发送一审要求，不再等待接单 ---
        
        # 1. 准备一审要求 Embed
        embed_req = discord.Embed(title="🔮 LOFI-加载中社区审核要求 【一审】", description="**⚠️ 请在审核时准备好以下材料**", color=STYLE["KIMI_YELLOW"])
        embed_req.add_field(name="一、成年证明（二选一）", value="1. 身份证**其余信息打码**，只露出身份证的__出生年月日__+__身份证号里出生年月日__部分\n2. 支付宝点击**我的-头像-我的档案-个人信息**，截图露出**生日**部分，其余信息打码", inline=False)
        embed_req.add_field(name="二、使用自建、非商业酒馆证明", value="准备好以下内容，让它们**同屏/同一张图显示**，如果在手机上显示不清/空间不够同屏，可以进行录屏：\n1. 你的SillyTavern后台（手机Termux、电脑Powershell/cmd、云酒馆1panel/宝塔/抱脸等）\n2. 一个超过100楼以上的女性向卡聊天记录，需要露出楼层编号和卡\n3. 在输入框内输入你的Discord id，格式为`Discord id：id数字`。\n> Discord id 获取方法:\n> 在设置里打开开发者模式-在聊天点击自己的头像-个人界面右上角有一个复制id\n4. 当前你所在的工单审核页面", inline=False)
        embed_req.add_field(name="三、小红书关注电波系", value="截图对电波系的关注😋需要有点赞留痕，可以直接给置顶帖子点赞", inline=False)
        embed_req.add_field(name="四、女性证明", value="在工单内发送语音，按照以下格式清晰朗读，审核编号是当前你所在工单频道名称里的6位数字：\n> 现在是xxxx年xx月xx日xx点xx分，我的审核编号是xxxxxx，我确保我是成年女性，并且已仔细阅读过社区守则，保证绝不违反，我会为自己的行为负责\n\n完成以上所有材料提交后，审核员会将你移至二审，届时你将进行自助答题验证~", inline=False)
        embed_req.set_footer(text="🚫 禁止对外泄露任何审核条件或试卷题目，违者直接做永久封禁处理")
        embed_req.set_image(url="https://files.catbox.moe/r269hz.png")
        
        # 2. 准备提醒消息和呼叫按钮
        reminder_description = (
            f"**尽量在12小时内提交哦！**超时需要重新申请工单。\n\n"
            f"你的审核编号为 `{ticket_id}`\n"
            f"你的Discord id为 `{interaction.user.id}`\n\n"
            f"准备好所有材料**并提交后**点击下方按钮艾特审核小蛋。"
        )
        reminder_embed = discord.Embed(description=reminder_description, color=STYLE["KIMI_YELLOW"])
        
        # 使用特定ID初始化视图
        notify_view = NotifyReviewerView(reviewer_id=SPECIFIC_REVIEWER_ID)

        # 3. 发送所有消息
        # 3.1: 发送初始欢迎和管理员操作面板（不包含接单按钮）
        await ticket_channel.send(content=f"{interaction.user.mention} {super_egg_role_mention}", embed=embed, view=TicketActionView())
        
        # 3.2: 发送审核要求
        await ticket_channel.send(f"你好呀 {interaction.user.mention}，请按下面的要求提交材料哦~", embed=embed_req)
        
        # 3.3: 发送呼叫按钮
        await ticket_channel.send(embed=reminder_embed, view=notify_view)
        
        # --- 修改结束 ---
        
        # --- 私信用户 ---
        dm_message = (f"你好呀！你在 **{interaction.guild.name}** 服务器的审核工单已经创建成功惹！\n\n"
                      f"➡️ **点击这里直接进入你的工单频道**: {ticket_channel.mention}\n\n"
                      f"请尽快前往频道查看审核要求哦！")
        dm_status_message = ""
        try:
            await interaction.user.send(dm_message)
            dm_status_message = "\n\n本大王已经把工单链接私信给你惹，记得查看哦！"
        except discord.Forbidden:
            dm_status_message = "\n\n**注意**: 你的私信关闭了，本大王没法把链接发给你！记得收藏好这个频道哦！"
        except Exception as e:
            print(f"私信用户 {interaction.user.name} 时出错: {e}")

        await interaction.followup.send(f"好惹！你的审核频道 {ticket_channel.mention} 已经创建好惹！审核要求已发送到频道内~ {dm_status_message}", ephemeral=True)

# ======================================================================================
# --- 工单系统的核心 Cog ---
# ======================================================================================

class Tickets(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(TicketActionView())
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(ArchiveRequestView())
        # 注册持久化视图时使用特定ID，确保重启后按钮有效
        self.bot.add_view(NotifyReviewerView(reviewer_id=SPECIFIC_REVIEWER_ID)) 
        print("唷呐！工单模块的永久视图已成功注册！")
        self.reset_daily_quota.start()
        self.check_inactive_tickets.start()
        self.close_tickets_at_night.start()

    @staticmethod
    def load_quota_data():
        try:
            with open(QUOTA["QUOTA_FILE_PATH"], 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"last_reset_date": "2000-01-01", "daily_quota_left": QUOTA["DAILY_TICKET_LIMIT"]}
    @staticmethod
    def save_quota_data(data):
        with open(QUOTA["QUOTA_FILE_PATH"], 'w') as f: json.dump(data, f, indent=4)
    async def update_ticket_panel(self):
        panel_channel = self.bot.get_channel(IDS["TICKET_PANEL_CHANNEL_ID"])
        if not panel_channel: 
            print("错误：找不到工单面板频道，无法更新！")
            return
        
        data = self.load_quota_data()
        now = datetime.datetime.now(QUOTA["TIMEZONE"])
        today_str = now.strftime('%Y-%m-%d')
        current_hour = now.hour
        quota_left = data.get("daily_quota_left", 0)
        
        embed = discord.Embed(title="🥚 新蛋身份审核", color=STYLE["KIMI_YELLOW"])
        description = "点击下方按钮，系统将为您自动开设单独的审核频道...\n\n"
        description += f"**-` 审核开放时间: 每日 08:00 - 23:00 `**\n"
        description += f"**-` {today_str} `**\n"
        daily_limit = QUOTA["DAILY_TICKET_LIMIT"]
        description += f"**-` 今日剩余名额: {quota_left}/{daily_limit} `**"
        
        embed.description = description
        view = TicketPanelView(self)

        # 核心修改：检查名额和时间
        if quota_left <= 0:
            view.children[0].disabled = True
            view.children[0].label = "今日名额已满"
        # 新增判断：如果时间不在 8点 到 22点 (23点前) 之间
        elif not (8 <= current_hour < 23):
            view.children[0].disabled = True
            view.children[0].label = "当前为休息时间"
            embed.description += "\n\n**当前为审核员休息时间，暂时无法创建工单哦~**"

        try:
            async for message in panel_channel.history(limit=5):
                if message.author == self.bot.user and message.embeds and "新蛋身份审核" in message.embeds[0].title:
                    await message.edit(embed=embed, view=view)
                    return
            await panel_channel.send(embed=embed, view=view)
        except Exception as e: print(f"更新工单面板时出错: {e}")

    @tasks.loop(time=datetime.time(hour=8, minute=0, tzinfo=QUOTA["TIMEZONE"]))
    async def reset_daily_quota(self):
        await self.bot.wait_until_ready()
        today_str = datetime.datetime.now(QUOTA["TIMEZONE"]).strftime('%Y-%m-%d')
        data = self.load_quota_data()
        if data["last_reset_date"] != today_str:
            print(f"[{datetime.datetime.now()}] 新的一天！重置每日审核额度...")
            data["last_reset_date"] = today_str
            data["daily_quota_left"] = QUOTA["DAILY_TICKET_LIMIT"]
            self.save_quota_data(data)
            await self.update_ticket_panel()
    
    @tasks.loop(time=datetime.time(hour=23, minute=0, tzinfo=QUOTA["TIMEZONE"]))
    async def close_tickets_at_night(self):
        """每晚23点准时运行，更新工单面板为关闭状态。"""
        await self.bot.wait_until_ready()
        print(f"[{datetime.datetime.now()}] 到达晚上23点，更新工单面板为关闭状态...")
        await self.update_ticket_panel()

    @tasks.loop(hours=1) 
    async def check_inactive_tickets(self):
        await self.bot.wait_until_ready()
        print(f"[{datetime.datetime.now()}] 幽灵管家开始巡逻检查沉睡的工单频道...")
        now = discord.utils.utcnow()
        archive_category = self.bot.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        if not archive_category or not isinstance(archive_category, discord.CategoryChannel):
            print("错误：找不到归档频道分类，自动归档任务跳过。")
            return
        categories_to_check_ids = [IDS["FIRST_REVIEW_CHANNEL_ID"], IDS["SECOND_REVIEW_CHANNEL_ID"]]
        for category_id in categories_to_check_ids:
            category = self.bot.get_channel(category_id)
            if not category or not isinstance(category, discord.CategoryChannel):
                print(f"警告：找不到ID为 {category_id} 的频道分类，跳过检查。")
                continue
            for channel in category.text_channels:
                if not ("待接单-" in channel.name or "一审中-" in channel.name or "二审中-" in channel.name):
                    continue
                try:
                    last_message = await channel.fetch_message(channel.last_message_id) if channel.last_message_id else None
                    last_activity_time = last_message.created_at if last_message else channel.created_at
                    if (now - last_activity_time) > datetime.timedelta(hours=12):
                        print(f"频道 '{channel.name}' 已沉睡超过12小时，准备归档...")
                        info = get_ticket_info(channel)
                        new_name = f"超时归档-{info.get('工单ID', '未知')}-{info.get('创建者', '未知')}"
                        await channel.send("呜...这个频道超过12小时没有新消息惹，本大王先把它归档保管起来咯！")
                        overwrites = {
                            channel.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                            channel.guild.get_role(IDS["SUPER_EGG_ROLE_ID"]): discord.PermissionOverwrite(read_messages=True)
                        }
                        await channel.edit(
                            name=new_name, 
                            category=archive_category, 
                            overwrites=overwrites,
                            reason="12小时无消息自动归档"
                        )
                except discord.Forbidden: print(f"呜...本大王没有权限操作频道 '{channel.name}'！")
                except discord.NotFound: print(f"警告：找不到频道 '{channel.name}' 的最后一条消息，跳过。")
                except Exception as e: print(f"检查频道 '{channel.name}' 时发生未知错误: {e}")

    ticket = discord.SlashCommandGroup("ticket", "工单相关指令")

    @ticket.command(name="超时归档", description="（超级小蛋用）将当前工单标记为超时，通知用户并删除。")
    @is_super_egg()
    async def timeout_archive(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        if not channel.topic or "工单ID" not in channel.topic:
            await ctx.followup.send("呜...这里似乎不是一个有效的工单频道（缺少工单Topic信息）！", ephemeral=True)
            return
        archive_log_channel = self.bot.get_channel(1419652525249794128)
        if not archive_log_channel:
            await ctx.followup.send("呜...找不到档案记录频道 `1419652525249794128`！请检查ID是否正确或机器人是否有权限查看。", ephemeral=True)
            return
        info = get_ticket_info(channel)
        ticket_id = info.get("工单ID", "未知编号")
        creator_name = info.get("创建者", "未知用户")
        creator_id_str = info.get("创建者ID")
        if not creator_id_str:
            await ctx.followup.send("呜...无法从此频道的Topic中解析出【创建者ID】，无法私信用户！", ephemeral=True)
            return
        log_message = f"{ticket_id}-{creator_name}因超时已归档"
        try: await archive_log_channel.send(log_message)
        except discord.Forbidden:
            await ctx.followup.send(f"呜...我没有权限在 {archive_log_channel.mention} 中发言！", ephemeral=True)
            return
        dm_message = "不好意思你在🔮LOFI-加载中申请的审核工单已超时，所以先做关闭处理惹😱如果还想要继续审核，欢迎宝宝重新申请~"
        try:
            creator = await self.bot.fetch_user(int(creator_id_str))
            await creator.send(dm_message)
            dm_status = "✅ 已成功私信用户。"
        except discord.NotFound: dm_status = f"❌ 找不到ID为 {creator_id_str} 的用户，无法私信。"
        except discord.Forbidden: dm_status = f"❌ 无法私信用户 {creator_name}，TA可能关闭了私信或屏蔽了我。"
        except Exception as e: dm_status = f"❌ 私信时发生未知错误: {e}"
        try: await channel.delete(reason=f"管理员 {ctx.author.name} 手动超时归档")
        except discord.Forbidden:
            await ctx.followup.send(f"呜...日志和私信都已处理，但我没有权限删除这个频道！请手动删除。\n{dm_status}", ephemeral=True)
            return
        await ctx.followup.send(f"操作成功！工单 `{ticket_id}-{creator_name}` 已作为超时处理并清除。\n{dm_status}", ephemeral=True)

    @ticket.command(name="删除并释放名额", description="（超级小蛋用）立即删除此工单，并将一个审核名额返还。")
    @is_super_egg()
    async def delete_and_refund(self, ctx: discord.ApplicationContext):
        confirm_view = discord.ui.View(timeout=30)
        confirm_button = discord.ui.Button(label="确认删除并返还名额", style=discord.ButtonStyle.danger)
        
        async def confirm_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("呜...只有发起命令的管理员才能确认哦！", ephemeral=True)
                return

            await interaction.response.defer()
            channel = interaction.channel
            if not channel.topic or "工单ID" not in channel.topic:
                await interaction.followup.send("呜...这里似乎不是一个有效的工单频道！", ephemeral=True)
                return

            data = self.load_quota_data()
            data["daily_quota_left"] += 1
            self.save_quota_data(data)
            await self.update_ticket_panel()

            try:
                await channel.delete(reason=f"管理员 {ctx.author.name} 删除并返还名额")
                log_channel = self.bot.get_channel(IDS.get("TICKET_LOG_CHANNEL_ID"))
                if log_channel:
                    await log_channel.send(f"✅ 管理员 **{ctx.author.name}** 删除了工单 `#{get_ticket_info(channel).get('工单ID', '未知')}` 并返还了一个名额。当前剩余名额: **{data['daily_quota_left']}**。")

            except discord.Forbidden:
                await ctx.author.send(f"呜哇！本大王没有权限删除频道 {channel.name}，但名额已经返还了！请手动删除该频道。")
            except Exception as e:
                await ctx.author.send(f"删除频道时发生错误: {e}，但名额已经返还了！请手动删除该频道。")

        confirm_button.callback = confirm_callback
        confirm_view.add_item(confirm_button)
        
        await ctx.respond("⚠️ **危险操作！**\n你确定要 **立即删除** 这个工单频道，并 **返还1个审核名额** 吗？此操作无法撤销！", view=confirm_view, ephemeral=True)

    @ticket.command(name="发送一审指引", description="（超级小蛋用）手动在当前频道发送一审指引。")
    @is_super_egg()
    async def send_first_review(self, ctx: discord.ApplicationContext):
        if not ctx.channel.topic or "工单ID" not in ctx.channel.topic:
            await ctx.respond("呜...这里似乎不是一个有效的工单频道！", ephemeral=True)
            return
        await ctx.defer()
        embed = discord.Embed(title="🔮 LOFI-加载中社区审核要求 【一审】", description="**⚠️ 请在审核时准备好以下材料**", color=STYLE["KIMI_YELLOW"])
        embed.add_field(name="一、成年证明（二选一）", value="1. 身份证**其余信息打码**，只露出身份证的__出生年月日__+__身份证号里出生年月日__部分\n2. 支付宝点击**我的-头像-我的档案-个人信息**，截图露出**生日**部分，其余信息打码", inline=False)
        embed.add_field(name="二、使用自建、非商业酒馆证明", value="准备好以下内容，让它们**同屏/同一张图显示**，如果在手机上显示不清/空间不够同屏，可以进行录屏：\n1. 你的酒馆后台（手机Termux、电脑Powershell/cmd、云酒馆1panel/宝塔/抱脸等）\n2. 一个超过100楼以上的女性向卡聊天记录，需要露出楼层编号和卡\n3. 在输入框内输入你的Discord id，格式为`Discord id：id数字`。\n> Discord id 获取方法:\n> 在设置里打开开发者模式-在聊天点击自己的头像-个人界面右上角三个点有一个复制id\n4. 当前你所在的工单审核页面", inline=False)
        embed.add_field(name="三、小红书关注电波系（可选，非强制）", value="截图对电波系的关注😋需要有点赞留痕，可以直接给置顶帖子点赞", inline=False)
        embed.add_field(name="四、女性证明", value="在工单内发送语音，按照以下格式清晰朗读，审核编号是当前你所在工单频道名称里的6位数字：\n> 现在是xxxx年xx月xx日xx点xx分，我的审核编号是xxxxxx，我确保我是成年女性，并且已仔细阅读过社区守则，保证绝不违反，我会为自己的行为负责\n\n完成以上所有材料提交后，审核员会将你移至二审，届时你将进行自助答题验证~", inline=False)
        embed.set_footer(text="🚫 禁止对外泄露任何审核条件或试卷题目，违者直接做永久封禁处理")
        embed.set_image(url="https://files.catbox.moe/r269hz.png")
        await ctx.send(f"你好呀！审核员 {ctx.author.mention} 已接单，请按下面的要求提交材料哦~", embed=embed)

    @ticket.command(name="发送二审指引", description="（超级小蛋用）手动在当前频道发送二审答题面板。")
    @is_super_egg()
    async def send_second_review(self, ctx: discord.ApplicationContext):
        if not ctx.channel.topic or "工单ID" not in ctx.channel.topic:
            await ctx.respond("呜...这里似乎不是一个有效的工单频道！", ephemeral=True)
            return
        
        await ctx.defer()
        
        info = get_ticket_info(ctx.channel)
        creator_id = int(info.get("创建者ID", 0))
        creator = ctx.guild.get_member(creator_id)
        
        embed = discord.Embed(
            title="🎯 二审答题验证",
            description="恭喜通过一审！现在需要完成身份确认答题~",
            color=STYLE["KIMI_YELLOW"]
        )
        embed.add_field(
            name="📝 答题说明",
            value=(
                "• 随机抽取10道题，每题10分，满分100分\n"
                "• 限时2分钟完成\n"
                "• 需要达到60分以上才能通过\n"
                "• 题目涉及基础酒馆知识和女性生活常识\n"
                "• **请认真作答，祝你好运！**"
            ),
            inline=False
        )
        embed.set_footer(text="准备好后，请点击下方按钮开始答题")
        
        if creator:
            await ctx.send(
                f"叮咚！{creator.mention} 小宝，请开始你的二审答题吧~",
                embed=embed,
                view=QuizStartView()
            )
        else:
            await ctx.send(embed=embed, view=QuizStartView())

    @ticket.command(name="发送过审祝贺", description="（超级小蛋用）手动在当前频道发送过审消息。")
    @is_super_egg()
    async def send_approved(self, ctx: discord.ApplicationContext):
        if not ctx.channel.topic or "工单ID" not in ctx.channel.topic:
            await ctx.respond("呜...这里似乎不是一个有效的工单频道！", ephemeral=True)
            return

        info = get_ticket_info(ctx.channel)
        creator_id = int(info.get("创建者ID", 0))
        creator = ctx.guild.get_member(creator_id)
        if not creator:
            await ctx.respond("呜...找不到这个工单的创建者了，TA可能已经离开服务器了...", ephemeral=True)
            return

        await ctx.defer()
        embed = discord.Embed(title="🥳 恭喜小宝加入社区", description="如果想来一起闲聊，社区有Q群可以来玩，进群问题也是填写你的【工单编号】就可以惹！\n## 对审核过程没有异议，同意并且阅读完全部东西后@当前审核员/任何超级小蛋来进行归档~身份组已经添加", color=STYLE["KIMI_YELLOW"])
        embed.set_image(url="https://files.catbox.moe/2tytko.jpg")
        embed.set_footer(text="宝宝如果已申请/不打算加群/没有别的问题了，请点击下方对应按钮")
        await ctx.send(f"恭喜 {creator.mention} 通过审核！", embed=embed, view=ArchiveRequestView(reviewer=ctx.author))

    @ticket.command(name="批量导出", description="（服主用）将已归档的过审频道打包成网页快照并删除！")
    @is_super_egg()
    async def bulk_export_and_archive(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        archive_category = self.bot.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        log_channel = self.bot.get_channel(IDS["TICKET_LOG_CHANNEL_ID"])
        if not archive_category: await ctx.followup.send("呜...找不到配置的【归档】分类！", ephemeral=True); return
        if not log_channel: await ctx.followup.send("呜...找不到存放日志的频道！", ephemeral=True); return
        await ctx.followup.send(f"收到！开始扫描 “{archive_category.name}” 中带 “已过审” 的频道...", ephemeral=True)
        exported_count = 0; channels_to_process = [ch for ch in archive_category.text_channels if "已过审" in ch.name]
        if not channels_to_process:
            await ctx.followup.send("在归档区没找到带“已过审”的频道哦~", ephemeral=True); return
        for channel in channels_to_process:
            try:
                html_template = """
                <!DOCTYPE html><html><head><title>Log for {channel_name}</title><meta charset="UTF-8"><style>
                body {{ background-color: #313338; color: #dbdee1; font-family: 'Whitney', 'Helvetica Neue', sans-serif; padding: 20px; }}
                .message-group {{ display: flex; margin-bottom: 20px; }} .avatar img {{ width: 40px; height: 40px; border-radius: 50%; margin-right: 20px; }}
                .message-content .author {{ font-weight: 500; color: #f2f3f5; }} .message-content .timestamp {{ font-size: 0.75rem; color: #949ba4; margin-left: 10px; }}
                .message-content .text {{ margin-top: 5px; line-height: 1.375rem; }} .attachment img {{ max-width: 400px; border-radius: 5px; margin-top: 10px; }}
                .embed {{ background-color: #2b2d31; border-left: 4px solid {embed_color}; padding: 10px; border-radius: 5px; margin-top: 10px; }}
                .embed-title {{ font-weight: bold; color: white; }} .embed-description {{ font-size: 0.9rem; }}
                </style></head><body><h1>工单日志: {channel_name}</h1>
                """
                html_content = html_template.format(channel_name=channel.name, embed_color=hex(STYLE['KIMI_YELLOW']).replace('0x', '#'))
                async for message in channel.history(limit=None, oldest_first=True):
                    message_text = message.clean_content.replace('\n', '<br>')
                    timestamp = message.created_at.astimezone(QUOTA["TIMEZONE"]).strftime('%Y-%m-%d %H:%M:%S')
                    html_content += f'<div class="message-group"><div class="avatar"><img src="{message.author.display_avatar.url}"></div>'
                    html_content += f'<div class="message-content"><span class="author">{message.author.display_name}</span><span class="timestamp">{timestamp}</span>'
                    html_content += f'<div class="text">{message_text}</div>'
                    for attachment in message.attachments:
                        if "image" in attachment.content_type: html_content += f'<div class="attachment"><img src="{attachment.url}"></div>'
                    for embed in message.embeds:
                        html_content += f'<div class="embed">'
                        if embed.title: html_content += f'<div class="embed-title">{embed.title}</div>'
                        if embed.description: 
                            description_text = embed.description.replace("\n", "<br>")
                            html_content += f'<div class="embed-description">{description_text}</div>'
                        html_content += '</div>'
                    html_content += '</div></div>'
                html_content += "</body></html>"
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.writestr(f'{channel.name}.html', html_content.encode('utf-8'))
                zip_buffer.seek(0)
                log_embed = discord.Embed(title="📦 批量导出日志", description=f"频道: `{channel.name}`", color=STYLE["KIMI_YELLOW"])
                await log_channel.send(embed=log_embed, file=discord.File(zip_buffer, filename=f"{channel.name}.zip"))
                await channel.delete(reason="批量导出并归档"); exported_count += 1; await asyncio.sleep(1)
            except Exception as e:
                print(f"批量导出频道 {channel.name} 时出错: {e}"); await log_channel.send(f"❌ 导出频道 `{channel.name}` 时出错: {e}")
        await ctx.followup.send(f"批量导出完成！成功处理了 **{exported_count}/{len(channels_to_process)}** 个频道！", ephemeral=True)

    quota_mg = discord.SlashCommandGroup("名额管理", "（仅限超级小蛋）手动调整工单名额~", checks=[is_super_egg()])
    @quota_mg.command(name="重置", description="将今天的剩余名额恢复到最大值！")
    async def reset_quota(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True); data = self.load_quota_data(); daily_limit = QUOTA["DAILY_TICKET_LIMIT"]; data["daily_quota_left"] = daily_limit; self.save_quota_data(data); await self.update_ticket_panel()
        await ctx.followup.send(f"好惹！今天的剩余名额已经被本大王恢复到 **{daily_limit}** 个！✨", ephemeral=True)
    @quota_mg.command(name="设置", description="手动设置今天的剩余名额数量！")
    async def set_quota(self, ctx: discord.ApplicationContext, amount: discord.Option(int, "要设置的剩余名额数量", required=True)):
        await ctx.defer(ephemeral=True)
        if amount < 0: await ctx.followup.send("呜...名额不能是负数啦！", ephemeral=True); return
        data = self.load_quota_data(); data["daily_quota_left"] = amount; self.save_quota_data(data); await self.update_ticket_panel()
        await ctx.followup.send(f"遵命！今天的剩余名额已经被本大王设置为 **{amount}** 个！🫡", ephemeral=True)
    @quota_mg.command(name="增加", description="给今天的剩余名额增加指定数量！")
    async def add_quota(self, ctx: discord.ApplicationContext, amount: discord.Option(int, "要增加的名额数量", required=True)):
        await ctx.defer(ephemeral=True)
        if amount <= 0: await ctx.followup.send("呜...要增加的数量必须大于0嘛！", ephemeral=True); return
        data = self.load_quota_data(); data["daily_quota_left"] += amount; self.save_quota_data(data); await self.update_ticket_panel()
        await ctx.followup.send(f"好嘞！本大王刚刚变出了 **{amount}** 个新名额，现在还剩 **{data['daily_quota_left']}** 个！", ephemeral=True)

    @discord.slash_command(name="setup_ticket_panel", description="（仅限超级小蛋）手动发送或刷新工单创建面板！")
    @is_super_egg()
    async def setup_ticket_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        channel = self.bot.get_channel(IDS["TICKET_PANEL_CHANNEL_ID"])
        if channel:
            await channel.purge(limit=100)
            await self.update_ticket_panel()
            await ctx.followup.send("工单创建面板已经成功刷新惹！✨", ephemeral=True)
        else:
            await ctx.followup.send("呜...找不到放置工单面板的频道！", ephemeral=True)

def setup(bot):
    bot.add_cog(Tickets(bot))
