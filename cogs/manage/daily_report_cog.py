import asyncio
import datetime

import discord
from discord.ext import commands, tasks

from config import IDS, TZ_CN
from cogs.points.storage import load_points_data
from .daily_report_storage import (
    get_day_stats,
    get_missing_report_dates,
    initialize_and_reconcile,
    mark_report_sent,
    record_member_join,
    record_member_leave,
    record_role_update,
)


REPORT_GUILD_ID = 1397629012292931726
REPORT_CHANNEL_ID = 1419582550766125138


def _date_cn(moment: datetime.datetime | None = None) -> datetime.date:
    moment = moment or discord.utils.utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(TZ_CN).date()


def _role_ids(member: discord.Member) -> set[int]:
    return {role.id for role in getattr(member, "roles", [])}


def load_daily_activity_stats(guild_id: int, report_date: str) -> dict:
    """Read durable daily activity counters from the points ledger."""
    data = load_points_data()
    signin_rows = data.get("daily_signins", {}).get(f"{guild_id}:{report_date}", [])
    signin_users = {str(user_id) for user_id in signin_rows if str(user_id).isdigit()}

    forum_users = set()
    forum_threads = set()
    for key, rows in data.get("daily_forum_rewards", {}).items():
        parts = str(key).split(":")
        if not parts or parts[-1] != report_date or not isinstance(rows, list):
            continue
        key_guild_id = parts[1] if parts[0] == "user" and len(parts) >= 4 else parts[0]
        if key_guild_id != str(guild_id):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            user_id = str(row.get("user_id", ""))
            thread_id = str(row.get("thread_id", ""))
            if user_id:
                forum_users.add(user_id)
            if thread_id:
                forum_threads.add(thread_id)

    praise_rows = data.get("daily_praise_rewards", {}).get(f"{guild_id}:{report_date}", {})
    praise_users = {
        str(key).split(":", 1)[0]
        for key, row in (praise_rows.items() if isinstance(praise_rows, dict) else [])
        if isinstance(row, dict)
    }
    return {
        "signin_users": len(signin_users),
        "forum_users": len(forum_users),
        "forum_posts": len(forum_threads),
        "praise_users": len(praise_users),
    }


