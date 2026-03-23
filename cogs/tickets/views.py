import discord
import asyncio
import datetime
from config import IDS, STYLE, QUOTA
from .utils import (
    STRINGS, SPECIFIC_REVIEWER_ID, get_ticket_info,
    execute_archive, load_quota_data, save_quota_data
)

# --- 模态框: 填写归档备注 ---
class TimeoutNoteModal(discord.ui.Modal):
    def __init__(self, bot, channel, *, is_timeout=True, log_title_override=None, title="填写归档备注"):
        super().__init__(title=title)
        self.bot = bot
        self.channel = channel
        self.is_timeout = is_timeout
        self.log_title_override = log_title_override
        self.add_item(discord.ui.InputText(
            label="备注内容", placeholder="请输入原因...", style=discord.InputTextStyle.paragraph, required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        await execute_archive(
            self.bot,
            interaction,
            self.channel,
            self.children[0].value,
            is_timeout=self.is_timeout,
            log_title_override=self.log_title_override,
        )

# --- 视图: 超时确认选项 ---
class TimeoutOptionView(discord.ui.View):
    def __init__(self, bot, channel):
        super().__init__(timeout=60)
        self.bot = bot
        self.channel = channel

    @discord.ui.button(label="📝 填写备注并归档", style=discord.ButtonStyle.primary)
    async def note_archive(self, button, interaction):
        await interaction.response.send_modal(TimeoutNoteModal(self.bot, self.channel))

    @discord.ui.button(label="🚀 直接归档", style=discord.ButtonStyle.danger)
    async def quick_archive(self, button, interaction):
        await execute_archive(self.bot, interaction, self.channel, "无 (直接归档)", is_timeout=True)

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction):
        await interaction.response.edit_message(content="操作已取消。", view=None)

# --- 视图: 用户过审后的确认 ---
class ArchiveRequestView(discord.ui.View):
    def __init__(self, reviewer: discord.Member = None):
        super().__init__(timeout=None)
        self.reviewer = reviewer

    async def process(self, interaction, choice):
        await interaction.response.defer()
        # 禁用按钮
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)

        # 通知
        msg = f"📢 {interaction.user.mention} 选择了：**{choice}**\n"
        mention = f"<@&{SPECIFIC_REVIEWER_ID}>"
        if self.reviewer: mention += f" {self.reviewer.mention}"
        msg += f"{mention}，请处理归档！"
        await interaction.channel.send(msg)

        # 10秒后自动锁定
        await interaction.channel.send("⏳ 30秒后自动锁定频道...")
        await asyncio.sleep(30)

        # 移除用户权限
        info = get_ticket_info(interaction.channel)
        cid = info.get("创建者ID")
        if cid:
            mem = interaction.guild.get_member(int(cid))
            if mem:
                await interaction.channel.set_permissions(mem, read_messages=False)
                await interaction.channel.send("🔒 频道已锁定。")

    @discord.ui.button(label="已申请加群", style=discord.ButtonStyle.primary, custom_id="req_archive_1")
    async def btn_Applied(self, button, interaction): await self.process(interaction, "已申请加群")

    @discord.ui.button(label="不打算加群，没问题了", style=discord.ButtonStyle.secondary, custom_id="req_archive_2")
    async def btn_NoIssue(self, button, interaction): await self.process(interaction, "不打算加群")

# --- 视图: 确认放弃审核 ---
class ConfirmAbandonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="✅ 确认放弃", style=discord.ButtonStyle.danger)
    async def confirm(self, button, interaction):
        await interaction.response.defer()
        channel = interaction.channel
        user = interaction.user
        info = get_ticket_info(channel)
        
        # 1. 返还名额
        q_data = load_quota_data()
        q_data["daily_quota_left"] += 1
        save_quota_data(q_data)
        
        # 更新面板
        cog = interaction.client.get_cog("Tickets")
        if cog:
            await cog.update_panel_message()
            
        # 2. 记录日志
        log_channel_id = IDS.get("TICKET_LOG_CHANNEL_ID")
        if log_channel_id:
            log_channel = interaction.client.get_channel(log_channel_id)
            if log_channel:
                embed = discord.Embed(
                    title="🚫 用户放弃审核",
                    description=f"**用户:** {user.mention} ({user.name})\n**工单ID:** {info.get('工单ID', '未知')}\n**频道名:** {channel.name}",
                    color=discord.Color.red()
                )
                await log_channel.send(embed=embed)
                
        # 3. 删除频道
        try:
            await channel.delete(reason=f"用户 {user.name} 主动放弃审核")
        except Exception as e:
            print(f"删除频道失败: {e}")

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction):
        await interaction.response.edit_message(content="已取消放弃操作。", view=None)

# --- 视图: 呼叫审核员 ---
class NotifyReviewerView(discord.ui.View):
    def __init__(self, reviewer_id: int):
        super().__init__(timeout=None)
        self.rid = reviewer_id

    @discord.ui.button(label="✅ 材料已备齐，呼叫审核小蛋", style=discord.ButtonStyle.primary, custom_id="notify_reviewer_button")
    async def notify(self, button, interaction):
        info = get_ticket_info(interaction.channel)
        if str(interaction.user.id) != info.get("创建者ID"):
            return await interaction.response.send_message("只有创建者能呼叫哦！", ephemeral=True)

        button.disabled = True
        button.label = "✅ 已呼叫"
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"<@&{self.rid}> 材料已备齐，请查看！")

    @discord.ui.button(label="🚫 放弃审核", style=discord.ButtonStyle.danger, custom_id="abandon_ticket_button")
    async def abandon(self, button, interaction):
        info = get_ticket_info(interaction.channel)
        if str(interaction.user.id) != info.get("创建者ID"):
            return await interaction.response.send_message("只有创建者能放弃审核哦！", ephemeral=True)
        
        await interaction.response.send_message("确定要放弃审核吗？此操作将删除当前工单并无法恢复。", view=ConfirmAbandonView(), ephemeral=True)

