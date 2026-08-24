import discord
from discord.ext import commands
import json
import os
import datetime

# 相对导入可能在Cog加载时会有问题，建议从项目根目录绝对导入配置
from config import IDS, QUOTA, STYLE
from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace

# --- 常量 ---
REVIEWER_ROLE_ID = 1452321798308888776
# 兼容模块外可能仍在使用的旧名称；该 Snowflake 实际指向身份组，不是用户。
SPECIFIC_REVIEWER_ID = REVIEWER_ROLE_ID
TIMEOUT_HOURS_ARCHIVE = 6
TIMEOUT_HOURS_REMIND = 3
STRINGS_PATH = os.path.join(os.path.dirname(__file__), 'strings.json')
QQ_GROUP_QR_URL = "https://discord.com/channels/1397629012292931726/1520276633498419220"
ARCHIVE_KIND_APPROVED = "approved"
ARCHIVE_KIND_TIMEOUT = "timeout"
ARCHIVE_KIND_REJECTED = "rejected"

ARCHIVE_STYLES = {
    ARCHIVE_KIND_APPROVED: ("✅ 已过审工单", 0x57F287),
    ARCHIVE_KIND_TIMEOUT: ("⏰ 超时工单", 0xF0A45D),
    ARCHIVE_KIND_REJECTED: ("🚫 未过审工单", 0xED4245),
}


def build_approved_archive_dm(member, guild, ticket_id, *, automatic=False):
    """Build the DM sent after an approved audit ticket is archived."""
    archive_note = (
        "由于等待确认超时，系统已经自动完成归档。"
        if automatic
        else "你已完成最后确认，审核工单现已安全归档。"
    )
    embed = discord.Embed(
        title="🎉 人工审核已通过｜正式成员权限已生效",
        description=(
            f"嗨，**{member.display_name}**！你在 **{guild.name}** 的人工审核流程已经全部完成。\n"
            f"{archive_note} 已获得的正式成员身份和社区权限不会受到影响。"
        ),
        color=0x8FA8C7,
    )
    embed.add_field(name="🧾 工单编号", value=f"`{ticket_id}`", inline=False)
    embed.add_field(
        name="💬 还想加入 QQ 闲聊群？",
        value=(
            "如果你还想加入社区 QQ 闲聊群，可以前往 "
            f"[QQ群二维码领取频道]({QQ_GROUP_QR_URL}) 获取最新二维码。\n"
            "加入闲聊群是可选的，不会影响你的 Discord 社区权限。"
        ),
        inline=False,
    )
    embed.add_field(
        name="💛 欢迎常来玩",
        value="审核辛苦啦！之后请继续遵守社区守则，祝你玩得开心～",
        inline=False,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="审核流程已完成 · 正式成员权限继续有效")
    return embed


def build_qq_group_link_view():
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label="前往获取 QQ 群二维码",
            emoji="💬",
            style=discord.ButtonStyle.link,
            url=QQ_GROUP_QR_URL,
        )
    )
    return view


async def send_approved_archive_dm(member, guild, ticket_id, *, automatic=False):
    """Send an approved-ticket archive DM without affecting the archive flow."""
    try:
        await member.send(
            embed=build_approved_archive_dm(member, guild, str(ticket_id or "未知"), automatic=automatic),
            view=build_qq_group_link_view(),
        )
        return True
    except discord.Forbidden:
        print(f"无法发送审核归档私信: user={member.id} reason=dm_closed")
    except discord.HTTPException as error:
        print(f"发送审核归档私信失败: user={member.id} error={error!r}")
    return False


