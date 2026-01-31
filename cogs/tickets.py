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

# ======================================================================================
# --- 常量定义 ---
# ======================================================================================

# 指定的审核员ID (审核小蛋)
SPECIFIC_REVIEWER_ID = 1452321798308888776

# 超时设置 (小时)
TIMEOUT_HOURS_ARCHIVE = 12
TIMEOUT_HOURS_REMIND = 6

# ======================================================================================
# --- 权限与工具函数 ---
# ======================================================================================

def is_reviewer_egg():
    """权限检查：判断命令使用者是否为指定的【审核小蛋】"""
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        # 1. 防止在私信中使用导致 ctx.guild 为 None
        if not ctx.guild:
            await ctx.respond("该命令只能在服务器中使用。", ephemeral=True)
            return False

        # 2. 直接检查用户ID
        if ctx.author.id == SPECIFIC_REVIEWER_ID:
            return True
        
        # 3. 检查身份组
        super_egg_role = ctx.guild.get_role(IDS.get("SUPER_EGG_ROLE_ID", 0))
        if super_egg_role and super_egg_role in ctx.author.roles:
            return True
            
        await ctx.respond("呜...这个是【审核小蛋】专属嘟魔法，你还不能用捏！QAQ", ephemeral=True)
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
# --- 辅助逻辑与交互视图 (Modal/View) ---
# ======================================================================================

async def execute_timeout_archive(cog, interaction, channel, note):
    """封装好的归档逻辑，供 弹窗 和 按钮 共同调用"""
    info = get_ticket_info(channel)
    ticket_id = info.get("工单ID", "未知")
    creator_id = info.get("创建者ID")
    creator_name = info.get("创建者", "未知用户")

    # 1. 记录日志
    archive_log_channel = cog.bot.get_channel(IDS.get("TICKET_LOG_CHANNEL_ID"))
    if not archive_log_channel:
         archive_log_channel = cog.bot.get_channel(1419652525249794128)

    log_content = (
        f"🚫 **超时归档 (右键强制)**\n"
        f"工单: `{ticket_id}`\n"
        f"用户: `{creator_name}` (`{creator_id}`)\n"
        f"操作人: {interaction.user.mention}\n"
        f"📝 **备注**: {note}"
    )
    if archive_log_channel: 
        await archive_log_channel.send(log_content)
    
    # 2. 私信通知用户
    if creator_id:
        try:
            user = await cog.bot.fetch_user(int(creator_id))
            dm_content = (
                f"不好意思，你在🔮LOFI-加载中申请的审核工单 `{ticket_id}` 已超时，"
                f"且管理员判定需关闭。\n"
                f"备注: {note}\n"
                f"工单现已关闭，欢迎准备好材料后重新申请~"
            )
            await user.send(dm_content)
        except Exception: pass
        
    # 3. 反馈并删除
    try:
        await interaction.response.send_message(f"✅ 已处理工单 `{ticket_id}` (备注: {note})，正在删除...", ephemeral=True)
    except:
        await interaction.followup.send(f"✅ 已处理工单 `{ticket_id}` (备注: {note})，正在删除...", ephemeral=True)
        
    await channel.delete(reason=f"右键超时归档: {note} - {interaction.user.name}")


class TimeoutNoteModal(discord.ui.Modal):
    def __init__(self, cog, channel):
        super().__init__(title="填写归档备注")
        self.cog = cog
        self.channel = channel
        self.add_item(discord.ui.InputText(
            label="备注内容",
            placeholder="请输入超时归档的原因...",
            style=discord.InputTextStyle.paragraph,
            required=True 
        ))

    async def callback(self, interaction: discord.Interaction):
        note = self.children[0].value
        await execute_timeout_archive(self.cog, interaction, self.channel, note)


class TimeoutOptionView(discord.ui.View):
    def __init__(self, cog, channel):
        super().__init__(timeout=60)
        self.cog = cog
        self.channel = channel

    # 使用 arg1, arg2 自动适配
    @discord.ui.button(label="📝 填写备注并归档", style=discord.ButtonStyle.primary)
    async def note_archive(self, arg1, arg2):
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        await interaction.response.send_modal(TimeoutNoteModal(self.cog, self.channel))

    @discord.ui.button(label="🚀 直接归档 (无备注)", style=discord.ButtonStyle.danger)
    async def quick_archive(self, arg1, arg2):
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        await execute_timeout_archive(self.cog, interaction, self.channel, note="无 (管理员选择直接归档)")

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, arg1, arg2):
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        await interaction.response.edit_message(content="操作已取消。", view=None)

# ======================================================================================
# --- 工单系统的常规交互视图 (Views) ---
# ======================================================================================

class ArchiveRequestView(discord.ui.View):
    def __init__(self, reviewer: discord.Member = None):
        super().__init__(timeout=None)
        self.reviewer = reviewer

    async def button_callback(self, interaction: discord.Interaction, choice: str):
        await interaction.response.defer()
        original_embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if original_embed:
            original_embed.color = 0x00FF00
            original_embed.set_footer(text=f"✅ 用户已选择：{choice}")
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=original_embed, view=self)
        
        notify_text = f"📢 {interaction.user.mention} 选择了：**{choice}**\n\n"
        reviewer_mention = f"<@&{SPECIFIC_REVIEWER_ID}>"
        if self.reviewer and self.reviewer.id != SPECIFIC_REVIEWER_ID:
            reviewer_mention = f"{self.reviewer.mention} {reviewer_mention}"
        notify_text += f"{reviewer_mention}，这位小饱饱已经确认完毕，可以进行归档操作啦！"
        await interaction.channel.send(notify_text)

    # 自动适配参数
    @discord.ui.button(label="已申请加群", style=discord.ButtonStyle.primary, custom_id="req_archive_1")
    async def applied(self, arg1, arg2): 
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        await self.button_callback(interaction, "已申请加群")

    @discord.ui.button(label="不打算加群，没有别的问题了", style=discord.ButtonStyle.secondary, custom_id="req_archive_2")
    async def no_problem(self, arg1, arg2): 
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        await self.button_callback(interaction, "不打算加群，没有别的问题了")