# --- 视图: 工单内管理面板 ---
class TicketActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):
        uid = interaction.user.id
        # 简单鉴权：审核员ID 或 超级蛋Role
        is_staff = (uid == SPECIFIC_REVIEWER_ID)
        role = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
        if role and role in interaction.user.roles: is_staff = True

        if not is_staff:
            await interaction.response.send_message(STRINGS["messages"]["err_not_staff"], ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🎉 已过审", style=discord.ButtonStyle.success, custom_id="ticket_approved")
    async def approved(self, button, interaction):
        await interaction.response.defer()
        button.disabled = True
        await interaction.message.edit(view=self)

        # 调用核心逻辑，需要在 Core 传递进来或者通过 Bot 获取 Cog
        # 这里为了解耦，我们假设通过 extension 获取 Cog 方法
        cog = interaction.client.get_cog("Tickets")
        if cog:
            await cog.approve_ticket_logic(interaction)

    @discord.ui.button(label="📦 工单归档", style=discord.ButtonStyle.secondary, custom_id="ticket_archive")
    async def archive(self, button, interaction):
        await interaction.response.send_modal(
            TimeoutNoteModal(
                interaction.client,
                interaction.channel,
                is_timeout=False,
                log_title_override="审核未通过",
            )
        )

class SuspendAuditModal(discord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="🔧 设置审核中止计划")
        self.cog = cog

        self.add_item(discord.ui.InputText(
            label="开始时间 (YYYY-MM-DD HH:MM 或 now)",
            placeholder="例如: 2024-05-20 12:00 或输入 now 立即开始",
            required=True
        ))

        self.add_item(discord.ui.InputText(
            label="结束时间 (留空代表无限期)",
            placeholder="例如: 2024-05-21 12:00",
            required=False
        ))

        self.add_item(discord.ui.InputText(
            label="中止原因",
            placeholder="展示给用户的理由，例如：系统维护中...",
            style=discord.InputTextStyle.paragraph,
            required=False,
            value="管理员正在进行系统维护" # 默认值
        ))

    async def callback(self, interaction: discord.Interaction):
        start_str = self.children[0].value.strip()
        end_str = self.children[1].value.strip()
        reason = self.children[2].value.strip()

        # 解析时间
        now = datetime.datetime.now(QUOTA["TIMEZONE"])
        start_dt = None
        end_dt = None

        try:
            # 解析开始时间
            if start_str.lower() == "now":
                start_dt = now
            else:
                # 尝试解析 'YYYY-MM-DD HH:MM'
                dt_naive = datetime.datetime.strptime(start_str, "%Y-%m-%d %H:%M")
                start_dt = dt_naive.replace(tzinfo=QUOTA["TIMEZONE"])

            # 解析结束时间
            if end_str:
                dt_naive = datetime.datetime.strptime(end_str, "%Y-%m-%d %H:%M")
                end_dt = dt_naive.replace(tzinfo=QUOTA["TIMEZONE"])

                if end_dt <= start_dt:
                    return await interaction.response.send_message("❌ **结束时间必须晚于开始时间！**", ephemeral=True)

        except ValueError:
            return await interaction.response.send_message("❌ **时间格式错误！**\n请使用 `YYYY-MM-DD HH:MM` 格式 (例如 2024-05-20 12:00) 或 `now`。", ephemeral=True)

        # --- 核心修改部分开始 ---

        # 1. 构建符合 core.py 中定义的 schedule_data 结构
        # 注意：这里要存时间戳 (timestamp)，因为 json 不能直接存 datetime 对象
        new_schedule = {
            "suspended": True,
            "reason": reason,
            "start_dt": start_dt.timestamp() if start_dt else None,
            "end_dt": end_dt.timestamp() if end_dt else None
        }

        # 2. 更新内存中的状态
        self.cog.schedule_data = new_schedule

        # 3. 持久化保存
        # 小技巧：我们在函数内部导入 save_audit_schedule，
        # 这样可以防止 views.py 和 core.py 互相导入导致的“循环引用”报错
        try:
            from .core import save_audit_schedule
            save_audit_schedule(new_schedule)
        except ImportError:
            print("警告：无法导入 save_audit_schedule，可能是文件结构问题，数据仅在内存生效。")

        # --- 核心修改部分结束 ---

        # 构建反馈消息
        msg = f"✅ **已设置审核中止计划**\n"
        msg += f"📅 **开始**: {start_dt.strftime('%Y-%m-%d %H:%M')}\n"
        if end_dt:
            msg += f"📅 **结束**: {end_dt.strftime('%Y-%m-%d %H:%M')}\n"
        else:
            msg += f"📅 **结束**: 无限期（需手动恢复）\n"
        msg += f"📝 **原因**: {reason}"

        await self.cog.update_panel_message()
        await interaction.response.send_message(msg, ephemeral=True)
