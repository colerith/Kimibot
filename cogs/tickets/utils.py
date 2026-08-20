import discord
from discord.ext import commands
import json
import os
import datetime

# 相对导入可能在Cog加载时会有问题，建议从项目根目录绝对导入配置
from config import IDS, QUOTA, STYLE
from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace

# --- 常量 ---
SPECIFIC_REVIEWER_ID = 1452321798308888776
TIMEOUT_HOURS_ARCHIVE = 6
TIMEOUT_HOURS_REMIND = 3
STRINGS_PATH = os.path.join(os.path.dirname(__file__), 'strings.json')
QQ_GROUP_QR_URL = "https://discord.com/channels/1397629012292931726/1520276633498419220"


def build_approved_archive_dm(member, guild, ticket_id, *, automatic=False):
    """Build the DM sent after an approved audit ticket is archived."""
    archive_note = (
        "由于等待确认超时，系统已经自动完成归档。"
        if automatic
        else "你已完成最后确认，审核工单现已安全归档。"
    )
    embed = discord.Embed(
        title="📦 人工审核工单已归档",
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

        if ctx.author.id == SPECIFIC_REVIEWER_ID:
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
async def execute_archive(bot, interaction, channel, note, is_timeout=True, log_title_override=None):
    """
    执行归档操作的核心逻辑
    """
    info = get_ticket_info(channel)
    ticket_id = info.get("工单ID", "未知")
    creator_id = info.get("创建者ID")
    creator_name = info.get("创建者", "未知用户")
    operator = interaction.user.mention if interaction else "系统自动"

    # 1. 记录日志
    log_channel = bot.get_channel(IDS.get("TICKET_LOG_CHANNEL_ID") or 1419652525249794128)
    if log_channel:
        log_text = STRINGS["messages"]["log_timeout"].format(
            ticket_id=ticket_id, creator_name=creator_name, creator_id=creator_id,
            operator=operator, note=note
        )
        if log_title_override:
            log_text = log_text.replace("超时归档", log_title_override)
        elif not is_timeout: # 手动归档
            log_text = log_text.replace("超时归档", "手动归档")
        await log_channel.send(log_text)

    # 2. 如果是超时，私信通知用户
    if is_timeout and creator_id:
        try:
            user = await bot.fetch_user(int(creator_id))
            await user.send(f"工单 `{ticket_id}` 已超时关闭。\n备注: {note}\n欢迎重新申请~")
        except: pass

    # 3. 移动频道或删除

    archive_cat = channel.guild.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
    if archive_cat:
        new_name = f"超时归档-{ticket_id}-{creator_name}" if is_timeout else f"归档-{ticket_id}-{creator_name}"
        overwrites = {channel.guild.default_role: discord.PermissionOverwrite(read_messages=False)}
        # 保留管理员权限
        spec_user = channel.guild.get_member(SPECIFIC_REVIEWER_ID)
        if spec_user: overwrites[spec_user] = discord.PermissionOverwrite(read_messages=True)

        try:
            await channel.edit(name=new_name, category=archive_cat, overwrites=overwrites, reason=note)
            await channel.send(f"🚫 **已归档**\n原因: {note}")
            if interaction:
                await interaction.response.send_message(f"✅ 已归档频道: {ticket_id}", ephemeral=True)
        except Exception as e:
            if interaction: await interaction.followup.send(f"归档出错: {e}", ephemeral=True)
    else:
        # 如果找不到归档分类，只能删除
        await channel.delete(reason=note)