class NotifyReviewerView(discord.ui.View):
    def __init__(self, reviewer_id: int):
        super().__init__(timeout=None)
        self.reviewer_id = reviewer_id

    # 自动适配参数
    @discord.ui.button(label="✅ 材料已备齐，呼叫审核小蛋", style=discord.ButtonStyle.primary, custom_id="notify_reviewer_button")
    async def notify_reviewer(self, arg1, arg2):
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        button = arg1 if isinstance(arg1, discord.ui.Button) else arg2

        ticket_info = get_ticket_info(interaction.channel)
        creator_id = ticket_info.get("创建者ID")
        if str(interaction.user.id) != creator_id:
            await interaction.response.send_message("呜...只有创建这个工单的饱饱才能呼叫审核员哦！", ephemeral=True)
            return
        button.disabled = True
        button.label = "✅ 已呼叫审核小蛋"
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"<@&{self.reviewer_id}> 小饱饱的材料准备好啦，快来看看吧！")

class TicketActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "ticket_approved":
                    child.disabled = True
                    child.style = discord.ButtonStyle.secondary
                elif child.custom_id == "ticket_archive":
                    child.disabled = True
                    child.style = discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == SPECIFIC_REVIEWER_ID:
            return True
        super_egg_role = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
        if super_egg_role and super_egg_role in interaction.user.roles:
            return True
        await interaction.response.send_message("呜...只有【审核小蛋】才能操作审核按钮哦！", ephemeral=True)
        return False

    # 自动适配参数
    @discord.ui.button(label="🎉 已过审", style=discord.ButtonStyle.success, custom_id="ticket_approved")
    async def approved(self, arg1, arg2):
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        button = arg1 if isinstance(arg1, discord.ui.Button) else arg2

        info = get_ticket_info(interaction.channel)
        creator_id = int(info.get("创建者ID", 0))
        creator = interaction.guild.get_member(creator_id)
        
        # 1. 修改身份组逻辑
        if creator:
            newbie_role = interaction.guild.get_role(IDS["VERIFICATION_ROLE_ID"])
            hatched_role = interaction.guild.get_role(IDS["HATCHED_ROLE_ID"])
            try:
                if newbie_role: await creator.remove_roles(newbie_role, reason="审核通过")
                if hatched_role: await creator.add_roles(hatched_role, reason="审核通过")
            except discord.Forbidden:
                await interaction.response.send_message("呜哇！本大王没有权限修改身份组！", ephemeral=True)
                return
            
            # --- ✨ 发送过审私信提醒 ✨ ---
            try:
                dm_embed = discord.Embed(
                    title="🎉 恭喜！审核通过啦！",
                    description=(
                        f"你好呀 **{creator.name}**！\n"
                        f"你在 **{interaction.guild.name}** 的新蛋身份审核已经**通过**惹！✨\n\n"
                        f"✅ 身份组已经自动发放，现在可以在社区里自由玩耍咯！\n"
                        f"📝 **请回到工单频道完成最后的归档确认步骤哦~**"
                    ),
                    color=STYLE["KIMI_YELLOW"]
                )
                if interaction.guild.icon:
                    dm_embed.set_thumbnail(url=interaction.guild.icon.url)
                
                dm_embed.add_field(name="🔗 前往工单频道", value=interaction.channel.mention, inline=False)
                
                await creator.send(embed=dm_embed)
            except discord.Forbidden:
                print(f"用户 {creator.name} 关闭了私信，无法发送过审通知。")
            except Exception as e:
                print(f"发送过审私信时发生未知错误: {e}")
            # -------------------------------------

        embed = discord.Embed(title="🥳 恭喜小宝加入社区", description="如果想来一起闲聊，社区有Q群可以来玩...\n## 对审核过程没有异议，同意并且阅读完全部东西后请点击下方按钮~", color=STYLE["KIMI_YELLOW"])
        embed.set_image(url="https://i.postimg.cc/sxh3MQkh/2tytko.png")
        embed.set_footer(text="宝宝如果已申请/不打算加群且没有别的问题了，请点击下方对应按钮")
        msg_content = f"恭喜 {creator.mention} 通过审核！" if creator else "恭喜通过审核！(用户已不在服务器)"
        await interaction.channel.send(msg_content, embed=embed, view=ArchiveRequestView(reviewer=interaction.user))

        button.disabled = True
        button.style = discord.ButtonStyle.secondary
        for child in self.children:
            if child.custom_id == "ticket_archive":
                child.disabled = False
                child.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    # 自动适配参数
    @discord.ui.button(label="📦 工单归档", style=discord.ButtonStyle.secondary, custom_id="ticket_archive")
    async def archive(self, arg1, arg2):
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        button = arg1 if isinstance(arg1, discord.ui.Button) else arg2

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
            prefix = "已过审" if is_approved else "未通过"
            new_name = f"{prefix}-{info.get('工单ID', '未知')}-{info.get('创建者', '未知')}"

            specific_reviewer = interaction.guild.get_member(SPECIFIC_REVIEWER_ID)
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            }
            if specific_reviewer:
                overwrites[specific_reviewer] = discord.PermissionOverwrite(read_messages=True)
            super_egg_role = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
            if super_egg_role:
                 overwrites[super_egg_role] = discord.PermissionOverwrite(read_messages=True)

            await channel.edit(name=new_name, category=archive_category, overwrites=overwrites, reason="管理员手动归档")
            await interaction.followup.send("工单已成功归档并锁定！✨", ephemeral=True)

        except discord.Forbidden:
            await channel.send("❌ **归档失败！** 呜哇！本大王没有权限移动或修改这个频道！")
        except Exception as e:
            await channel.send(f"❌ **归档失败！** 发生未知错误: {e}")

