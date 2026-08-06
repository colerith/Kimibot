import re

import discord
from discord.ext import commands

import config
from cogs.points.storage import format_shells, modify_user_points

from .storage import format_digit_emojis, mark_processed, pick_thanks_message

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


def _build_boost_embed(member: discord.Member, boost_count: int, guild: discord.Guild, thanks_text: str) -> discord.Embed:
    tier = int(getattr(guild, "premium_tier", 0) or 0)
    total_boosts = int(getattr(guild, "premium_subscription_count", 0) or 0)
    boost_digits = format_digit_emojis(boost_count)

    embed = discord.Embed(
        title="🥚 小蛋收到助力啦",
        description=(
            f"{member.mention}\n\n"
            f"{thanks_text}\n\n"
            f"本次助力：{boost_digits}\n"
            f"当前服务器等级：**Level {tier}**\n"
            f"当前服务器助力数：**{total_boosts}**"
        ),
        color=getattr(config, "KIMI_YELLOW", 0xFFD700),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="奇米蛋感谢你的助力。")
    return embed


class BoostThanksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("[BoostThanks] Cog loaded.")

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
        embed = _build_boost_embed(message.author, boost_count, message.guild, thanks_text)
        embed.add_field(
            name="蛋壳感谢",
            value=f"+**{format_shells(reward)}** 蛋壳\n当前余额：**{format_shells(balance)}** 蛋壳",
            inline=False,
        )

        target_channel = self._get_target_channel(message)
        await target_channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    def _get_target_channel(self, message: discord.Message):
        channel_id = getattr(config, "BOOST_THANKS_CHANNEL_ID", None)
        if channel_id:
            channel = message.guild.get_channel(int(channel_id))
            if channel:
                return channel
        return message.channel
