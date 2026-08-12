import re
import random

import discord
from discord import Option
from discord.ext import commands

import config
from cogs.points.storage import format_shells, modify_user_points
from cogs.shared.utils import is_super_egg

from .storage import (
    DIGIT_EMOJI_IDS,
    format_digit_emojis,
    load_boost_thanks_data,
    mark_processed,
    pick_thanks_message,
    update_processed_message,
)

BOOST_MESSAGE_TYPE_NAMES = {
    "premium_guild_subscription",
    "premium_guild_tier_1",
    "premium_guild_tier_2",
    "premium_guild_tier_3",
}

CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

BOOST_THANKS_TITLE = "🥚 小蛋收到助力啦"
BOOST_EMBED_COLORS = [
    0xF4B7C7,
    0xF7C873,
    0x8FD5C7,
    0x79B8F3,
    0xA99BEF,
    0xE89AC7,
    0x74C7A5,
]


def _message_type_name(message: discord.Message) -> str:
    msg_type = getattr(message, "type", None)
    return str(getattr(msg_type, "name", msg_type or ""))


def _extract_boost_count(message: discord.Message) -> int:
    content = message.content or ""
    number_match = re.search(r"(\d+)", content)
    if number_match:
        return max(1, int(number_match.group(1)))

    for char, value in CHINESE_DIGITS.items():
        if char in content and value > 0:
            return value

    return 1


def _safe_display_name(user) -> str:
    name = getattr(user, "display_name", None) or getattr(user, "name", None) or "未知成员"
    return discord.utils.escape_markdown(str(name))


def _user_profile_link(user_id: int, display_name: str) -> str:
    safe_name = discord.utils.escape_markdown(str(display_name or "未知成员"))
    if not user_id:
        return f"@{safe_name}"
    return f"[@{safe_name}](https://discord.com/users/{user_id})"


def _build_boost_embed(member: discord.Member, boost_count: int, guild: discord.Guild, thanks_text: str, bot=None) -> discord.Embed:
    tier = int(getattr(guild, "premium_tier", 0) or 0)
    total_boosts = int(getattr(guild, "premium_subscription_count", 0) or 0)
    boost_digits = format_digit_emojis(boost_count, bot=bot)

    embed = discord.Embed(
        title=BOOST_THANKS_TITLE,
        description=(
            f"{_user_profile_link(member.id, member.display_name)}\n\n"
            f"{thanks_text}\n\n"
            f"本次助力：{boost_digits}\n"
            f"当前服务器等级：**Level {tier}**\n"
            f"当前服务器助力数：**{total_boosts}**"
        ),
        color=random.choice(BOOST_EMBED_COLORS),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="奇米蛋感谢你的助力。")
    return embed


def _extract_boost_count_from_embed(embed: discord.Embed) -> int | None:
    description = embed.description or ""
    line_match = re.search(r"本次助力[：:]\s*(.+)", description)
    if not line_match:
        return None

    raw = line_match.group(1).strip()
    custom_ids = re.findall(r"<a?:[^:>]+:(\d+)>", raw)
    if custom_ids:
        id_to_digit = {
            str(emoji_id): digit
            for digit, emoji_id in DIGIT_EMOJI_IDS.items()
        }
        digits = "".join(id_to_digit.get(emoji_id, "") for emoji_id in custom_ids)
        if digits:
            return int(digits)

    named_digits = re.findall(r":(?:kimi|num_?)(\d):", raw)
    if named_digits:
        return int("".join(named_digits))

    number_match = re.search(r"(\d+)", raw)
    if number_match:
        return int(number_match.group(1))

    return None


def _refresh_boost_embed(
    embed: discord.Embed,
    boost_count: int,
    *,
    user_id: int,
    display_name: str,
    color: int,
    avatar_url: str | None = None,
    bot=None,
) -> discord.Embed:
    description = embed.description or ""
    refreshed_description = re.sub(
        r"本次助力[：:].*",
        f"本次助力：{format_digit_emojis(boost_count, bot=bot)}",
        description,
        count=1,
    )
    refreshed = discord.Embed.from_dict(embed.to_dict())
    refreshed.description = refreshed_description
    lines = refreshed.description.splitlines()
    if lines:
        lines[0] = _user_profile_link(user_id, display_name)
        refreshed.description = "\n".join(lines)
    refreshed.color = discord.Color(color)
    if avatar_url:
        refreshed.set_thumbnail(url=avatar_url)
    return refreshed


class BoostThanksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._auto_refreshed = False

    @commands.Cog.listener()
    async def on_ready(self):
        print("[BoostThanks] Cog loaded.")
        if self._auto_refreshed:
            return
        self._auto_refreshed = True
        for guild in self.bot.guilds:
            channel = await self._get_configured_target_channel(guild)
            if channel:
                updated, scanned, skipped = await self._refresh_channel_boost_embeds(channel, limit=None)
                if updated:
                    print(f"[BoostThanks] auto-refreshed {updated}/{scanned} boost thanks embeds in {guild.id}, skipped={skipped}.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        type_name = _message_type_name(message)
        if type_name not in BOOST_MESSAGE_TYPE_NAMES:
            return

        boost_count = _extract_boost_count(message)
        payload = {
            "guild_id": str(message.guild.id),
            "user_id": str(message.author.id),
            "boost_count": boost_count,
            "message_type": type_name,
        }
        if not mark_processed(message.id, payload):
            return

        reward_per_boost = float(getattr(config, "BOOST_REWARD_AMOUNT", 10.0))
        reward = reward_per_boost * boost_count
        balance = modify_user_points(
            message.author.id,
            reward,
            message.guild.id,
            source="server_boost",
            reason=f"message={message.id};count={boost_count}",
        )

        thanks_text = pick_thanks_message()
        embed = _build_boost_embed(message.author, boost_count, message.guild, thanks_text, bot=self.bot)
        embed.add_field(
            name="蛋壳感谢",
            value=f"+**{format_shells(reward)}** 蛋壳\n当前余额：**{format_shells(balance)}** 蛋壳",
            inline=False,
        )

        target_channel = self._get_target_channel(message)
        sent = await target_channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        update_processed_message(
            message.id,
            {
                "thanks_channel_id": str(target_channel.id),
                "thanks_message_id": str(sent.id),
                "thanks_text": thanks_text,
                "reward": reward,
                "balance": balance,
            },
        )

    def _get_target_channel(self, message: discord.Message):
        channel_id = getattr(config, "BOOST_THANKS_CHANNEL_ID", None)
        if channel_id:
            channel = message.guild.get_channel(int(channel_id))
            if channel:
                return channel
        return message.channel

    async def _get_configured_target_channel(self, guild: discord.Guild):
        channel_id = getattr(config, "BOOST_THANKS_CHANNEL_ID", None)
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        if channel:
            return channel
        try:
            return await guild.fetch_channel(int(channel_id))
        except discord.HTTPException:
            return None

    async def _resolve_boost_user(self, guild: discord.Guild, user_id: int):
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        if member is not None:
            return member
        try:
            return await self.bot.fetch_user(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _refresh_channel_boost_embeds(self, channel, *, limit: int | None) -> tuple[int, int, int]:
        scanned = 0
        updated = 0
        skipped = 0
        processed = load_boost_thanks_data().get("processed", {})
        records_by_thanks_message = {
            str(record.get("thanks_message_id")): record
            for record in processed.values()
            if isinstance(record, dict) and record.get("thanks_message_id")
        }
        async for message in channel.history(limit=limit):
            scanned += 1
            if message.author.id != self.bot.user.id or not message.embeds:
                continue
            embed = message.embeds[0]
            if embed.title != BOOST_THANKS_TITLE:
                continue
            boost_count = _extract_boost_count_from_embed(embed)
            if boost_count is None:
                skipped += 1
                continue

            record = records_by_thanks_message.get(str(message.id), {})
            user_id = int(record.get("user_id") or 0)
            if not user_id:
                old_mention = re.search(r"<@!?(\d+)>", embed.description or "")
                user_id = int(old_mention.group(1)) if old_mention else 0
            user = await self._resolve_boost_user(channel.guild, user_id) if user_id else None
            display_name = (
                getattr(user, "display_name", None) or getattr(user, "name", None) or "未知成员"
                if user else "未知成员"
            )
            avatar_url = str(user.display_avatar.url) if user and getattr(user, "display_avatar", None) else None
            color = random.Random(message.id).choice(BOOST_EMBED_COLORS)
            refreshed = _refresh_boost_embed(
                embed,
                boost_count,
                user_id=user_id,
                display_name=display_name,
                color=color,
                avatar_url=avatar_url,
                bot=self.bot,
            )
            try:
                await message.edit(embed=refreshed, allowed_mentions=discord.AllowedMentions.none())
                updated += 1
            except discord.HTTPException:
                skipped += 1
        return updated, scanned, skipped

    @discord.slash_command(name="刷新助力鸣谢", description="强制刷新助力鸣谢面板的数字表情显示")
    @is_super_egg()
    async def refresh_boost_thanks(
        self,
        ctx: discord.ApplicationContext,
        扫描数量: Option(int, "扫描最近多少条消息，0 表示尽量扫描全部", required=False, default=1000),  # pyright: ignore[reportInvalidTypeForm]
    ):
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            return await ctx.followup.send("❌ 该命令只能在服务器内使用。", ephemeral=True)

        channel = await self._get_configured_target_channel(ctx.guild) or ctx.channel
        if channel is None:
            return await ctx.followup.send("❌ 找不到助力鸣谢频道。", ephemeral=True)

        limit = None if int(扫描数量 or 0) <= 0 else max(1, int(扫描数量))
        updated, scanned, skipped = await self._refresh_channel_boost_embeds(channel, limit=limit)

        await ctx.followup.send(
            f"✅ 已刷新助力鸣谢面板。\n扫描：**{scanned}** 条\n更新：**{updated}** 条\n跳过：**{skipped}** 条",
            ephemeral=True,
        )

    @discord.slash_command(name="检查助力表情", description="检查 bot 是否能定位助力数字表情 ID")
    @is_super_egg()
    async def check_boost_digit_emojis(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        lines = []
        missing = []
        for digit in "1234567890":
            emoji_id = DIGIT_EMOJI_IDS[digit]
            emoji = self.bot.get_emoji(int(emoji_id))
            if emoji is None:
                missing.append(digit)
                lines.append(f"⚠️ `{digit}` `{emoji_id}`：bot emoji cache 找不到")
            else:
                guild_name = getattr(getattr(emoji, "guild", None), "name", "未知服务器")
                lines.append(f"✅ `{digit}` `{emoji_id}`：{emoji} · `{emoji.name}` · {guild_name}")

        tip = ""
        if missing:
            tip = (
                "\n\n如果这里显示找不到，说明 bot 没有加入这些表情所在的服务器，"
                "或启动时没有加载到该服务器的 emoji。仅开放“使用外部表情”权限还不够。"
            )

        await ctx.followup.send("\n".join(lines)[:1800] + tip, ephemeral=True)