class TicketPanelView(discord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    # 自动适配参数
    @discord.ui.button(label="🥚 申请全区权限", style=discord.ButtonStyle.primary, custom_id="create_ticket_panel_button")
    async def create_ticket_callback(self, arg1, arg2):
        interaction = arg1 if isinstance(arg1, discord.Interaction) else arg2
        button = arg1 if isinstance(arg1, discord.ui.Button) else arg2

        if self.cog.audit_suspended_until:
            now = datetime.datetime.now()
            if self.cog.audit_suspended_until == "infinite" or now < self.cog.audit_suspended_until:
                reason = self.cog.audit_suspend_reason or "管理员暂停了审核功能"
                until_str = "恢复时间待定" if self.cog.audit_suspended_until == "infinite" else f"预计 {self.cog.audit_suspended_until.strftime('%H:%M')} 恢复"
                await interaction.response.send_message(f"🚫 **审核通道已暂时关闭**\n原因：{reason}\n{until_str}", ephemeral=True)
                return

        # --- 时间检查 ---
        now = datetime.datetime.now(QUOTA["TIMEZONE"])
        if not (8 <= now.hour < 23):
            await interaction.response.send_message("呜...现在是审核员的休息时间 (08:00 - 23:00)，请在开放时间内再来申请哦！", ephemeral=True)
            return

        user_roles = [role.id for role in interaction.user.roles]
        is_specific_reviewer = interaction.user.id == SPECIFIC_REVIEWER_ID
        if IDS["VERIFICATION_ROLE_ID"] not in user_roles and IDS["SUPER_EGG_ROLE_ID"] not in user_roles and not is_specific_reviewer:
            await interaction.response.send_message(f"呜...只有【新兵蛋子】或【审核小蛋】才能创建审核工单哦！", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)

        # --- 获取分类并检查容量 (修复报错的核心) ---
        first_review_category = interaction.guild.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"])
        if not first_review_category or not isinstance(first_review_category, discord.CategoryChannel):
             await interaction.followup.send("呜...找不到【一审】的频道分类！请服主检查配置！", ephemeral=True)
             return
             
        # 检查分类下的频道数量是否已达上限 (Discord限制为50个)
        if len(first_review_category.channels) >= 50:
            await interaction.followup.send("🚫 **无法创建工单**\n呜...当前的审核队列（一审分类）已经满了（50/50）！\n请联系管理员清理或归档旧的工单后再试。", ephemeral=True)
            return

        # --- 检查用户是否已有工单 ---
        second_review_category = interaction.guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        categories_to_check = [cat for cat in [first_review_category, second_review_category] if cat]
        for category in categories_to_check:
            for channel in category.text_channels:
                if channel.topic and f"创建者ID: {interaction.user.id}" in channel.topic:
                    await interaction.followup.send(f"呜...你已经有一个正在处理的工单 {channel.mention} 惹！请不要重复创建哦~", ephemeral=True)
                    return

        data = self.cog.load_quota_data()
        if data["daily_quota_left"] <= 0:
            await interaction.followup.send("呜...今天的新蛋审核名额已经用完惹，请明天再来吧！", ephemeral=True)
            return
            
        data["daily_quota_left"] -= 1
        self.cog.save_quota_data(data)
        await self.cog.update_ticket_panel()
        
        ticket_channel = None
        try:
            ticket_id = random.randint(100000, 999999)
            channel_name = f"一审中-{ticket_id}-{interaction.user.name}"

            specific_reviewer = interaction.guild.get_member(SPECIFIC_REVIEWER_ID)
            
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            if specific_reviewer:
                overwrites[specific_reviewer] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            super_egg_role = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
            if super_egg_role:
                 overwrites[super_egg_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

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
            else:
                await interaction.followup.send(f"呜...创建工单时发生了未知错误，请联系服主查看后台日志！", ephemeral=True)

            data["daily_quota_left"] += 1
            self.cog.save_quota_data(data)
            await self.cog.update_ticket_panel()
            return

        embed = discord.Embed(title=f"🎫 工单 #{ticket_id} 已创建", description=f"饱饱你好呀！请按照审核要求提交相关材料哦~\n**准备好材料后在本频道直接发送即可**", color=STYLE["KIMI_YELLOW"])
        mention_text = f"<@&{SPECIFIC_REVIEWER_ID}>"
        await ticket_channel.send(content=f"{interaction.user.mention} {mention_text}", embed=embed, view=TicketActionView())
        
        embed_req = discord.Embed(title="🔮 LOFI-加载中社区审核要求", description="**⚠️ 请在审核时准备好以下材料**", color=STYLE["KIMI_YELLOW"])
        embed_req.add_field(name="一、成年&女性证明（二选一）", value="1. 身份证**其余信息打码**，只露出身份证的__出生年月日__+__身份证号里出生年月日__+__性别__部分\n2. 支付宝点击**我的-头像-我的档案-个人信息**，截图露出**生日+性别**部分，其余信息打码", inline=False)
        embed_req.add_field(name="二、使用自建、非商业酒馆证明", value="准备好以下内容，让它们**同屏/同一张图显示**，如果在手机上显示不清/空间不够同屏，可以进行录屏：\n1. 你的酒馆后台（手机Termux、电脑Powershell/cmd、云酒馆1panel/宝塔/抱脸等）\n2. 一个超过100楼以上的女性向卡聊天记录，需要露出楼层编号和卡\n3. 在输入框内输入你的Discord id，格式为`Discord id：id数字`。\n> Discord id 获取方法:\n> 在设置里打开开发者模式-在聊天点击自己的头像-个人界面右上角有一个复制id\n4. 当前你所在的工单审核页面", inline=False)
        embed_req.add_field(name="三、小红书关注电波系", value="截图对电波系的关注，需要有点赞留痕", inline=False)
        embed_req.add_field(name="四、语音证明", value="在工单内发送语音（电脑端可以先在手机录制，然后发送文件），按照以下格式清晰朗读，审核编号是当前你所在工单频道名称里的6位数字：\n> 现在是xxxx年xx月xx日xx点xx分，我的审核编号是xxxxxx，我确保我是成年女性，并且已仔细阅读过社区守则，保证绝不违反，我会为自己的行为负责", inline=False)
        embed_req.set_footer(text="🚫 禁止对外泄露任何审核条件或试卷题目，违者直接做永久封禁处理")
        embed_req.set_image(url="https://i.postimg.cc/MGpMv5dr/r269hz.png")
        
        await ticket_channel.send(f"你好呀 {interaction.user.mention}，请按下面的要求提交材料哦~", embed=embed_req)
        
        # 3. 发送提醒和呼叫按钮
        reminder_description = (
            f"**尽量在12小时内提交哦！**超时需要重新申请工单。\n\n"
            f"你的审核编号为 `{ticket_id}`\n"
            f"你的Discord id为 `{interaction.user.id}`\n\n"
            f"准备好所有材料**并在本频道完全提交后**点击下方按钮艾特审核小蛋。"
        )
        reminder_embed = discord.Embed(description=reminder_description, color=STYLE["KIMI_YELLOW"])
        notify_view = NotifyReviewerView(reviewer_id=SPECIFIC_REVIEWER_ID)
        await ticket_channel.send(embed=reminder_embed, view=notify_view)
        
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
    def __init__(self, bot):
        self.bot = bot
        # 审核暂停状态
        self.audit_suspended = False
        self.audit_suspended_until = None # None: 正常, "infinite": 无限暂停, datetime: 暂停截止时间
        self.audit_suspend_reason = None

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(TicketActionView())
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(ArchiveRequestView())
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
        
        embed = discord.Embed(title="🥚 全区权限申请 (人工审核)", color=STYLE["KIMI_YELLOW"])
        description = (
            "**在创建工单前，请您仔细阅读并确认遵守以下社区核心原则：**\n\n"
            "1.  **社区定位**：我们是 **非商业化SillyTavern女性社区**，仅欢迎有酒馆使用经验的同好加入。\n"
            "2.  **资源使用**：社区内所有资源、技术与讨论，**严禁**用于商业云酒馆、付费服务或Tavo、Omate等第三方软件。\n"
            "3.  **反商业化**：我们坚决反对任何形式的商业化行为，请勿在社区内推荐或使用非官方的付费API、付费节点等服务。\n\n"
            "----------------------------------------------------\n"
            "未通过审核的用户仅能浏览有限的公共频道。如您已阅读并同意以上所有条款，请点击下方按钮创建工单以验证身份、解锁全部内容。\n\n"
            f"**⚠️ 前置要求：需先拥有【新兵蛋子】身份 (请先去答题)**\n"
            f"**-` 审核开放时间: 每日 08:00 - 23:00 `**\n"
            f"**-` 今日剩余名额: {quota_left}/{QUOTA['DAILY_TICKET_LIMIT']} `**"
        )

        
        embed.description = description
        view = TicketPanelView(self)

        # 按钮状态控制
        if self.audit_suspended:
            view.children[0].disabled = False # 让用户点，点了之后弹窗提示原因
            view.children[0].label = "⚠️ 审核暂停中"
        elif quota_left <= 0:
            view.children[0].disabled = True
            view.children[0].label = "今日名额已满"
        elif not (8 <= current_hour < 23):
            view.children[0].disabled = True
            view.children[0].label = "当前为休息时间"
            embed.description += "\n\n**当前为审核员休息时间，暂时无法创建工单哦~**"

        try:
            async for message in panel_channel.history(limit=5):
                if message.author == self.bot.user and message.embeds and "全区权限申请" in message.embeds[0].title:
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
        await self.bot.wait_until_ready()
        print(f"[{datetime.datetime.now()}] 到达晚上23点，更新工单面板为关闭状态...")
        await self.update_ticket_panel()

    # --- 超时检测与提醒 ---
    @tasks.loop(hours=1) 
    async def check_inactive_tickets(self):
        await self.bot.wait_until_ready()
        print(f"[{datetime.datetime.now()}] 幽灵管家开始巡逻检查沉睡的工单频道...")
        now = discord.utils.utcnow()
        archive_category = self.bot.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        if not archive_category: return

        categories_to_check_ids = [IDS["FIRST_REVIEW_CHANNEL_ID"], IDS["SECOND_REVIEW_CHANNEL_ID"]]
        
        for category_id in categories_to_check_ids:
            category = self.bot.get_channel(category_id)
            if not category: continue
            
            guild = category.guild
            specific_reviewer = guild.get_member(SPECIFIC_REVIEWER_ID)
            super_egg_role = guild.get_role(IDS["SUPER_EGG_ROLE_ID"])

            for channel in category.text_channels:
                # 过滤掉不相关的频道，只检查工单
                if not ("待接单-" in channel.name or "一审中-" in channel.name or "二审中-" in channel.name):
                    continue
                
                try:
                    # 获取工单信息
                    info = get_ticket_info(channel)
                    creator_id = info.get('创建者ID')
                    ticket_id = info.get('工单ID', '未知')

                    # 1. 获取最后一条消息（用于判断状态）
                    last_msg = None
                    async for msg in channel.history(limit=1):
                        last_msg = msg
                        break
                    
                    if not last_msg: continue # 空频道跳过

                    # ------------------------------------------------------------------
                    # 🌟 新增逻辑：检查是否为“已过审但未确认”状态 (3小时超时)
                    # ------------------------------------------------------------------
                    is_approved_waiting = False
                    if last_msg.author.id == self.bot.user.id and last_msg.embeds:
                        embed_title = last_msg.embeds[0].title or ""
                        if "恭喜小宝加入社区" in embed_title:
                            is_approved_waiting = True
                    
                    time_diff = now - last_msg.created_at

                    if is_approved_waiting:
                        # 如果处于等待确认状态，且超过 3 小时
                        if time_diff > datetime.timedelta(hours=3):
                            print(f"频道 '{channel.name}' 已过审但用户3小时未操作，执行自动归档...")
                            
                            # 1. 发送频道通知
                            await channel.send("⏳ **自动归档**\n检测到宝宝通过审核后超过 **3小时** 未点击确认按钮。\n为节省资源，本大王已自动帮你完成归档流程啦！(身份组已发放，不影响正常游玩)")
                            
                            # 2. 尝试私信用户
                            if creator_id:
                                try:
                                    member = await guild.fetch_member(int(creator_id))
                                    dm_embed = discord.Embed(
                                        title="📦 工单自动归档通知",
                                        description=(
                                            f"你好呀！你在 **{guild.name}** 的审核工单 `#{ticket_id}` 已经通过审核。\n"
                                            "由于你超过 **3小时** 没有点击最后的确认按钮，本大王已经帮你自动归档啦！\n\n"
                                            "✅ **你的身份组已经正常发放，不影响在社区内玩耍哦！**"
                                        ),
                                        color=STYLE["KIMI_YELLOW"]
                                    )
                                    await member.send(embed=dm_embed)
                                except: pass

                            # 3. 执行归档移动
                            new_name = f"已过审-{ticket_id}-{info.get('创建者', '未知')}"
                            
                            overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False)}
                            if specific_reviewer: overwrites[specific_reviewer] = discord.PermissionOverwrite(read_messages=True)
                            if super_egg_role: overwrites[super_egg_role] = discord.PermissionOverwrite(read_messages=True)

                            await channel.edit(name=new_name, category=archive_category, overwrites=overwrites, reason="已过审3小时无响应自动归档")
                            continue # 处理完这个特殊情况后，跳过后续的常规检查

                    # ------------------------------------------------------------------
                    # 🌟 原有逻辑：常规活动超时 (12小时归档 / 6小时提醒)
                    # ------------------------------------------------------------------
                    
                    # 重新计算最后有效活动时间（排除机器人的提醒消息）
                    last_active_time = channel.created_at
                    has_already_reminded = False
                    
                    async for msg in channel.history(limit=20):
                        if msg.author.bot:
                            # 如果是提醒消息，标记已提醒
                            if "温馨提醒" in msg.content or (msg.embeds and "温馨提醒" in (msg.embeds[0].title or "")):
                                has_already_reminded = True
                        else:
                            # 找到用户或管理员的发言，视为有效活动
                            last_active_time = msg.created_at
                            break
                    
                    time_diff_active = now - last_active_time

                    # 2. 检查是否超过 12 小时 (常规归档)
                    if time_diff_active > datetime.timedelta(hours=TIMEOUT_HOURS_ARCHIVE):
                        print(f"频道 '{channel.name}' 超过{TIMEOUT_HOURS_ARCHIVE}小时无有效活动，执行归档...")
                        new_name = f"超时归档-{ticket_id}-{info.get('创建者', '未知')}"
                        
                        await channel.send(f"呜...这个频道超过{TIMEOUT_HOURS_ARCHIVE}小时没有动静惹，本大王先把它归档保管起来咯！")
                        
                        overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False)}
                        if specific_reviewer: overwrites[specific_reviewer] = discord.PermissionOverwrite(read_messages=True)
                        if super_egg_role: overwrites[super_egg_role] = discord.PermissionOverwrite(read_messages=True)

                        await channel.edit(name=new_name, category=archive_category, overwrites=overwrites, reason="超时自动归档")
                        
                        if creator_id:
                            try:
                                member = await guild.fetch_member(int(creator_id))
                                await member.send(f"你的工单 `{ticket_id}` 因超过{TIMEOUT_HOURS_ARCHIVE}小时未活动已被归档。如需继续请重新创建工单哦！")
                            except: pass

                    # 3. 检查是否超过 6 小时 (提醒)
                    elif time_diff_active > datetime.timedelta(hours=TIMEOUT_HOURS_REMIND) and not has_already_reminded:
                        # 确保不是“已过审”状态才催促（已过审的走上面的3小时逻辑）
                        if not is_approved_waiting:
                            print(f"频道 '{channel.name}' 超过{TIMEOUT_HOURS_REMIND}小时无有效活动，发送首次提醒...")
                            
                            mention_str = ""
                            if creator_id:
                                mention_str = f"<@{creator_id}>"
                                try:
                                    member = await guild.fetch_member(int(creator_id))
                                    await member.send(f"👋 饱饱，你的审核工单 `{ticket_id}` 已经{TIMEOUT_HOURS_REMIND}小时没有变动了哦！如果材料准备好了请尽快提交，超过{TIMEOUT_HOURS_ARCHIVE}小时会自动关闭工单哒！")
                                except: pass
                            
                            embed = discord.Embed(title="⏰ 温馨提醒", description=f"工单已经沉睡超过 **{TIMEOUT_HOURS_REMIND}小时** 啦！\n请注意：**超过{TIMEOUT_HOURS_ARCHIVE}小时无响应** 将会自动归档哦！\n如果需要审核，请尽快回复~", color=0xFFA500)
                            await channel.send(content=mention_str, embed=embed)

                except Exception as e:
                    print(f"检查频道 '{channel.name}' 时发生错误: {e}")

    # ======================================================================================
    # --- 命令组定义 ---
    # ======================================================================================

    ticket = discord.SlashCommandGroup("工单", "工单相关指令")

    @ticket.command(name="中止新蛋审核", description="（管理员）设置中止工单申请，可设置时长和原因。")
    @is_reviewer_egg()
    async def suspend_audit(self, ctx: discord.ApplicationContext,
                            duration: discord.Option(str, "中止时长 (例如 1h, 30m, 留空或inf为无限期)", required=False) = None,
                            reason: discord.Option(str, "中止原因 (会显示在公告中)", default="管理员正在进行系统维护") = None):
        """
        管理员中止审核。
        如果 duration 为空或 inf，则是无限期，直到手动解除（暂未实现手动解除，可重启或重新设一个短时间）。
        """
        await ctx.defer(ephemeral=True)
        
        self.audit_suspended = True
        self.suspend_reason = reason
        
        msg = f"✅ 已中止审核功能。\n原因：{reason}\n"
        
        if duration and duration.lower() != "inf":
            seconds = parse_duration(duration)
            if seconds > 0:
                self.suspend_end_time = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
                msg += f"预计恢复时间：{duration} 后"
                # 启动自动恢复任务
                self.bot.loop.create_task(self.auto_resume_audit(seconds))
            else:
                self.suspend_end_time = None
                msg += "时长格式无法识别，默认为无限期中止。"
        else:
            self.suspend_end_time = None
            msg += "时长：无限期 (直到重启或手动恢复)"

        await self.update_ticket_panel()
        
        # 发送公告到工单面板频道
        panel_channel = self.bot.get_channel(IDS["TICKET_PANEL_CHANNEL_ID"])
        if panel_channel:
            embed = discord.Embed(title="📢 审核暂停公告", description=f"因 **{reason}**，审核功能暂时关闭。", color=0xFF0000)
            if self.suspend_end_time:
                embed.add_field(name="预计恢复", value=f"<t:{int(self.suspend_end_time.timestamp())}:R>")
            await panel_channel.send(embed=embed)
            
        await ctx.followup.send(msg, ephemeral=True)

    async def auto_resume_audit(self, seconds):
        await asyncio.sleep(seconds)
        self.audit_suspended = False
        self.suspend_reason = None
        self.suspend_end_time = None
        await self.update_ticket_panel()

    @ticket.command(name="恢复工单状态", description="（审核小蛋用）误操作恢复！将工单恢复到指定状态并通知用户。")
    @is_reviewer_egg()
    async def recover_ticket(self, ctx: discord.ApplicationContext,
                             state: discord.Option(str, "选择恢复到的状态", choices=["一审中", "二审中", "已过审", "归档", "超时归档"]),
                             reason: discord.Option(str, "给用户的解释（会私信发送）", required=False, default="管理员手动调整了工单状态。")):
        """
        核心恢复功能：
        1. 识别当前频道信息
        2. 根据选择的状态，移动分类、重命名、重置权限
        3. 发送 DM 通知用户
        """
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        
        # 1. 获取工单信息
        info = get_ticket_info(channel)
        if not info or "工单ID" not in info:
            await ctx.followup.send("❌ 这里似乎不是一个有效的工单频道（无法读取Topic信息）！", ephemeral=True)
            return

        ticket_id = info.get("工单ID", "未知")
        creator_id_str = info.get("创建者ID")
        creator_name = info.get("创建者", "未知用户")
        
        # 2. 准备配置参数
        target_category_id = None
        name_prefix = ""
        is_active_state = False # 活跃状态用户可读写，归档状态不可
        
        if state == "一审中":
            target_category_id = IDS["FIRST_REVIEW_CHANNEL_ID"]
            name_prefix = "一审中"
            is_active_state = True
        elif state == "二审中":
            target_category_id = IDS["SECOND_REVIEW_CHANNEL_ID"]
            name_prefix = "二审中"
            is_active_state = True
        elif state == "已过审":
            # 已过审通常也放在二审分类等待归档，或者可以直接放归档分类但名字带已过审
            # 这里逻辑设定为：恢复到二审分类，让用户可以看最后一眼或操作
            target_category_id = IDS["SECOND_REVIEW_CHANNEL_ID"] 
            name_prefix = "已过审"
            is_active_state = True
        elif state == "归档":
            target_category_id = IDS["ARCHIVE_CHANNEL_ID"]
            name_prefix = "已过审" # 通常手动归档是成功的，或者可以是 "归档"
            is_active_state = False
        elif state == "超时归档":
            target_category_id = IDS["ARCHIVE_CHANNEL_ID"]
            name_prefix = "超时归档"
            is_active_state = False

        target_category = ctx.guild.get_channel(target_category_id)
        if not target_category:
            await ctx.followup.send(f"❌ 找不到目标分类 (ID: {target_category_id})，请检查配置！", ephemeral=True)
            return

        # 3. 构建权限
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        }
        
        # 审核员权限
        specific_reviewer = ctx.guild.get_member(SPECIFIC_REVIEWER_ID)
        if specific_reviewer:
            overwrites[specific_reviewer] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        super_egg_role = ctx.guild.get_role(IDS.get("SUPER_EGG_ROLE_ID", 0))
        if super_egg_role:
             overwrites[super_egg_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        # 用户权限
        creator = None
        if creator_id_str:
            creator = ctx.guild.get_member(int(creator_id_str))
            if creator:
                if is_active_state:
                    overwrites[creator] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                else:
                    overwrites[creator] = discord.PermissionOverwrite(read_messages=False) # 归档后不可见

        # 4. 执行频道修改
        new_name = f"{name_prefix}-{ticket_id}-{creator_name}"
        # 截断过长的名字以防报错
        if len(new_name) > 100: new_name = new_name[:100]

        try:
            await channel.edit(name=new_name, category=target_category, overwrites=overwrites, reason=f"工单恢复: {state} - {ctx.author.name}")
            
            # 5. 发送频道内提示
            embed_notify = discord.Embed(
                title="🔄 工单状态已恢复",
                description=f"管理员 **{ctx.author.name}** 已将此工单恢复为：**{state}**\n说明: {reason}",
                color=STYLE["KIMI_YELLOW"]
            )
            await channel.send(embed=embed_notify)
            
            # 如果是恢复到二审，贴心地补发一下答题面板（可选）
            if state == "二审中":
                await channel.send("检测到恢复为二审，正在重新加载答题面板...", view=QuizStartView())

            # 6. 发送 DM 提醒用户
            if creator:
                try:
                    dm_embed = discord.Embed(
                        title="🎫 工单状态更新通知",
                        description=f"你好呀！你在 **{ctx.guild.name}** 的工单 `#{ticket_id}` 状态发生了变化。",
                        color=STYLE["KIMI_YELLOW"]
                    )
                    dm_embed.add_field(name="当前状态", value=state, inline=True)
                    dm_embed.add_field(name="操作原因", value=reason, inline=True)
                    
                    if is_active_state:
                        dm_embed.add_field(name="🔗 前往工单频道", value=channel.mention, inline=False)
                        dm_embed.set_footer(text="请点击上方链接回到频道继续操作哦！")
                    else:
                        dm_embed.set_footer(text="工单已归档/关闭。")

                    await creator.send(embed=dm_embed)
                    await ctx.followup.send(f"✅ 成功恢复工单状态为 **{state}** 并已通知用户！", ephemeral=True)
                except discord.Forbidden:
                    await ctx.followup.send(f"✅ 工单已恢复为 **{state}**，但用户关闭了私信，无法通知。", ephemeral=True)
            else:
                await ctx.followup.send(f"✅ 工单已恢复为 **{state}**，但用户已不在服务器内。", ephemeral=True)

        except Exception as e:
            await ctx.followup.send(f"❌ 恢复失败: {e}", ephemeral=True)

    @ticket.command(name="超时归档", description="（审核小蛋用）将当前工单标记为超时，通知用户并删除。")
    @is_reviewer_egg()
    async def timeout_archive(self, ctx: discord.ApplicationContext, 
                              note: discord.Option(str, "补充备注（可选）", required=False) = None):
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        if not channel.topic or "工单ID" not in channel.topic:
            await ctx.followup.send("无效工单频道！", ephemeral=True); return
        
        info = get_ticket_info(channel)
        ticket_id = info.get("工单ID", "未知")
        creator_id = info.get("创建者ID")
        creator_name = info.get("创建者", "未知用户")

        # 记录日志
        archive_log_channel = self.bot.get_channel(1419652525249794128)
        log_content = f"🚫 **超时归档**\n工单: `{ticket_id}`\n用户: `{creator_name}` (`{creator_id}`)"
        if note:
            log_content += f"\n备注: {note}"
            
        if archive_log_channel: 
            await archive_log_channel.send(log_content)
        
        # 私信用户
        if creator_id:
            try:
                user = await self.bot.fetch_user(int(creator_id))
                dm_content = "不好意思你在🔮LOFI-加载中申请的审核工单已超时，所以先做关闭处理惹😱欢迎重新申请~"
                if note:
                    dm_content += f"\n(管理员留言: {note})"
                await user.send(dm_content)
            except: pass
            
        await channel.delete(reason=f"手动超时归档 - {ctx.author.name}")
        await ctx.followup.send(f"工单 `{ticket_id}` 已处理。", ephemeral=True)

    @ticket.command(name="删除并释放名额", description="（审核小蛋用）立即删除此工单，并将一个审核名额返还。")
    @is_reviewer_egg()
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

    @ticket.command(name="发送二审指引", description="（审核小蛋用）手动在当前频道发送二审答题面板。")
    @is_reviewer_egg()
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

    @ticket.command(name="发送过审祝贺", description="（审核小蛋用）手动在当前频道发送过审消息。")
    @is_reviewer_egg()
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
        embed = discord.Embed(title="🥳 恭喜小宝加入社区", description="如果想来一起闲聊，社区有Q群可以来玩，进群问题也是填写你的【工单编号】就可以惹！\n## 对审核过程没有异议，同意并且阅读完全部东西后@当前审核员/任何审核小蛋来进行归档~身份组已经添加", color=STYLE["KIMI_YELLOW"])
        embed.set_image(url="https://files.catbox.moe/2tytko.jpg")
        embed.set_footer(text="宝宝如果已申请/不打算加群且没有别的问题了，请点击下方对应按钮")
        await ctx.send(f"恭喜 {creator.mention} 通过审核！", embed=embed, view=ArchiveRequestView(reviewer=ctx.author))

    @ticket.command(name="批量导出", description="（服主用）将已归档的过审频道打包成网页快照并删除！")
    @is_reviewer_egg()
    async def bulk_export_and_archive(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        archive_category = self.bot.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        log_channel = self.bot.get_channel(IDS["TICKET_LOG_CHANNEL_ID"])
        
        if not archive_category: await ctx.followup.send("呜...找不到配置的【归档】分类！", ephemeral=True); return
        if not log_channel: await ctx.followup.send("呜...找不到存放日志的频道！", ephemeral=True); return
        
        await ctx.followup.send(f"收到！开始扫描 “{archive_category.name}” 中带 “已过审” 的频道...", ephemeral=True)
        
        channels_to_process = [ch for ch in archive_category.text_channels if "已过审" in ch.name]
        if not channels_to_process:
            await ctx.followup.send("在归档区没找到带“已过审”的频道哦~", ephemeral=True); return

        channels_to_process.sort(key=lambda x: x.created_at)

        exported_count = 0
        current_date_header = "" 

        for channel in channels_to_process:
            try:
                channel_date = channel.created_at.astimezone(QUOTA["TIMEZONE"]).strftime('%Y%m%d')
                if channel_date != current_date_header:
                    current_date_header = channel_date
                    await log_channel.send(f"## 📅 {current_date_header}") 

                info = get_ticket_info(channel)
                qq_number = info.get("QQ", "未录入") 
                ticket_id = info.get("工单ID", "未知")
                creator_name = info.get("创建者", "未知")

                html_template = """
                <!DOCTYPE html><html><head><title>Log for {channel_name}</title><meta charset="UTF-8"><style>
                body {{ background-color: #313338; color: #dbdee1; font-family: 'Whitney', 'Helvetica Neue', sans-serif; padding: 20px; }}
                .info-box {{ background-color: #2b2d31; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #F1C40F; }}
                .info-item {{ margin: 5px 0; font-size: 1.1em; }}
                .message-group {{ display: flex; margin-bottom: 20px; }} .avatar img {{ width: 40px; height: 40px; border-radius: 50%; margin-right: 20px; }}
                .message-content .author {{ font-weight: 500; color: #f2f3f5; }} .message-content .timestamp {{ font-size: 0.75rem; color: #949ba4; margin-left: 10px; }}
                .message-content .text {{ margin-top: 5px; line-height: 1.375rem; }} .attachment img {{ max-width: 400px; border-radius: 5px; margin-top: 10px; }}
                .embed {{ background-color: #2b2d31; border-left: 4px solid {embed_color}; padding: 10px; border-radius: 5px; margin-top: 10px; }}
                .embed-title {{ font-weight: bold; color: white; }} .embed-description {{ font-size: 0.9rem; }}
                </style></head><body>
                <h1>工单日志: {channel_name}</h1>
                <div class="info-box">
                    <div class="info-item">🎫 <b>工单编号:</b> {ticket_id}</div>
                    <div class="info-item">👤 <b>申请用户:</b> {creator_name}</div>
                    <div class="info-item">🐧 <b>绑定QQ:</b> {qq_number}</div>
                </div>
                <hr>
                """
                html_content = html_template.format(
                    channel_name=channel.name, 
                    embed_color=hex(STYLE['KIMI_YELLOW']).replace('0x', '#'),
                    ticket_id=ticket_id,
                    creator_name=creator_name,
                    qq_number=qq_number
                )
                
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
                
                await log_channel.send(f"📄 归档记录: `{channel.name}` (QQ: {qq_number})")
                await log_channel.send(file=discord.File(zip_buffer, filename=f"{channel.name}.zip"))
                
                await channel.delete(reason="批量导出并归档")
                exported_count += 1
                await asyncio.sleep(1) 

            except Exception as e:
                print(f"批量导出频道 {channel.name} 时出错: {e}")
                await log_channel.send(f"❌ 导出频道 `{channel.name}` 时出错: {e}")

        await ctx.followup.send(f"批量导出完成！成功处理了 **{exported_count}/{len(channels_to_process)}** 个频道！", ephemeral=True)
    
    @ticket.command(name="录入qq", description="（审核小蛋用）录入或更新当前工单对应的QQ号。")
    @is_reviewer_egg()
    async def record_qq(self, ctx: discord.ApplicationContext, 
                        qq_number: discord.Option(str, "用户的QQ号码", required=True)):
        """录入QQ号到频道Topic中，方便归档时读取。此版本反馈信息仅管理员可见。"""
        channel = ctx.channel
        
        if not channel.topic or "工单ID" not in channel.topic:
            await ctx.respond("呜...这里似乎不是一个有效的工单频道！请在工单频道内使用此指令。", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)

        try:
            info = get_ticket_info(channel)
            info["QQ"] = qq_number
            
            new_topic_parts = []
            for key, value in info.items():
                new_topic_parts.append(f"{key}: {value}")
            new_topic = " | ".join(new_topic_parts)
 
            await channel.edit(topic=new_topic)
            
            embed = discord.Embed(
                description=f"✅ **录入成功！**\n\n工单QQ已更新为：`{qq_number}`\n归档导出时将包含此信息。",
                color=STYLE["KIMI_YELLOW"]
            )
            await ctx.followup.send(embed=embed, ephemeral=True)

        except discord.Forbidden:
            await ctx.followup.send("呜哇！本大王没有权限修改这个频道的简介（Topic），请检查权限！", ephemeral=True)
        except Exception as e:
            await ctx.followup.send(f"录入失败，发生未知错误: {e}", ephemeral=True)

    @discord.message_command(name="超时归档此工单")
    @is_reviewer_egg()
    async def timeout_archive_ctx(self, ctx: discord.ApplicationContext, message: discord.Message):
        """右键点击消息 -> Apps -> 超时归档此工单"""
        channel = ctx.channel
        if not channel.topic or "工单ID" not in channel.topic:
            await ctx.respond("❌ 只能在有效的工单频道内使用此功能！", ephemeral=True)
            return

        await ctx.respond(
            "👋 **请确认归档操作：**\n你需要为这次超时归档添加备注吗？", 
            view=TimeoutOptionView(self, channel), 
            ephemeral=True
        )

    @ticket.command(name="批量清理超时", description="（服主用）扫描归档区，批量删除所有标记为“超时归档”的旧频道。")
    @is_reviewer_egg()
    async def bulk_clean_timeouts(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        archive_category = self.bot.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        log_channel = self.bot.get_channel(IDS["TICKET_LOG_CHANNEL_ID"])
        
        if not archive_category: 
            await ctx.followup.send("呜...找不到配置的【归档】分类！", ephemeral=True); return
        
        channels_to_delete = [ch for ch in archive_category.text_channels if "超时归档" in ch.name]
        if not channels_to_delete:
            await ctx.followup.send("在归档区没找到任何标记为“超时归档”的频道哦~ 看起来很干净！", ephemeral=True)
            return

        count = len(channels_to_delete)
        await ctx.followup.send(f"🔍 扫描完毕！发现 **{count}** 个超时归档频道，正在开始清理...", ephemeral=True)
        
        if log_channel:
            await log_channel.send(f"🧹 **开始批量清理超时工单**\n操作人: {ctx.author.mention}\n数量: {count} 个")

        deleted_count = 0
        deleted_names = []

        for channel in channels_to_delete:
            try:
                c_name = channel.name
                await channel.delete(reason=f"批量清理超时 - {ctx.author.name}")
                deleted_names.append(c_name)
                deleted_count += 1
                await asyncio.sleep(1.5) 
            except Exception as e:
                print(f"删除频道 {channel.name} 失败: {e}")

        report = f"🗑️ **批量清理完成**\n成功删除: {deleted_count}/{count}"
        if deleted_names:
            names_str = "\n".join(deleted_names[:20])
            if len(deleted_names) > 20:
                names_str += f"\n... 以及其他 {len(deleted_names)-20} 个"
            report += f"\n\n**删除列表:**\n```\n{names_str}\n```"

        if log_channel:
            await log_channel.send(report)

        await ctx.followup.send(f"✨ 清理完毕！共删除了 **{deleted_count}** 个超时废弃频道！", ephemeral=True)

    quota_mg = discord.SlashCommandGroup("名额管理", "（仅限审核小蛋）手动调整工单名额~", checks=[is_reviewer_egg()])
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

    @discord.slash_command(name="刷新工单创建面板", description="（仅限审核小蛋）手动发送或刷新工单创建面板！")
    @is_reviewer_egg()
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