def _format_archive_time(value: datetime.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return f"<t:{int(value.timestamp())}:F>\n<t:{int(value.timestamp())}:R>"


def build_ticket_archive_embed(
    *,
    ticket_id: str,
    creator_id: str | int | None,
    creator_name: str,
    reason: str,
    opened_at: datetime.datetime,
    closed_at: datetime.datetime,
    archive_kind: str,
    operator: str = "系统自动",
    qq_number: str | None = None,
) -> discord.Embed:
    """Build the durable archive record posted to the ticket log channel."""
    title, color = ARCHIVE_STYLES.get(archive_kind, ARCHIVE_STYLES[ARCHIVE_KIND_REJECTED])
    embed = discord.Embed(
        title=f"{title} · #{ticket_id}",
        description="人工审核工单处理完毕，原工单频道已进入自动清理流程。",
        color=color,
        timestamp=closed_at,
    )
    embed.add_field(name="📌 归档原因", value=str(reason or "未填写"), inline=False)
    embed.add_field(name="⏱️ 工单开启时间", value=_format_archive_time(opened_at), inline=True)
    embed.add_field(name="🔒 工单关闭时间", value=_format_archive_time(closed_at), inline=True)
    embed.add_field(name="🧾 工单编号", value=f"`{ticket_id}`", inline=True)
    embed.add_field(name="🆔 用户 DC ID", value=f"`{creator_id or '未知'}`", inline=True)
    embed.add_field(name="👤 用户名", value=str(creator_name or "未知用户"), inline=True)
    embed.add_field(name="🛡️ 处理人", value=str(operator or "系统自动"), inline=True)
    if archive_kind == ARCHIVE_KIND_APPROVED:
        embed.add_field(name="🐧 QQ 号码", value=f"`{qq_number}`" if qq_number else "`尚未录入`", inline=False)
    embed.set_footer(text="人工审核归档 · 原工单频道已自动清理")
    return embed


def _is_archive_staff(interaction: discord.Interaction) -> bool:
    user_role_ids = {getattr(role, "id", 0) for role in getattr(interaction.user, "roles", [])}
    if REVIEWER_ROLE_ID in user_role_ids:
        return True
    role_id = IDS.get("SUPER_EGG_ROLE_ID", 0)
    return role_id in user_role_ids


class TicketArchiveQQModal(discord.ui.Modal):
    def __init__(self, message: discord.Message):
        super().__init__(title="录入已过审用户 QQ")
        self.archive_message = message
        self.qq_input = discord.ui.InputText(
            label="QQ 号码",
            placeholder="请输入 5～12 位 QQ 号码",
            min_length=5,
            max_length=12,
            required=True,
        )
        self.add_item(self.qq_input)

    async def callback(self, interaction: discord.Interaction):
        qq_number = str(self.qq_input.value or "").strip()
        if not qq_number.isdigit() or not 5 <= len(qq_number) <= 12:
            return await interaction.response.send_message("❌ QQ 号码必须为 5～12 位数字。", ephemeral=True)
        if not self.archive_message.embeds:
            return await interaction.response.send_message("❌ 找不到原归档记录。", ephemeral=True)

        embed = self.archive_message.embeds[0].copy()
        for index, field in enumerate(embed.fields):
            if field.name == "🐧 QQ 号码":
                embed.set_field_at(index, name=field.name, value=f"`{qq_number}`", inline=False)
                break
        else:
            embed.add_field(name="🐧 QQ 号码", value=f"`{qq_number}`", inline=False)

        await interaction.response.defer(ephemeral=True)
        await self.archive_message.edit(embed=embed, view=ApprovedTicketArchiveView())
        await interaction.followup.send(f"✅ 已录入 QQ：`{qq_number}`，归档记录已更新。", ephemeral=True)


class ApprovedTicketArchiveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if _is_archive_staff(interaction):
            return True
        await interaction.response.send_message("❌ 只有审核管理人员可以录入 QQ。", ephemeral=True)
        return False

    @discord.ui.button(
        label="录入 / 修改 QQ",
        emoji="🐧",
        style=discord.ButtonStyle.primary,
        custom_id="ticket_archive_record_qq",
    )
    async def record_qq(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketArchiveQQModal(interaction.message))

# --- 文本加载 ---
def load_strings():
    try:
        with open(STRINGS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading strings.json: {e}")
        return {}

STRINGS = load_strings()

# --- 权限检查 ---
def is_reviewer_egg():
    """权限检查装饰器"""
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not ctx.guild:
            await ctx.respond(STRINGS["messages"]["err_not_guild"], ephemeral=True)
            return False

        reviewer_role = ctx.guild.get_role(REVIEWER_ROLE_ID)
        if reviewer_role and reviewer_role in ctx.author.roles:
            return True

        super_egg_role = ctx.guild.get_role(IDS.get("SUPER_EGG_ROLE_ID", 0))
        if super_egg_role and super_egg_role in ctx.author.roles:
            return True

        await ctx.respond(STRINGS["messages"]["err_not_staff"], ephemeral=True)
        return False
    return commands.check(predicate)

# --- 频道信息解析 ---
def get_ticket_info(channel: discord.TextChannel):
    info = {}
    if not channel.topic: return info
    try:
        parts = channel.topic.split(" | ")
        for part in parts:
            if ": " in part:
                key, value = part.split(": ", 1)
                info[key] = value
    except Exception: pass
    return info

# --- 额度管理 ---
def load_quota_data():
    default = {"last_reset_date": "2000-01-01", "daily_quota_left": QUOTA["DAILY_TICKET_LIMIT"]}
    raw = load_json_namespace(
        "ticket_quota", legacy_file=QUOTA["QUOTA_FILE_PATH"], default=default
    )
    return raw if isinstance(raw, dict) else default

def save_quota_data(data):
    save_json_namespace("ticket_quota", data)

# --- 通用归档逻辑 ---
async def execute_archive(
    bot,
    interaction,
    channel,
    note,
    is_timeout=True,
    log_title_override=None,
    *,
    archive_kind=None,
    automatic=False,
    notify_user=True,
):
    """
    执行归档操作的核心逻辑
    """
    info = get_ticket_info(channel)
    ticket_id = info.get("工单ID", "未知")
    creator_id = info.get("创建者ID")
    creator_name = info.get("创建者", "未知用户")
    actor = getattr(interaction, "user", None) or getattr(interaction, "author", None)
    operator = getattr(actor, "mention", None) or "系统自动"
    if archive_kind is None:
        archive_kind = ARCHIVE_KIND_TIMEOUT if is_timeout else ARCHIVE_KIND_REJECTED

    # Modal submissions may not have been acknowledged yet.
    if interaction:
        response = getattr(interaction, "response", None)
        try:
            if response and hasattr(response, "is_done") and not response.is_done():
                await response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass

    # 1. 先写入归档记录；失败时保留原频道，避免无记录删除。
    log_channel = bot.get_channel(IDS.get("TICKET_LOG_CHANNEL_ID") or 1419652525249794128)
    if not log_channel:
        if interaction:
            await interaction.followup.send("❌ 找不到工单归档频道，原工单已保留。", ephemeral=True)
        return False

    closed_at = discord.utils.utcnow()
    archive_embed = build_ticket_archive_embed(
        ticket_id=str(ticket_id),
        creator_id=creator_id,
        creator_name=creator_name,
        reason=str(note or log_title_override or "未填写"),
        opened_at=channel.created_at,
        closed_at=closed_at,
        archive_kind=archive_kind,
        operator=operator,
    )
    try:
        await log_channel.send(
            embed=archive_embed,
            view=ApprovedTicketArchiveView() if archive_kind == ARCHIVE_KIND_APPROVED else None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"发送工单归档记录失败: ticket={ticket_id} error={error!r}")
        if interaction:
            await interaction.followup.send("❌ 归档记录发送失败，原工单已保留。", ephemeral=True)
        return False

    # 2. 如果是超时，私信通知用户
    member = None
    if creator_id:
        try:
            member = channel.guild.get_member(int(creator_id))
        except (TypeError, ValueError):
            member = None
    if notify_user and archive_kind == ARCHIVE_KIND_TIMEOUT and creator_id:
        try:
            user = await bot.fetch_user(int(creator_id))
            await user.send(f"工单 `{ticket_id}` 已超时关闭。\n备注: {note}\n欢迎重新申请~")
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            pass
    elif notify_user and archive_kind == ARCHIVE_KIND_APPROVED and member:
        await send_approved_archive_dm(member, channel.guild, ticket_id, automatic=automatic)

    # 3. 归档消息成功后直接清理原工单，不再移动到待手动清理分类。
    try:
        if interaction:
            await interaction.followup.send(f"✅ 工单 `{ticket_id}` 已记录并自动归档。", ephemeral=True)
        await channel.delete(reason=f"工单自动归档：{note}")
        return True
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"删除已归档工单失败: ticket={ticket_id} error={error!r}")
        try:
            if interaction:
                await interaction.followup.send("⚠️ 归档记录已保存，但原工单删除失败，请检查权限。", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass
        return False