def build_daily_report_embed(
    guild: discord.Guild,
    report_date: str,
    stats: dict,
    activity: dict,
    *,
    is_catchup: bool,
) -> discord.Embed:
    day = datetime.date.fromisoformat(report_date)
    joins = len(stats.get("joins", []))
    leaves = len(stats.get("leaves", []))
    newbie_gains = len(stats.get("newbie_gains", []))
    hatched_gains = len(stats.get("hatched_gains", []))
    net_growth = joins - leaves

    members = list(guild.members)
    humans = [member for member in members if not member.bot]
    bots = len(members) - len(humans)
    newbie_role_id = int(IDS.get("VERIFICATION_ROLE_ID", 0) or 0)
    hatched_role_id = int(IDS.get("HATCHED_ROLE_ID", 0) or 0)
    current_newbies = sum(newbie_role_id in _role_ids(member) for member in humans)
    current_hatched = sum(hatched_role_id in _role_ids(member) for member in humans)

    color = 0x73C991 if net_growth > 0 else 0xF1C75B if net_growth == 0 else 0xD98282
    report_label = "自动补发" if is_catchup else "准时结算"
    embed = discord.Embed(
        title=f"📊 服务器日报 · {day.year}年{day.month}月{day.day}日",
        description=(
            f"统计时段：`{report_date} 00:00 - 23:59`（北京时间）\n"
            f"发布状态：**{report_label}**"
        ),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="🌱 成员变化",
        value=(
            f"📥 新加入：**{joins}** 人\n"
            f"📤 离开：**{leaves}** 人\n"
            f"📈 净增长：**{net_growth:+d}** 人"
        ),
        inline=True,
    )
    embed.add_field(
        name="🐣 身份成长",
        value=(
            f"新兵蛋子新增：**{newbie_gains}** 人\n"
            f"破壳而出新增：**{hatched_gains}** 人\n"
            f"今日完成成长：**{newbie_gains + hatched_gains}** 人次"
        ),
        inline=True,
    )
    embed.add_field(
        name="🏡 当前服务器概况",
        value=(
            f"总成员：**{len(members)}**\n"
            f"真人成员：**{len(humans)}**　机器人：**{bots}**\n"
            f"新兵蛋子：**{current_newbies}**　破壳而出：**{current_hatched}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="🥚 社区活跃",
        value=(
            f"小蛋报到：**{activity.get('signin_users', 0)}** 人\n"
            f"社区发帖：**{activity.get('forum_posts', 0)}** 帖 / **{activity.get('forum_users', 0)}** 人\n"
            f"赞美奇米蛋：**{activity.get('praise_users', 0)}** 人"
        ),
        inline=False,
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text="服务器日报 · 每日北京时间 00:00 结算 · 漏发将自动补齐")
    return embed


class ServerDailyReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._started = False
        self._send_lock = asyncio.Lock()

    def cog_unload(self):
        self.daily_midnight_report.cancel()
        self.repair_missing_reports.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        guild = self.bot.get_guild(REPORT_GUILD_ID)
        if not guild:
            print(f"[服务器日报] 找不到目标服务器: guild={REPORT_GUILD_ID}")
            return

        if not getattr(guild, "chunked", True):
            try:
                await guild.chunk(cache=True)
            except (discord.HTTPException, discord.ClientException) as error:
                print(f"[服务器日报] 成员缓存补全失败，将使用现有缓存: error={error!r}")

        try:
            await self._reconcile_guild(guild)
        except Exception as error:
            print(f"[服务器日报] 启动数据校准失败，将由修复任务重试: error={error!r}")

        # Start repair loops even when one startup reconciliation/send fails.
        if not self._started:
            self._started = True
            self.daily_midnight_report.start()
            self.repair_missing_reports.start()
        try:
            await self._send_missing_reports()
        except Exception as error:
            print(f"[服务器日报] 启动补发失败，将由每小时修复任务重试: error={error!r}")

    async def _reconcile_guild(self, guild: discord.Guild) -> None:
        today = _date_cn()
        joined_members = []
        newbie_ids = []
        hatched_ids = []
        newbie_role_id = int(IDS.get("VERIFICATION_ROLE_ID", 0) or 0)
        hatched_role_id = int(IDS.get("HATCHED_ROLE_ID", 0) or 0)

        for member in guild.members:
            if member.bot:
                continue
            if member.joined_at:
                joined_members.append((member.id, _date_cn(member.joined_at).isoformat()))
            roles = _role_ids(member)
            if newbie_role_id in roles:
                newbie_ids.append(member.id)
            if hatched_role_id in roles:
                hatched_ids.append(member.id)

        await asyncio.to_thread(
            initialize_and_reconcile,
            guild.id,
            today=today.isoformat(),
            captured_at=datetime.datetime.now(TZ_CN).isoformat(timespec="seconds"),
            joined_members=joined_members,
            newbie_ids=newbie_ids,
            hatched_ids=hatched_ids,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or member.guild.id != REPORT_GUILD_ID:
            return
        joined_date = _date_cn(member.joined_at) if member.joined_at else _date_cn()
        await asyncio.to_thread(record_member_join, member.guild.id, member.id, joined_date.isoformat())

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot or member.guild.id != REPORT_GUILD_ID:
            return
        await asyncio.to_thread(record_member_leave, member.guild.id, member.id, _date_cn().isoformat())

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot or after.guild.id != REPORT_GUILD_ID:
            return
        newbie_role_id = int(IDS.get("VERIFICATION_ROLE_ID", 0) or 0)
        hatched_role_id = int(IDS.get("HATCHED_ROLE_ID", 0) or 0)
        before_roles = _role_ids(before)
        after_roles = _role_ids(after)
        if before_roles == after_roles:
            return
        await asyncio.to_thread(
            record_role_update,
            after.guild.id,
            after.id,
            _date_cn().isoformat(),
            has_newbie=newbie_role_id in after_roles,
            had_newbie=newbie_role_id in before_roles,
            has_hatched=hatched_role_id in after_roles,
            had_hatched=hatched_role_id in before_roles,
        )

    async def _get_report_channel(self):
        channel = self.bot.get_channel(REPORT_CHANNEL_ID)
        if channel:
            return channel
        try:
            return await self.bot.fetch_channel(REPORT_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
            print(f"[服务器日报] 找不到日报频道: channel={REPORT_CHANNEL_ID} error={error!r}")
            return None

    async def _send_missing_reports(self) -> None:
        async with self._send_lock:
            guild = self.bot.get_guild(REPORT_GUILD_ID)
            channel = await self._get_report_channel()
            if not guild or not channel:
                return
            yesterday = _date_cn() - datetime.timedelta(days=1)
            missing_dates = await asyncio.to_thread(
                get_missing_report_dates,
                guild.id,
                yesterday.isoformat(),
            )
            for report_date in missing_dates:
                stats, activity = await asyncio.gather(
                    asyncio.to_thread(get_day_stats, guild.id, report_date),
                    asyncio.to_thread(load_daily_activity_stats, guild.id, report_date),
                )
                is_catchup = report_date != yesterday.isoformat() or datetime.datetime.now(TZ_CN).time() > datetime.time(0, 5)
                embed = build_daily_report_embed(
                    guild,
                    report_date,
                    stats,
                    activity,
                    is_catchup=is_catchup,
                )
                try:
                    message = await channel.send(
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except (discord.Forbidden, discord.HTTPException) as error:
                    print(f"[服务器日报] 发送失败: date={report_date} error={error!r}")
                    break
                await asyncio.to_thread(
                    mark_report_sent,
                    guild.id,
                    report_date,
                    message.id,
                    datetime.datetime.now(TZ_CN).isoformat(timespec="seconds"),
                )
                print(f"[服务器日报] 已发送: date={report_date} message={message.id}")

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=TZ_CN))
    async def daily_midnight_report(self):
        try:
            await self._send_missing_reports()
        except Exception as error:
            print(f"[服务器日报] 零点结算失败，将稍后重试: error={error!r}")

    @daily_midnight_report.before_loop
    async def before_daily_midnight_report(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def repair_missing_reports(self):
        try:
            await self._send_missing_reports()
        except Exception as error:
            print(f"[服务器日报] 定时补发失败，将在下一轮重试: error={error!r}")

    @repair_missing_reports.before_loop
    async def before_repair_missing_reports(self):
        await self.bot.wait_until_ready()
