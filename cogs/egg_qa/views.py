import random

import discord

from .storage import (
    DAILY_REPLY_REWARD_CAP,
    DAILY_QUESTION_LIMIT,
    cancel_question,
    create_question,
    finalize_question,
    get_daily_usage,
)


EMBED_COLORS = [
    0xF4B7C7,
    0xF7C873,
    0x8FD5C7,
    0x79B8F3,
    0xA99BEF,
    0xE89AC7,
    0x74C7A5,
]


class EggQuestionModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="🙋‍♀️ 发起小蛋问答")
        self.question_input = discord.ui.InputText(
            label="你想问大家什么？",
            placeholder="把问题写清楚，更容易收到有趣的回答哦～",
            style=discord.InputTextStyle.paragraph,
            min_length=2,
            max_length=1000,
            required=True,
        )
        self.add_item(self.question_input)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild_id or not interaction.channel:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器频道中使用。", ephemeral=True)

        question = str(self.question_input.value or "").strip()
        if len(question) < 2:
            return await interaction.response.send_message("问题至少需要 2 个字符。", ephemeral=True)

        record = create_question(
            author_id=interaction.user.id,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel.id,
            content=question,
        )
        if not record:
            return await interaction.response.send_message(
                f"🥚 你今天已经发起了 **{DAILY_QUESTION_LIMIT} 次**问答，明天再来吧！",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="💬 小蛋提问时间",
            description=f"## {question}",
            color=random.choice(EMBED_COLORS),
        )
        embed.set_author(
            name=f"由 {interaction.user.display_name} 发起",
            icon_url=interaction.user.display_avatar.url,
        )
        embed.add_field(
            name="🥚 回答有礼",
            value=(
                "使用 Discord 的 **回复** 功能回答这条问题，就有机会获得 **3～15 蛋壳**。"
                "奖励越高越稀有！\n提问者自己补充回答时，可获得 **1～3 蛋壳**。"
            ),
            inline=False,
        )
        embed.set_footer(text="每位小蛋对本题限领一次 · 认真回答会更可爱")

        try:
            message = await interaction.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            cancel_question(record["id"])
            return await interaction.followup.send("❌ 问题发送失败，请检查机器人在该频道的权限。", ephemeral=True)

        finalize_question(record["id"], message.id)
        used = get_daily_usage(interaction.user.id, interaction.guild_id)
        await interaction.followup.send(
            f"✅ 问题已发出！你今天还可以发起 **{max(0, DAILY_QUESTION_LIMIT - used)} 次**。",
            ephemeral=True,
        )


class EggQAPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="发起问答",
        style=discord.ButtonStyle.primary,
        emoji="🙋‍♀️",
        custom_id="egg_qa_start",
    )
    async def start_question(self, button, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)
        used = get_daily_usage(interaction.user.id, interaction.guild_id)
        if used >= DAILY_QUESTION_LIMIT:
            return await interaction.response.send_message(
                f"🥚 你今天已经发起了 **{DAILY_QUESTION_LIMIT} 次**问答，明天再来吧！",
                ephemeral=True,
            )
        await interaction.response.send_modal(EggQuestionModal())


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🥚 小蛋问答站",
        description=(
            "有想听听大家意见的问题？按下按钮，把话筒递给整个社区吧！\n\n"
            "### 📖 使用说明\n"
            "**发起问题**　点击下方 **🙋‍♀️ 发起问答**，填写问题后公开发布。\n"
            "**参与回答**　对问题卡片使用 Discord 自带的 **回复** 功能。\n"
            "**领取彩蛋**　首次有效回答可随机获得 **3～15 蛋壳**，大奖更稀有。\n\n"
            "**自问自答**　提问者自己回复问题时，可随机获得 **1～3 蛋壳**。\n\n"
            f"> 每位用户每天最多发起 **{DAILY_QUESTION_LIMIT} 次**；每题每人只可领取一次奖励；"
            f"每天回答奖励最多 **{DAILY_REPLY_REWARD_CAP} 蛋壳**。"
        ),
        color=0xF3B83F,
    )
    embed.add_field(name="💡 小提示", value="问题写得具体一点，大家会更容易接住你的脑电波。", inline=False)
    embed.set_footer(text="小蛋问答 · 分享好奇，也分享蛋壳")
    return embed


async def deploy_egg_qa_panel(channel) -> discord.Message:
    """在指定频道发布小蛋问答入口面板。"""
    return await channel.send(embed=build_panel_embed(), view=EggQAPanelView())
