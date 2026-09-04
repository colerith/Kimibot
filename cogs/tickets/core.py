# cogs/tickets/core.py

import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import random
import json
import os

from config import IDS, QUOTA, STYLE
from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace
from .utils import (
    STRINGS, REVIEWER_ROLE_ID, TIMEOUT_HOURS_ARCHIVE, TIMEOUT_HOURS_REMIND,
    APPROVAL_QR_IMAGE_URL, GROUP_CONFIRM_SECONDS,
    is_reviewer_egg, get_ticket_info, load_quota_data, save_quota_data, execute_archive,
    ApprovedTicketArchiveView, ARCHIVE_KIND_APPROVED, ARCHIVE_KIND_REJECTED, ARCHIVE_KIND_TIMEOUT,
)
from .views import (
    TicketActionView, TimeoutOptionView, ArchiveRequestView, ApproveTicketConfirmationView,
    NotifyReviewerView, SuspendAuditModal, build_approve_confirmation_embed,
)

# --- 持久化工具函数 (新增) ---
AUDIT_SCHEDULE_FILE = "data/audit_schedule.json"
UPLOAD_WINDOW_MINUTES = 10
MATERIAL_STATE_PENDING = "待提交"
MATERIAL_STATE_SUBMITTED = "已提交"


def build_ticket_channel_name(info, material_state):
    """Build a compact ticket name whose prefix exposes material submission state."""
    is_test = info.get("测试模式") == "是"
    prefix = ("已过审-测试" if is_test else "已过审") if material_state == "已过审" else (f"测试{material_state}" if is_test else material_state)
    ticket_id = info.get("工单ID") or "未知工单"
    creator = info.get("创建者") or "未知用户"
    return f"{prefix}-{ticket_id}-{creator}"[:100]


def build_ticket_created_dm(
    user: discord.Member,
    guild: discord.Guild,
    channel: discord.TextChannel,
    ticket_id: str,
) -> discord.Embed:
    """Build the private confirmation card for a newly created audit ticket."""
    embed = discord.Embed(
        title="🎫 人工审核工单创建成功",
        description=(
            f"嗨，**{user.display_name}**！你在 **{guild.name}** 的专属审核工单已经准备好啦。\n"
            "请只在自己的工单频道内查看要求并提交审核材料。"
        ),
        color=STYLE.get("KIMI_YELLOW", 0xF7C873),
    )
    embed.add_field(
        name="📌 工单信息",
        value=(
            f"工单编号：`{ticket_id}`\n"
            f"专属频道：[点击进入 {channel.name}]({channel.jump_url})"
        ),
        inline=False,
    )
    embed.add_field(
        name="📝 接下来这样做",
        value=(
            "**1.** 进入工单，仔细阅读完整审核要求\n"
            "**2.** 先在本地准备好截图、录屏与语音材料\n"
            "**3.** 点击 **开始上传**，并在 10 分钟内一次性上传完毕"
        ),
        inline=False,
    )
    embed.add_field(
        name="⏰ 提交时间",
        value=(
            "请先准备材料，再开启仅有一次的 **10 分钟上传窗口**。\n"
            "截止后将停止补充材料；若没有上传任何附件，工单会自动按超时归档。"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔒 隐私提醒",
        value="审核材料可能包含个人信息，请做好必要打码，且不要发送到工单以外的频道。",
        inline=False,
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=f"工单 #{ticket_id} · 请保留这条私信，方便随时返回")
    return embed


def build_ticket_link_view(channel: discord.TextChannel) -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label="立即进入我的审核工单",
            emoji="➡️",
            style=discord.ButtonStyle.link,
            url=channel.jump_url,
        )
    )
    return view


def build_ticket_approved_dm(
    user: discord.Member,
    guild: discord.Guild,
    channel: discord.TextChannel,
    ticket_id: str,
) -> discord.Embed:
    """Build the private confirmation card for a successfully approved audit."""
    embed = discord.Embed(
        title="🎉 人工审核顺利通过！",
        description=(
            f"恭喜你，**{user.display_name}**！你在 **{guild.name}** 的人工审核已经完成。\n"
            "正式成员身份已发放，更多社区内容现已解锁啦 ✨"
        ),
        color=0x73C991,
    )
    embed.add_field(
        name="🧾 工单编号",
        value=f"`{ticket_id}`",
        inline=False,
    )
    embed.add_field(
        name="✅ 当前状态",
        value="审核结果：**已通过**\n身份状态：**正式成员身份已更新**",
        inline=False,
    )
    embed.add_field(
        name="📮 最后一步",
        value=(
            f"请返回 [审核工单频道]({channel.jump_url}) 查看通过说明，扫描加群二维码，选择 **已加群** 或 **不加群**。\n"
            "如果暂时没有确认，系统会在过审 30 分钟后自动归档；已获得的身份和权限不会受影响。"
        ),
        inline=False,
    )
    embed.add_field(
        name="💛 欢迎加入",
        value="感谢你的配合！记得遵守社区守则，祝你在社区玩得开心～",
        inline=False,
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="权限已生效 · 请回到工单完成最后确认")
    return embed


def build_ticket_approved_link_view(channel: discord.TextChannel) -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label="返回工单完成确认",
            emoji="✅",
            style=discord.ButtonStyle.link,
            url=channel.jump_url,
        )
    )
    return view


def load_audit_schedule():
    default = {"suspended": False, "reason": None, "start_dt": None, "end_dt": None}
    raw = load_json_namespace(
        "ticket_audit_schedule", legacy_file=AUDIT_SCHEDULE_FILE, default=default
    )
    return raw if isinstance(raw, dict) else default

def save_audit_schedule(data):
    save_json_namespace("ticket_audit_schedule", data)

class TicketPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🥚 申请全区权限", style=discord.ButtonStyle.primary, custom_id="create_ticket_panel_button")
    async def create_ticket(self, button, interaction):
        await self.cog.create_ticket_logic(interaction)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # 加载持久化的暂停计划
        self.schedule_data = load_audit_schedule()

        # 内存锁：防止同一用户并发创建
        # 集合中存储正在处理中的 user_id
        self.creating_lock = set()
        self.approval_lock = set()
        self.material_state_lock = set()
        self.ticket_order_locks = {}
        self.material_submission_times = {}
        self.group_confirmations = load_json_namespace("ticket_group_confirmations", default={})
        self.group_confirmation_locks = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(TicketActionView())
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(ArchiveRequestView())
        self.bot.add_view(NotifyReviewerView(REVIEWER_ROLE_ID))
        self.bot.add_view(ApprovedTicketArchiveView())

        print("Tickets Cog Loaded & Views Registered.")
        print(f"当前审核暂停状态: {self.schedule_data.get('suspended')}")

        await self.restore_approved_tickets()

        # 启动定时任务
        if not self.reset_daily_quota.is_running(): self.reset_daily_quota.start()
        if not self.check_inactive_tickets.is_running(): self.check_inactive_tickets.start()
        if not self.check_group_confirmations.is_running(): self.check_group_confirmations.start()
        if not self.check_upload_windows.is_running(): self.check_upload_windows.start()
        if not self.close_tickets_at_night.is_running(): self.close_tickets_at_night.start()

    # ======================================================================================
    # --- 核心逻辑方法 (供 View 调用) ---
    # ======================================================================================

    async def create_ticket_logic(self, interaction: discord.Interaction, *, test_mode: bool = False):
        user = interaction.user

        # 必须在所有资格检查和频道扫描之前确认交互，否则繁忙时会超过
        # Discord 的首次响应窗口并得到 10062 Unknown interaction。
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return

        # [0] 并发锁检查：如果该用户正在创建中，直接阻止
        if user.id in self.creating_lock:
            return await interaction.followup.send("🚧 **正在处理中...**\n请不要频繁点击按钮哦，正在为你创建这里！", ephemeral=True)

        # 加锁
        self.creating_lock.add(user.id)
        quota_deducted = False

        try:
            # 1. 检查暂停状态 (使用持久化数据)
            if not test_mode and self.schedule_data.get("suspended", False):
                now = datetime.datetime.now(QUOTA["TIMEZONE"])
                is_active_suspension = False

                # 读取时间戳并转换回 datetime 对象
                start_ts = self.schedule_data.get("start_dt")
                end_ts = self.schedule_data.get("end_dt")

                start_dt = datetime.datetime.fromtimestamp(start_ts, QUOTA["TIMEZONE"]) if start_ts else None
                end_dt = datetime.datetime.fromtimestamp(end_ts, QUOTA["TIMEZONE"]) if end_ts else None

                if not start_dt:
                    is_active_suspension = True
                else:
                    if start_dt <= now:
                        if end_dt:
                            if now < end_dt:
                                is_active_suspension = True
                            else:
                                is_active_suspension = False
                        else:
                            is_active_suspension = True
                    else:
                        is_active_suspension = False

                if is_active_suspension:
                    reason = self.schedule_data.get("reason") or "管理员暂停了审核功能"
                    until_str = "恢复时间待定"
                    if end_dt:
                        diff = end_dt - now
                        hours, remainder = divmod(int(diff.total_seconds()), 3600)
                        minutes, _ = divmod(remainder, 60)
                        if hours > 24:
                            until_str = f"预计 {end_dt.strftime('%m-%d %H:%M')} 恢复"
                        else:
                            until_str = f"预计 {hours}小时{minutes}分 后恢复"

                    # 只要返回，记得解锁
                    self.creating_lock.discard(user.id)
                    return await interaction.followup.send(f"🚫 **审核通道已暂时关闭**\n原因：{reason}\n{until_str}", ephemeral=True)

            # 2. 检查时间
            now = datetime.datetime.now(QUOTA["TIMEZONE"])
            if not test_mode and not (17 <= now.hour < 23):
                self.creating_lock.discard(user.id)
                return await interaction.followup.send(STRINGS["messages"]["err_time_limit"], ephemeral=True)

            # 3. 检查资格
            user_roles = [r.id for r in interaction.user.roles]
            has_perm = (IDS["VERIFICATION_ROLE_ID"] in user_roles) or \
                    (IDS["SUPER_EGG_ROLE_ID"] in user_roles) or \
                    (REVIEWER_ROLE_ID in user_roles)

            if not test_mode and not has_perm:
                self.creating_lock.discard(user.id)
                return await interaction.followup.send(STRINGS["messages"]["err_perm_create"], ephemeral=True)

            # 4. 检查重复 & 额度
            # 获取所有相关分类
            c1 = interaction.guild.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"])
            c1_extra = interaction.guild.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID"))
            c2 = interaction.guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])

            if not c1:
                self.creating_lock.discard(user.id)
                return await interaction.followup.send("配置错误：找不到一审分类。", ephemeral=True)

            # 确定目标分类（处理容量50上限）
            target_category = c1
            if isinstance(c1, discord.CategoryChannel) and len(c1.channels) >= 50:
                if c1_extra and isinstance(c1_extra, discord.CategoryChannel) and len(c1_extra.channels) < 50:
                    target_category = c1_extra
                else:
                    self.creating_lock.discard(user.id)
                    return await interaction.followup.send("🚫 **无法创建工单**\n所有审核窗口都满员啦（50/50）！请稍后再试。", ephemeral=True)

            # 严查是否已有频道：遍历所有可能存在的分类
            check_cats = [c1, c2, interaction.guild.get_channel(IDS["ARCHIVE_CHANNEL_ID"])]
            if c1_extra: check_cats.append(c1_extra)

            for c in check_cats:
                if not c or not isinstance(c, discord.CategoryChannel): continue
                for ch in c.text_channels:
                    # 检查 Topic 里的 ID，且排除归档区（允许归档后重建，但这里根据需求，如果归档区还要查重，可以加上）
                    # 通常如果之前工单没删（在归档区），也不让建新的？看你的需求。
                    # 之前的代码是 "除非该工单被删除才能重新申请"，意味着归档了（没删）也不能申请。
                    if not test_mode and ch.topic and str(interaction.user.id) in ch.topic:
                        # 再次确认不是误判（检查topic格式）
                        if f"创建者ID: {interaction.user.id}" in ch.topic:
                            self.creating_lock.discard(user.id)
                            return await interaction.followup.send(STRINGS["messages"]["err_already_has"].format(channel=ch.mention), ephemeral=True)

            # 检查额度
            if not test_mode:
                q_data = load_quota_data()
                if q_data["daily_quota_left"] <= 0:
                    self.creating_lock.discard(user.id)
                    return await interaction.followup.send(STRINGS["messages"]["err_quota_limit"], ephemeral=True)

                # 测试工单不占用每日名额；真实工单保持原有扣减逻辑。
                q_data["daily_quota_left"] -= 1
                save_quota_data(q_data)
                quota_deducted = True
                await self.update_panel_message()

            tid = random.randint(100000, 999999)
            initial_info = {
                "创建者ID": str(interaction.user.id),
                "创建者": interaction.user.name,
                "工单ID": str(tid),
                "材料状态": MATERIAL_STATE_PENDING,
            }
            if test_mode:
                initial_info["测试模式"] = "是"
            c_name = build_ticket_channel_name(initial_info, MATERIAL_STATE_PENDING)

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    attach_files=False,
                ),
            }
            reviewer_role = interaction.guild.get_role(REVIEWER_ROLE_ID)
            if reviewer_role:
                overwrites[reviewer_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            super_egg = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
            if super_egg: overwrites[super_egg] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            ch = await interaction.guild.create_text_channel(
                name=c_name, category=target_category, overwrites=overwrites,
                topic=" | ".join(f"{key}: {value}" for key, value in initial_info.items()),
            )

            # 新建的待提交工单仍位于已过审队列之前。
            order_lock = self.ticket_order_locks.setdefault(target_category.id, asyncio.Lock())
            async with order_lock:
                approved_channels = [c for c in target_category.text_channels
                                     if str(c.id) in self.group_confirmations or "已过审" in c.name]
                if approved_channels:
                    await ch.move(before=min(approved_channels, key=lambda c: c.position),
                                  reason="待提交工单排在已过审工单之前")

            # 发送初始消息
            e_create = discord.Embed.from_dict(STRINGS["embeds"]["ticket_created"])
            if e_create.title: e_create.title = e_create.title.replace("{ticket_id}", str(tid))
            if e_create.description: e_create.description = e_create.description.replace("{ticket_id}", str(tid))
            e_create.color = STYLE["KIMI_YELLOW"]
            await ch.send(f"{interaction.user.mention}", embed=e_create, view=TicketActionView())

            # 发送要求
            req_data = STRINGS["embeds"]["requirements"]
            e_req = discord.Embed(title=req_data["title"], description=req_data["desc"], color=STYLE["KIMI_YELLOW"])
            for f in req_data["fields"]: e_req.add_field(name=f["name"], value=f["value"], inline=False)
            e_req.set_image(url=req_data["image"])
            e_req.set_footer(text=req_data["footer"])
            await ch.send(f"你好呀 {interaction.user.mention}，请按下面的要求提交材料哦~", embed=e_req)

            # 发送给审核员的提醒
            rem_text = STRINGS["messages"]["reminder_text"].format(ticket_id=tid, user_id=interaction.user.id)
            await ch.send(embed=discord.Embed(description=rem_text, color=STYLE["KIMI_YELLOW"]), view=NotifyReviewerView(REVIEWER_ROLE_ID))

            # 私信通知
            try:
                await interaction.user.send(
                    embed=build_ticket_created_dm(interaction.user, interaction.guild, ch, str(tid)),
                    view=build_ticket_link_view(ch),
                )
                msg_status = STRINGS["messages"]["dm_status_ok"]
            except discord.Forbidden:
                print(f"无法发送工单创建私信: user={interaction.user.id} reason=dm_closed")
                msg_status = STRINGS["messages"]["dm_status_fail"]
            except discord.HTTPException as error:
                print(f"发送工单创建私信失败: user={interaction.user.id} error={error!r}")
                msg_status = STRINGS["messages"]["dm_status_fail"]

            prefix = "🧪 测试工单" if test_mode else "好惹！你的审核频道"
            cleanup_tip = "\n测试完成后可使用频道内的管理按钮归档清理。" if test_mode else ""
            await interaction.followup.send(
                f"{prefix} {ch.mention} 已经创建，审核要求已发送到频道内。\n{msg_status}{cleanup_tip}",
                ephemeral=True,
            )

        except Exception as e:
            print(f"创建工单逻辑出错: {e}")
            # 只有确实扣过额度才回滚，避免 defer/前置检查失败凭空增加名额。
            if quota_deducted:
                q_data = load_quota_data() # 重新读一遍防止并发覆盖
                q_data["daily_quota_left"] += 1
                save_quota_data(q_data)
                await self.update_panel_message()

            try:
                # 尝试发送错误信息，如果 interaction 过期可能会失败，所以加 try
                await interaction.followup.send(f"创建失败: {e}", ephemeral=True)
            except:
                pass

        finally:
            # 无论成功失败，最后都要释放锁
            self.creating_lock.discard(user.id)


    async def start_upload_window(self, interaction, view, button):
        """开启持久化的十分钟上传窗口，截止处理由后台任务接管。"""
        channel = interaction.channel
        info = get_ticket_info(channel)
        if info.get("上传状态"):
            return await interaction.response.send_message(
                "ℹ️ 本工单已经开启过上传窗口，不能重复开始。",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        now = discord.utils.utcnow()
        deadline = now + datetime.timedelta(minutes=UPLOAD_WINDOW_MINUTES)
        info["上传状态"] = "进行中"
        info["上传开始"] = str(int(now.timestamp()))
        info["上传截止"] = str(int(deadline.timestamp()))
        info["材料状态"] = info.get("材料状态") or MATERIAL_STATE_PENDING
        new_topic = " | ".join(f"{key}: {value}" for key, value in info.items())
        new_name = build_ticket_channel_name(info, info["材料状态"])

        overwrite = channel.overwrites_for(interaction.user)
        overwrite.read_messages = True
        overwrite.send_messages = True
        overwrite.attach_files = True
        try:
            await channel.set_permissions(
                interaction.user,
                overwrite=overwrite,
                reason="人工审核材料上传窗口已开启",
            )
            await channel.edit(
                name=new_name,
                topic=new_topic,
                reason="记录人工审核材料上传窗口",
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            overwrite.send_messages = False
            overwrite.attach_files = False
            try:
                await channel.set_permissions(interaction.user, overwrite=overwrite)
            except (discord.Forbidden, discord.HTTPException):
                pass
            return await interaction.followup.send(f"❌ 无法开启上传窗口：{error}", ephemeral=True)

        button.disabled = True
        button.label = "⏳ 上传进行中"
        await interaction.message.edit(view=view)
        embed = discord.Embed(
            title="📤 材料上传已开始",
            description=(
                f"{interaction.user.mention} 请在 **{UPLOAD_WINDOW_MINUTES} 分钟内**一次性上传完全部审核材料。\n\n"
                f"截止时间：<t:{int(deadline.timestamp())}:F>（<t:{int(deadline.timestamp())}:R>）\n"
                "到时系统会自动关闭你的发送权限，并通知审核小蛋开始审核。\n"
                "若截止时没有检测到任何附件，本工单会按超时自动归档。"
            ),
            color=0x5B8DEF,
        )
        embed.set_footer(text="上传窗口仅可开启一次 · 截止后不能补充材料")
        await channel.send(embed=embed)
        await interaction.followup.send("✅ 十分钟上传窗口已开启，请立即上传全部材料。", ephemeral=True)

    @staticmethod
    def _ticket_created_sort_key(channel):
        return (channel.created_at.timestamp(), channel.id)

    async def reposition_submitted_ticket(self, channel, submitted_at):
        """Insert one submitted ticket into the category queue with one Discord move."""
        category = channel.category
        if not category:
            return

        lock = self.ticket_order_locks.setdefault(category.id, asyncio.Lock())
        async with lock:
            submitted = []
            pending = []
            for ticket_channel in category.text_channels:
                info = get_ticket_info(ticket_channel)
                if not info.get("工单ID"):
                    continue
                if str(ticket_channel.id) in self.group_confirmations or "已过审" in ticket_channel.name:
                    continue

                state = info.get("材料状态")
                if ticket_channel.id == channel.id:
                    state = MATERIAL_STATE_SUBMITTED
                    submission_time = int(submitted_at)
                else:
                    submission_time = self.material_submission_times.get(ticket_channel.id)
                    if submission_time is not None:
                        state = MATERIAL_STATE_SUBMITTED
                    if submission_time is None:
                        try:
                            submission_time = int(
                                info.get("材料提交时间")
                                or info.get("上传开始")
                                or ticket_channel.created_at.timestamp()
                            )
                        except (TypeError, ValueError):
                            submission_time = int(ticket_channel.created_at.timestamp())

                if state == MATERIAL_STATE_SUBMITTED:
                    submitted.append((submission_time, ticket_channel.id, ticket_channel))
                elif state == MATERIAL_STATE_PENDING:
                    pending.append(ticket_channel)

            submitted.sort(key=lambda item: (item[0], item[1]))
            pending.sort(key=self._ticket_created_sort_key)
            target_index = next(
                (index for index, item in enumerate(submitted) if item[2].id == channel.id),
                None,
            )
            if target_index is None:
                return

            try:
                if target_index + 1 < len(submitted):
                    await channel.move(
                        before=submitted[target_index + 1][2],
                        reason="按材料提交顺序排列人工审核工单",
                    )
                elif target_index > 0:
                    await channel.move(
                        after=submitted[target_index - 1][2],
                        reason="按材料提交顺序排列人工审核工单",
                    )
                elif pending:
                    await channel.move(
                        before=pending[0],
                        reason="已提交工单置于待提交工单之前",
                    )
                else:
                    await channel.move(
                        beginning=True,
                        reason="已提交工单置于审核频道列表最前",
                    )
            except (discord.Forbidden, discord.HTTPException, ValueError) as error:
                print(f"调整工单审核队列失败: channel={channel.id} error={error!r}")

    async def mark_material_submitted(self, channel, *, submitted_at=None):
        """Persist the first valid upload and expose it in the ticket channel prefix."""
        if channel.id in self.material_state_lock:
            return False
        self.material_state_lock.add(channel.id)
        try:
            info = get_ticket_info(channel)
            if str(channel.id) in self.group_confirmations or "已过审" in channel.name:
                return False
            if info.get("上传状态") != "进行中":
                return False
            if info.get("材料状态") == MATERIAL_STATE_SUBMITTED:
                try:
                    saved_submission_at = int(
                        info.get("材料提交时间")
                        or submitted_at
                        or info.get("上传开始")
                        or channel.created_at.timestamp()
                    )
                except (TypeError, ValueError):
                    saved_submission_at = int(channel.created_at.timestamp())
                self.material_submission_times[channel.id] = saved_submission_at
                await self.reposition_submitted_ticket(channel, saved_submission_at)
                return True

            submitted_at = int(
                submitted_at.timestamp()
                if isinstance(submitted_at, datetime.datetime)
                else submitted_at or discord.utils.utcnow().timestamp()
            )
            info["材料状态"] = MATERIAL_STATE_SUBMITTED
            info["材料提交时间"] = str(submitted_at)
            await channel.edit(
                name=build_ticket_channel_name(info, MATERIAL_STATE_SUBMITTED),
                topic=" | ".join(f"{key}: {value}" for key, value in info.items()),
                reason="申请人已提交人工审核材料",
            )
            self.material_submission_times[channel.id] = submitted_at
            await self.reposition_submitted_ticket(channel, submitted_at)
            return True
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"更新工单材料状态失败: channel={channel.id} error={error!r}")
            return False
        finally:
            self.material_state_lock.discard(channel.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Rename an application ticket as soon as its creator uploads the first attachment."""
        if message.author.bot or not message.guild or not message.attachments:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        valid_category_ids = {
            IDS.get("FIRST_REVIEW_CHANNEL_ID"),
            IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID"),
            IDS.get("SECOND_REVIEW_CHANNEL_ID"),
        }
        if message.channel.category_id not in valid_category_ids:
            return

        info = get_ticket_info(message.channel)
        try:
            creator_id = int(info.get("创建者ID", "0"))
        except (TypeError, ValueError):
            return
        if creator_id != message.author.id or info.get("上传状态") != "进行中":
            return

        if info.get("材料状态") == MATERIAL_STATE_SUBMITTED:
            return
        await self.mark_material_submitted(
            message.channel,
            submitted_at=message.created_at,
        )



    async def approve_ticket_logic(self, interaction_or_ctx):
        """带频道级互斥锁的过审入口，防止多个确认窗口重复执行。"""
        channel_id = interaction_or_ctx.channel.id
        if channel_id in self.approval_lock:
            await interaction_or_ctx.followup.send("ℹ️ 此工单正在执行过审，请勿重复操作。", ephemeral=True)
            return False
        self.approval_lock.add(channel_id)
        try:
            return await self._approve_ticket_logic_unlocked(interaction_or_ctx)
        finally:
            self.approval_lock.discard(channel_id)


    async def _approve_ticket_logic_unlocked(self, interaction_or_ctx):
        """核心过审逻辑"""
        channel = interaction_or_ctx.channel
        guild = interaction_or_ctx.guild

        info = get_ticket_info(channel)
        uid = info.get("创建者ID")
        user = guild.get_member(int(uid)) if uid else None
        test_mode = info.get("测试模式") == "是"

        existing = self.group_confirmations.get(str(channel.id))
        if existing and existing.get("message_id"):
            await self.reposition_approved_ticket(channel)
            await interaction_or_ctx.followup.send("此工单已过审，正在等待加群确认，原截止时间保持不变。", ephemeral=True)
            return True

        # 1. 给身份
        if user and not test_mode:
            r_new = guild.get_role(IDS["VERIFICATION_ROLE_ID"])
            r_done = guild.get_role(IDS["HATCHED_ROLE_ID"])
            roles_updated = False
            try:
                if r_new: await user.remove_roles(r_new, reason="审核通过")
                if r_done: await user.add_roles(r_done, reason="审核通过")
                roles_updated = True
            except Exception as e:
                print(f"审核通过后更新身份失败: user={user.id} error={e!r}")

            if not roles_updated:
                await interaction_or_ctx.followup.send(
                    "❌ 身份组更新失败，工单已保留，请检查机器人权限后重试。",
                    ephemeral=True,
                )
                return False

        # 先持久化截止时间，重启和重复过审不会延长确认窗口。
        key = str(channel.id)
        if key not in self.group_confirmations:
            approved_at = discord.utils.utcnow().timestamp()
            self.group_confirmations[key] = {
                "approved_at": approved_at,
                "deadline": approved_at + GROUP_CONFIRM_SECONDS,
                "status": "待确认",
            }
            self.save_group_confirmations()
        state = self.group_confirmations[key]
        info.update({"审核状态": "已过审", "过审时间": str(state["approved_at"]),
                     "加群确认截止": str(state["deadline"]), "上传状态": "已结束"})
        channel = await channel.edit(
            name=build_ticket_channel_name(info, "已过审"),
            topic=" | ".join(f"{k}: {v}" for k, v in info.items()),
            reason="人工审核通过，等待加群确认",
        )
        if not state.get("message_id"):
            embed = discord.Embed(
                title="🎉 审核已通过，请确认是否加群",
                description=("正式成员权限已生效！可扫描下方二维码加入 QQ 群。\n"
                             "请点击 **已加群** 或 **不加群**，点击后工单将归档。\n"
                             f"确认截止：<t:{int(state['deadline'])}:F>（30 分钟）；逾期自动归档。"),
                color=0x73C991,
            )
            embed.set_image(url=APPROVAL_QR_IMAGE_URL)
            message = await channel.send(
                f"<@{uid}>" if uid else None, embed=embed, view=ArchiveRequestView(),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            state["message_id"] = message.id
            self.save_group_confirmations()
            if user and not test_mode:
                try:
                    await user.send(embed=build_ticket_approved_dm(user, guild, channel, info.get("工单ID")),
                                    view=build_ticket_approved_link_view(channel))
                except discord.HTTPException:
                    pass
        await self.reposition_approved_ticket(channel)
        await interaction_or_ctx.followup.send("✅ 已过审，已发送加群确认，30 分钟后自动归档。", ephemeral=True)
        return True

    async def restore_approved_tickets(self):
        """接管升级前尚未清理的已过审工单，并恢复队列位置。"""
        for category_id in (IDS.get("FIRST_REVIEW_CHANNEL_ID"),
                            IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID"),
                            IDS.get("SECOND_REVIEW_CHANNEL_ID")):
            category = self.bot.get_channel(category_id)
            if not category:
                continue
            channels = [c for c in category.text_channels
                        if "已过审" in c.name or str(c.id) in self.group_confirmations]
            for channel in channels:
                info = get_ticket_info(channel)
                if not info.get("工单ID"):
                    continue
                key = str(channel.id)
                try:
                    if key not in self.group_confirmations:
                        # 旧工单没有可靠时间时，升级后重新给予完整的确认窗口。
                        now = discord.utils.utcnow().timestamp()
                        try:
                            approved_at = float(info.get("过审时间", now))
                        except (TypeError, ValueError):
                            approved_at = now
                        self.group_confirmations[key] = {
                            "approved_at": approved_at, "deadline": approved_at + GROUP_CONFIRM_SECONDS,
                            "status": "待确认",
                        }
                        self.save_group_confirmations()
                    state = self.group_confirmations[key]
                    if channel.name != build_ticket_channel_name(info, "已过审"):
                        channel = await channel.edit(name=build_ticket_channel_name(info, "已过审"))
                    if not state.get("message_id"):
                        embed = discord.Embed(
                            title="🎉 审核已通过，请确认是否加群",
                            description=("请扫描二维码，选择 **已加群** 或 **不加群** 后归档。\n"
                                         f"确认截止：<t:{int(state['deadline'])}:F>；逾期自动归档。"),
                            color=0x73C991,
                        )
                        embed.set_image(url=APPROVAL_QR_IMAGE_URL)
                        message = await channel.send(embed=embed, view=ArchiveRequestView())
                        state["message_id"] = message.id
                        self.save_group_confirmations()
                    await self.reposition_approved_ticket(channel)
                except discord.HTTPException as error:
                    print(f"恢复已过审工单失败: channel={key} error={error!r}")

    def save_group_confirmations(self):
        save_json_namespace("ticket_group_confirmations", self.group_confirmations)

    async def reposition_approved_ticket(self, channel):
        category = channel.category
        if not category:
            return
        lock = self.ticket_order_locks.setdefault(category.id, asyncio.Lock())
        async with lock:
            approved = []
            others = []
            for candidate in category.text_channels:
                info = get_ticket_info(candidate)
                if not info.get("工单ID"):
                    continue
                state = self.group_confirmations.get(str(candidate.id))
                if state or "已过审" in candidate.name:
                    timestamp = state["approved_at"] if state else candidate.created_at.timestamp()
                    approved.append((timestamp, candidate.id, candidate))
                else:
                    others.append(candidate)
            approved.sort(key=lambda item: (item[0], item[1]))
            index = next((i for i, item in enumerate(approved) if item[1] == channel.id), None)
            if index is None:
                return
            if index:
                await channel.move(after=approved[index - 1][2], reason="按过审顺序排列已过审工单")
            elif others:
                await channel.move(after=max(others, key=lambda item: item.position), reason="已过审工单排在未提交工单下方")
            elif len(approved) > 1:
                await channel.move(before=approved[1][2], reason="按过审顺序排列已过审工单")

    async def finish_group_confirmation(self, channel, choice=None, interaction=None):
        key = str(channel.id)
        lock = self.group_confirmation_locks.setdefault(key, asyncio.Lock())
        async with lock:
            state = self.group_confirmations.get(key)
            if not state:
                if interaction:
                    await interaction.followup.send("此工单不在等待加群确认，或已归档。", ephemeral=True)
                return False
            if state["status"] == "待确认":
                expired = discord.utils.utcnow().timestamp() >= state["deadline"]
                if not expired and choice is None:
                    return False
                state["status"] = "超时未确认" if expired else choice
                self.save_group_confirmations()
            automatic = state["status"] == "超时未确认"
            archived = await execute_archive(
                self.bot, interaction, channel,
                f"人工审核通过；加群状态：{state['status']}",
                is_timeout=False, archive_kind=ARCHIVE_KIND_APPROVED,
                automatic=automatic, group_status=state["status"],
            )
            if archived:
                self.group_confirmations.pop(key, None)
                self.save_group_confirmations()
            return archived

    @tasks.loop(seconds=30)
    async def check_group_confirmations(self):
        await self.bot.wait_until_ready()
        for key, state in list(self.group_confirmations.items()):
            if state["status"] == "待确认" and discord.utils.utcnow().timestamp() < state["deadline"]:
                continue
            try:
                channel = self.bot.get_channel(int(key)) or await self.bot.fetch_channel(int(key))
                await self.finish_group_confirmation(channel)
            except discord.NotFound:
                self.group_confirmations.pop(key, None)
                self.save_group_confirmations()
            except discord.HTTPException as error:
                print(f"加群确认自动归档失败: channel={key} error={error!r}")

    def cog_unload(self):
        self.reset_daily_quota.cancel()
        self.check_inactive_tickets.cancel()
        self.check_upload_windows.cancel()
        self.check_group_confirmations.cancel()
        self.close_tickets_at_night.cancel()


    async def update_panel_message(self):
        ch = self.bot.get_channel(IDS["TICKET_PANEL_CHANNEL_ID"])
        if not ch: return

        d = load_quota_data()
        p_data = STRINGS["embeds"]["panel"]
        now = datetime.datetime.now(QUOTA["TIMEZONE"])

        desc = p_data["description_head"] + "\n" + p_data["req_newbie"] + "\n"
        desc += f"**-` 审核开放时间: 每日 17:00 - 23:00 `**\n**-` 今日剩余名额: {d['daily_quota_left']}/{QUOTA['DAILY_TICKET_LIMIT']} `**"

        is_active_suspension = False

        # 使用持久化数据判断暂停
        if self.schedule_data.get("suspended", False):
            # 将时间戳转为 datetime
            start_ts = self.schedule_data.get("start_dt")
            end_ts = self.schedule_data.get("end_dt")

            start_dt = datetime.datetime.fromtimestamp(start_ts, QUOTA["TIMEZONE"]) if start_ts else None
            end_dt = datetime.datetime.fromtimestamp(end_ts, QUOTA["TIMEZONE"]) if end_ts else None

            if not start_dt:
                is_active_suspension = True
            else:
                if now >= start_dt:
                    if end_dt:
                        if now < end_dt:
                            is_active_suspension = True
                        else:
                            is_active_suspension = False
                    else:
                        is_active_suspension = True
                else:
                    is_active_suspension = False

        if is_active_suspension:
            label = p_data["btn_suspended"]
            disabled = False # 按钮不禁用，但点进去会提示暂停
        elif d["daily_quota_left"] <= 0:
            label = p_data["btn_full"]
            disabled = True
        elif not (8 <= now.hour < 23):
            label = p_data["btn_rest"]
            disabled = True
            desc += "\n\n**" + p_data["status_off_time"] + "**"
        else:
            label = p_data["btn_normal"]
            disabled = False

        embed = discord.Embed(title=p_data["title"], description=desc, color=STYLE.get("KIMI_YELLOW", 0xFFFF00))
        view = TicketPanelView(self)
        btn = view.children[0]
        btn.label = label
        btn.disabled = disabled

        try:
            async for m in ch.history(limit=5):
                if m.author == self.bot.user and m.embeds and "全区权限申请" in m.embeds[0].title:
                    await m.edit(embed=embed, view=view)
                    return
            await ch.send(embed=embed, view=view)
        except Exception as e:
            print(f"刷新面板失败: {e}")

    # ======================================================================================
    # --- 定时任务 ---
    # ======================================================================================

    @tasks.loop(time=datetime.time(hour=8, minute=0, tzinfo=QUOTA["TIMEZONE"]))
    async def reset_daily_quota(self):
        await self.bot.wait_until_ready()
        today_str = datetime.datetime.now(QUOTA["TIMEZONE"]).strftime('%Y-%m-%d')
        d = load_quota_data()
        if d["last_reset_date"] != today_str:
            d["last_reset_date"] = today_str
            d["daily_quota_left"] = QUOTA["DAILY_TICKET_LIMIT"]
            save_quota_data(d)
            await self.update_panel_message()

    @tasks.loop(time=datetime.time(hour=23, minute=0, tzinfo=QUOTA["TIMEZONE"]))
    async def close_tickets_at_night(self):
        await self.bot.wait_until_ready()
        await self.update_panel_message()

    @tasks.loop(seconds=30)
    async def check_upload_windows(self):
        """处理已到期上传窗口；状态存于 Topic，重启后仍可恢复。"""
        await self.bot.wait_until_ready()
        now = discord.utils.utcnow()
        categories = [
            self.bot.get_channel(IDS.get("FIRST_REVIEW_CHANNEL_ID")),
            self.bot.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID")),
            self.bot.get_channel(IDS.get("SECOND_REVIEW_CHANNEL_ID")),
        ]
        for category in categories:
            if not category:
                continue
            for channel in list(category.text_channels):
                info = get_ticket_info(channel)
                if str(channel.id) in self.group_confirmations or "已过审" in channel.name:
                    continue
                if info.get("上传状态") != "进行中":
                    continue
                try:
                    started_at = int(info.get("上传开始", "0"))
                    deadline_at = int(info.get("上传截止", "0"))
                    creator_id = int(info.get("创建者ID", "0"))
                except (TypeError, ValueError):
                    continue
                if not started_at or not deadline_at or not creator_id or now.timestamp() < deadline_at:
                    continue

                attachment_count = 0
                first_attachment_at = None
                after = datetime.datetime.fromtimestamp(started_at, tz=datetime.timezone.utc)
                async for message in channel.history(limit=None, after=after, oldest_first=True):
                    if message.author.id == creator_id:
                        attachment_count += len(message.attachments)
                        if message.attachments and first_attachment_at is None:
                            first_attachment_at = message.created_at

                if attachment_count <= 0:
                    await execute_archive(
                        self.bot,
                        None,
                        channel,
                        f"开始上传后 {UPLOAD_WINDOW_MINUTES} 分钟内未检测到任何材料",
                        is_timeout=True,
                        archive_kind=ARCHIVE_KIND_TIMEOUT,
                        automatic=True,
                    )
                    continue

                # 实时消息事件可能因重启或短暂断线漏掉；截止扫描负责兜底校正。
                await self.mark_material_submitted(
                    channel,
                    submitted_at=first_attachment_at,
                )

                member = channel.guild.get_member(creator_id)
                if member:
                    overwrite = channel.overwrites_for(member)
                    overwrite.send_messages = False
                    overwrite.attach_files = False
                    try:
                        await channel.set_permissions(
                            member,
                            overwrite=overwrite,
                            reason="人工审核材料上传时间已截止",
                        )
                    except (discord.Forbidden, discord.HTTPException) as error:
                        print(f"锁定工单上传权限失败: channel={channel.id} error={error!r}")
                        continue

                info["上传状态"] = "已截止"
                info["材料状态"] = MATERIAL_STATE_SUBMITTED
                info["上传材料数"] = str(attachment_count)
                new_topic = " | ".join(f"{key}: {value}" for key, value in info.items())
                try:
                    await channel.edit(
                        name=build_ticket_channel_name(info, MATERIAL_STATE_SUBMITTED),
                        topic=new_topic,
                        reason="人工审核材料上传已截止",
                    )
                    embed = discord.Embed(
                        title="🔒 材料上传已截止",
                        description=(
                            f"已收集 **{attachment_count} 个附件**，"
                            f"{member.mention if member else f'<@{creator_id}>'} 现已停止补充材料。\n"
                            "审核小蛋请开始审核。"
                        ),
                        color=0xF0A45D,
                    )
                    await channel.send(
                        f"<@&{REVIEWER_ROLE_ID}>",
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False,
                            users=False,
                            roles=True,
                        ),
                    )
                except (discord.Forbidden, discord.HTTPException) as error:
                    print(f"发送上传截止通知失败: channel={channel.id} error={error!r}")

    @tasks.loop(hours=1)
    async def check_inactive_tickets(self):
        await self.bot.wait_until_ready()
        now = discord.utils.utcnow()

        # 遍历一审和二审分类
        cats = [
            self.bot.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"]), 
            self.bot.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID")),
            self.bot.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])]
        for cat in cats:
            if not cat: continue
            for channel in cat.text_channels:
                valid_prefixes = [
                    "待提交", "已提交", "测试待提交", "测试已提交",
                    "一审中", "二审中", "审核中", "已过审",
                ]
                if not any(prefix in channel.name for prefix in valid_prefixes):
                    continue

                try:
                    info = get_ticket_info(channel)
                    if str(channel.id) in self.group_confirmations:
                        continue
                    if info.get("上传状态") == "进行中":
                        continue
                    creator_id = info.get("创建者ID")

                    # 扫描历史消息 & 收集状态
                    last_active = channel.created_at
                    found_active = False
                    has_reminded = False
                    is_locked = False
                    is_approved_waiting = False
                    last_msg_time = None

                    # 遍历历史消息
                    i = 0
                    async for m in channel.history(limit=20):
                        if i == 0: # 检查最新一条
                            last_msg_time = m.created_at
                            if m.author.id == self.bot.user.id and m.embeds:
                                embed_title = m.embeds[0].title or ""
                                if "恭喜小宝加入社区" in embed_title:
                                    is_approved_waiting = True

                        raw_content = m.content or ""
                        e_title = (m.embeds[0].title or "") if m.embeds else ""
                        e_desc = (m.embeds[0].description or "") if m.embeds else ""
                        full_text = f"{raw_content} {e_title} {e_desc}"

                        if "已锁定" in full_text:
                            is_locked = True
                        if m.author.bot and ("温馨提醒" in full_text):
                            has_reminded = True

                        if not found_active:
                            is_bot_remind = m.author.bot and ("温馨提醒" in full_text)
                            if not is_bot_remind:
                                last_active = m.created_at
                                found_active = True
                        i += 1

                    if not last_msg_time: continue

                    diff_active = now - last_active
                    is_name_approved = "已过审" in channel.name


                    # --- 逻辑分支 ---

                    # 2. 常规超时归档 (12小时)
                    if is_name_approved:
                        continue

                    # 北京时间最近一次 23:30 截止线：若此后无新消息，直接按超时处理
                    now_cn = now.astimezone(QUOTA["TIMEZONE"])
                    cutoff_today = now_cn.replace(hour=23, minute=30, second=0, microsecond=0)
                    latest_cutoff = cutoff_today if now_cn >= cutoff_today else (cutoff_today - datetime.timedelta(days=1))
                    is_silent_after_cutoff = last_active.astimezone(QUOTA["TIMEZONE"]) <= latest_cutoff

                    if is_silent_after_cutoff:
                        await execute_archive(self.bot, None, channel, "北京时间23:30后无新消息", is_timeout=True)
                    elif diff_active > datetime.timedelta(hours=TIMEOUT_HOURS_ARCHIVE):
                        await execute_archive(self.bot, None, channel, f"超过{TIMEOUT_HOURS_ARCHIVE}小时无活动", is_timeout=True)

                    # 3. 温馨提醒 (6小时)
                    elif diff_active > datetime.timedelta(hours=TIMEOUT_HOURS_REMIND):
                        if not has_reminded and not is_approved_waiting and not is_locked:
                            embed = discord.Embed(title="⏰ 温馨提醒", description=f"工单已沉睡超过 {TIMEOUT_HOURS_REMIND} 小时！\n超过 {TIMEOUT_HOURS_ARCHIVE} 小时会自动归档哦！", color=0xFFA500)
                            txt = f"<@{creator_id}>" if creator_id else ""
                            await channel.send(txt, embed=embed)

                except Exception as e:
                    print(f"检查频道 {channel.name} 错误: {e}")

        # 升级后自动接管旧归档分类，补写新版记录并清理历史积压频道。
        legacy_archive_cat = self.bot.get_channel(IDS.get("ARCHIVE_CHANNEL_ID"))
        if legacy_archive_cat:
            for channel in list(legacy_archive_cat.text_channels):
                info = get_ticket_info(channel)
                if not info.get("工单ID"):
                    continue
                if "超时" in channel.name:
                    archive_kind = ARCHIVE_KIND_TIMEOUT
                    reason = "旧超时归档工单自动迁移"
                elif "已过审" in channel.name:
                    archive_kind = ARCHIVE_KIND_APPROVED
                    reason = "旧已过审工单自动迁移"
                elif "归档" in channel.name or "未过审" in channel.name:
                    archive_kind = ARCHIVE_KIND_REJECTED
                    reason = "旧未过审工单自动迁移"
                else:
                    continue
                try:
                    await execute_archive(
                        self.bot,
                        None,
                        channel,
                        reason,
                        is_timeout=archive_kind == ARCHIVE_KIND_TIMEOUT,
                        archive_kind=archive_kind,
                        automatic=True,
                        notify_user=False,
                    )
                    await asyncio.sleep(0)
                except Exception as error:
                    print(f"迁移旧归档工单失败: channel={channel.id} error={error!r}")

    # ======================================================================================
    # --- 命令组 (Slash Commands) ---
    # ======================================================================================

    ticket = discord.SlashCommandGroup("工单", "工单相关指令")

    @ticket.command(name="手动过审", description="（审核小蛋用）一键给身份、发通知、移频道！")
    @is_reviewer_egg()
    async def manual_approve(self, ctx: discord.ApplicationContext):
        if not get_ticket_info(ctx.channel).get("工单ID"):
            return await ctx.respond("这里不是工单频道哦！", ephemeral=True)
        await ctx.respond(
            embed=build_approve_confirmation_embed(ctx.channel),
            view=ApproveTicketConfirmationView(ctx.author.id),
            ephemeral=True,
        )

    @ticket.command(name="修复按钮", description="（审核小蛋用）按钮没反应？尝试修复当前频道已有的面板！")
    @is_reviewer_egg()
    async def fix_ticket_button(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 1. 检查是否在工单频道
        if not get_ticket_info(ctx.channel).get("工单ID"):
            await ctx.followup.send("这里不是工单频道哦！", ephemeral=True)
            return

        # 2. 尝试寻找并修复旧消息
        fixed = False
        target_titles = ["已创建", "管理员操作面板", "一审中", "审核中"]  # 识别面板的关键词

        try:
            async for message in ctx.channel.history(limit=50):  # 搜索最近50条消息
                if message.author.id == self.bot.user.id and message.embeds:
                    embed_title = message.embeds[0].title or ""
                    # 只要标题匹配或者是工单初始消息，就尝试修复View
                    if any(t in embed_title for t in target_titles):
                        await message.edit(view=TicketActionView())
                        fixed = True
                        break
        except Exception as e:
            print(f"修复按钮时出错: {e}")

        # 3. 反馈结果
        if fixed:
            await ctx.followup.send("✅ 已成功修复当前频道的旧操作面板！按钮应该能用啦！", ephemeral=True)
        else:
            embed = discord.Embed(
                title="🔧 管理员操作面板 (补发)",
                description="呜...本蛋没找到旧的面板消息，所以给你补发了一个新的！",
                color=STYLE["KIMI_YELLOW"]
            )
            await ctx.channel.send(embed=embed, view=TicketActionView())
            await ctx.followup.send("⚠️ 未找到可修复的旧消息，已为你补发新的面板。", ephemeral=True)


    @ticket.command(name="中止新蛋审核", description="（管理员）弹出面板，设置定时或立即中止工单申请。")
    @is_reviewer_egg()
    async def suspend_audit(self, ctx: discord.ApplicationContext):
        modal = SuspendAuditModal(self)
        await ctx.send_modal(modal)

    @ticket.command(name="恢复新蛋审核", description="（管理员）手动立即恢复审核功能。")
    @is_reviewer_egg()
    async def resume_audit(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 清除所有暂停状态 (逻辑同上)
        self.schedule_data = {
            "suspended": False,
            "reason": None,
            "start_dt": None,
            "end_dt": None
        }
        save_audit_schedule(self.schedule_data)

        await self.update_panel_message()
        await ctx.followup.send("✅ **已手动恢复审核功能！**\n现在大家可以正常创建工单了。", ephemeral=True)


    @ticket.command(name="清理重复工单", description="（慎用）一键删除指定用户所有重复创建的工单，保留最早的一个。")
    @is_reviewer_egg()
    async def clean_user_duplicates(self, ctx: discord.ApplicationContext,
                                    user: discord.Member,
                                    dry_run: discord.Option(bool, "是否仅模拟（不真删）", default=True)):
        """
        查找该用户创建的所有工单频道，保留最早创建的一个，其余删除并返还额度。
        """
        await ctx.defer(ephemeral=True)

        # 扫描所有相关分类
        categories = [
            self.bot.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"]),
            self.bot.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID")),
            self.bot.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        ]

        user_channels = []
        for cat in categories:
            if not cat or not isinstance(cat, discord.CategoryChannel): continue
            for ch in cat.text_channels:
                # 检查 topic 中的用户ID
                if ch.topic and f"创建者ID: {user.id}" in ch.topic:
                    user_channels.append(ch)

        if not user_channels:
            return await ctx.followup.send(f"✅ 未在审核区发现用户 {user.mention} 的任何工单。", ephemeral=True)

        if len(user_channels) == 1:
            return await ctx.followup.send(f"✅ 用户 {user.mention} 只有一个工单 {user_channels[0].mention}，无需清理。", ephemeral=True)

        # 按创建时间排序：最早的在前
        user_channels.sort(key=lambda c: c.created_at)

        keep_channel = user_channels[0]
        delete_channels = user_channels[1:]

        msg = f"🔍 **发现重复工单！**\n用户: {user.mention}\n共发现: {len(user_channels)} 个\n\n"
        msg += f"🛡️ **将保留**: {keep_channel.mention} (创建于 {keep_channel.created_at.strftime('%H:%M:%S')})\n"
        msg += f"🗑️ **将删除**: {len(delete_channels)} 个 (并返还对应额度)\n"

        for c in delete_channels:
            msg += f"- {c.mention} ({c.created_at.strftime('%H:%M:%S')})\n"

        if dry_run:
            msg += "\n⚠️ **当前为模拟模式 (Dry Run)**，未执行实际删除。\n如果要执行，请重新运行命令并将 `dry_run` 设为 `False`。"
            await ctx.followup.send(msg, ephemeral=True)
        else:
            # 执行删除
            d = load_quota_data()
            count = 0
            for c in delete_channels:
                try:
                    await c.delete(reason=f"清理重复工单 - 操作人: {ctx.author.name}")
                    count += 1
                except Exception as e:
                    msg += f"\n❌ 删除 {c.name} 失败: {e}"

            # 返还额度
            d["daily_quota_left"] += count
            save_quota_data(d)
            await self.update_panel_message()

            msg += f"\n✅ **清理完成！** 已删除 {count} 个频道，并返还了 {count} 个名额。\n当前剩余名额: {d['daily_quota_left']}"
            await ctx.followup.send(msg, ephemeral=True)

    @ticket.command(name="恢复工单状态", description="（审核小蛋用）误操作恢复！")
    @is_reviewer_egg()
    async def recover_ticket(self, ctx: discord.ApplicationContext,
                             state: discord.Option(str, "选择恢复到的状态", choices=["一审中", "二审中", "已过审", "归档"]),
                             reason: discord.Option(str, "给用户的解释", required=False, default="管理员手动调整了工单状态。")):
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        info = get_ticket_info(channel)
        if not info.get("工单ID"): return await ctx.followup.send("无效工单頻道", ephemeral=True)

        # 🟢 逻辑完善：根据状态确定目标位置，如果是恢复到一审，需要考虑容量
        if state == "一审中":
             c1 = ctx.guild.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"])
             c1_extra = ctx.guild.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID"))

             target_cat = c1
             # 如果主分类满了，且有备用分类，则放到备用
             if len(c1.channels) >= 50:
                 if c1_extra and len(c1_extra.channels) < 50:
                     target_cat = c1_extra
        elif state in ["二审中", "已过审"]:
            target_cat = ctx.guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        elif state == "归档":
            target_cat = ctx.guild.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        else:
            target_cat = None

        if not target_cat: return await ctx.followup.send("找不到目标分类配置或分类已满", ephemeral=True)

        overwrites = {ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False)}
        reviewer_role = ctx.guild.get_role(REVIEWER_ROLE_ID)
        if reviewer_role:
            overwrites[reviewer_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        uid = info.get("创建者ID")
        user = ctx.guild.get_member(int(uid)) if uid else None
        if user and state != "归档":
            overwrites[user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        new_name = f"{state}-{info.get('工单ID')}-{info.get('创建者')}"
        await channel.edit(name=new_name, category=target_cat, overwrites=overwrites, reason=reason)

        embed = discord.Embed(title="🔄 工单状态已恢复", description=f"恢复为：**{state}**\n原因: {reason}", color=STYLE["KIMI_YELLOW"])
        await channel.send(embed=embed)
        if user:
            try: await user.send(f"你的工单 `{info.get('工单ID')}` 状态已变更为: {state}。")
            except: pass
        await ctx.followup.send("恢复完成！", ephemeral=True)

    @ticket.command(name="超时归档", description="（审核小蛋用）手动标记超时。")
    @is_reviewer_egg()
    async def timeout_archive(self, ctx: discord.ApplicationContext, note: discord.Option(str, "备注", required=False)="手动超时"):
        await ctx.defer(ephemeral=True)
        if not get_ticket_info(ctx.channel).get("工单ID"): return await ctx.followup.send("这里不是工单频道", ephemeral=True)

        await execute_archive(self.bot, ctx, ctx.channel, note, is_timeout=True)

    @ticket.command(name="删除并释放名额", description="（审核小蛋用）删除工单并返还名额。")
    @is_reviewer_egg()
    async def delete_and_refund(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        if not get_ticket_info(channel).get("工单ID"): return await ctx.followup.send("无效频道", ephemeral=True)

        d = load_quota_data()
        d["daily_quota_left"] += 1
        save_quota_data(d)
        await self.update_panel_message()

        await channel.delete(reason=f"管理员 {ctx.author.name} 删除并返还名额")

    @ticket.command(name="批量更名", description="（管理用）一键将【一审中】前缀修正为【审核中】")
    @is_reviewer_egg()
    async def bulk_rename_tickets(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 🟢 逻辑修改：同时扫描主分类和备用分类
        categories = [
            self.bot.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"]),
            self.bot.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID"))
        ]

        channels_to_rename = []
        for cat in categories:
            if not cat: continue
            channels_to_rename.extend([ch for ch in cat.text_channels if "一审中" in ch.name])

        if not channels_to_rename:
            await ctx.followup.send("没有发现需要更名的频道哦~", ephemeral=True); return

        progress_msg = await ctx.followup.send(f"开始处理... 预计需要 {len(channels_to_rename) * 2} 秒", ephemeral=True)
        success_count = 0

        for channel in channels_to_rename:
            try:
                old_name = channel.name
                new_name = old_name.replace("一审中", "审核中")
                if old_name != new_name:
                    await channel.edit(name=new_name)
                    success_count += 1
                    await asyncio.sleep(1.5)
            except Exception as e:
                print(f"更名出错: {e}")

        await progress_msg.edit(content=f"✅ 处理完成！\n扫描: {len(channels_to_rename)} 个\n更名: {success_count} 个")

    # 上下文菜单：右键消息超时归档
    @discord.message_command(name="🚫超时归档此工单")
    @is_reviewer_egg()
    async def timeout_archive_ctx(self, ctx: discord.ApplicationContext, message: discord.Message):
        if not get_ticket_info(ctx.channel).get("工单ID"): return await ctx.respond("无效频道", ephemeral=True)
        await ctx.respond("确认归档？", view=TimeoutOptionView(self.bot, ctx.channel), ephemeral=True)

    # --- 工单计划管理组 ---
    schedule_group = discord.SlashCommandGroup("工单计划", "管理工单/审核系统的维护计划", checks=[is_reviewer_egg()])

    @schedule_group.command(name="查看", description="查看当前工单审核的自动暂停计划")
    async def view_audit_schedule(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 从字典读取数据
        is_suspended = self.schedule_data.get("suspended", False)

        if not is_suspended:
            desc = "🟢 **当前工单系统正常开放**\n没有检测到预设的暂停计划。"
            color = 0x00FF00
        else:
            now = datetime.datetime.now(QUOTA["TIMEZONE"])
            desc = "🔴 **检测到维护/暂停计划**\n"

            # 显示预设的原因
            reason = self.schedule_data.get("reason") or "未填写原因"
            desc += f"原因: {reason}\n"

            # 读取时间戳
            start_ts = self.schedule_data.get("start_dt")
            end_ts = self.schedule_data.get("end_dt")

            # 转换时间用于显示
            if start_ts:
                start_dt = datetime.datetime.fromtimestamp(start_ts, QUOTA["TIMEZONE"])
                start_str = start_dt.strftime('%m-%d %H:%M')
            else:
                start_dt = None
                start_str = "立即生效"

            if end_ts:
                end_dt = datetime.datetime.fromtimestamp(end_ts, QUOTA["TIMEZONE"])
                end_str = end_dt.strftime('%m-%d %H:%M')
            else:
                end_dt = None
                end_str = "手动恢复"

            desc += f"📅 **计划时间表**:\nStart: `{start_str}`\nEnd: `{end_str}`\n\n"

            # 判断当前这一秒是否真的暂停了
            is_active_now = False
            if not start_dt:
                is_active_now = True
            elif now >= start_dt:
                if not end_dt or now < end_dt:
                    is_active_now = True

            status_text = "⛔ **服务已暂停** (当前生效中)" if is_active_now else "⏳ **计划等待执行中** (尚未开始)"
            desc += f"⚡ **当前状态**: {status_text}"
            color = 0xFF0000

        await ctx.followup.send(embed=discord.Embed(title="📅 工单计划管理器", description=desc, color=color), ephemeral=True)


    @schedule_group.command(name="清除", description="移除所有定时计划并立即恢复工单系统")
    async def clear_audit_schedule(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 重置所有状态到字典
        self.schedule_data = {
            "suspended": False,
            "reason": None,
            "start_dt": None,
            "end_dt": None
        }
        # 保存到文件
        save_audit_schedule(self.schedule_data)

        # 立即更新面板显示
        await self.update_panel_message()

        await ctx.followup.send(
            embed=discord.Embed(description="✅ **已清除所有计划任务！**\n工单系统已强制恢复为开放状态，面板已刷新。", color=0x00FF00),
            ephemeral=True
        )


    # --- 名额管理组 ---
    quota_mg = discord.SlashCommandGroup("名额管理", "（仅限审核小蛋）手动调整工单名额~", checks=[is_reviewer_egg()])

    @quota_mg.command(name="重置", description="将今天的剩余名额恢复到最大值！")
    async def reset_quota(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        d = load_quota_data(); d["daily_quota_left"] = QUOTA["DAILY_TICKET_LIMIT"]
        save_quota_data(d); await self.update_panel_message()
        await ctx.followup.send(f"已重置为 {QUOTA['DAILY_TICKET_LIMIT']}", ephemeral=True)

    @quota_mg.command(name="设置", description="手动设置今天的剩余名额数量！")
    async def set_quota(self, ctx: discord.ApplicationContext, amount: discord.Option(int)):
        await ctx.defer(ephemeral=True)
        if amount < 0: return await ctx.followup.send("不能为负", ephemeral=True)
        d = load_quota_data(); d["daily_quota_left"] = amount
        save_quota_data(d); await self.update_panel_message()
        await ctx.followup.send(f"已设置为 {amount}", ephemeral=True)

    @quota_mg.command(name="增加", description="给今天的剩余名额增加指定数量！")
    async def add_quota(self, ctx: discord.ApplicationContext, amount: discord.Option(int)):
        await ctx.defer(ephemeral=True)
        if amount <= 0: return await ctx.followup.send("必须大于0", ephemeral=True)
        d = load_quota_data(); d["daily_quota_left"] += amount
        save_quota_data(d); await self.update_panel_message()
        await ctx.followup.send(f"已增加，当前: {d['daily_quota_left']}", ephemeral=True)
