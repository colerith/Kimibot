import random

import discord

from .storage import (
    DAILY_REPLY_REWARD_CAP,
    DAILY_QUESTION_LIMIT,
    cancel_question,
    create_question,
    finalize_question,
    get_daily_usage,
    get_panel,
    save_panel,
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
        cog = interaction.client.get_cog("小蛋问答")
        if cog and interaction.channel.id == cog._bottom_channel_id():
            cog._schedule_bottom_refresh()
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


class EggQAEntryView(discord.ui.View):
    """固定频道中的轻量入口；完整面板仅对点击者可见。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="打开提问面板",
        style=discord.ButtonStyle.primary,
        emoji="🙋‍♀️",
        custom_id="egg_qa_entry_open",
    )
    async def open_panel(self, button, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=build_panel_embed(),
            view=EggQAPanelView(),
            ephemeral=True,
        )


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


def build_entry_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🙋‍♀️ 小蛋问答入口",
        description="有问题想问大家？点击下方按钮打开提问面板。",
        color=0xF3B83F,
    )
    embed.set_footer(text="完整面板仅你自己可见 · 本入口会自动保持在频道底部")
    return embed


def _is_egg_qa_panel_message(message: discord.Message) -> bool:
    if not message.embeds:
        return False
    return message.embeds[0].title in {"🙋‍♀️ 小蛋问答入口", "🥚 小蛋问答站"}


async def deploy_egg_qa_panel(channel) -> discord.Message:
    """发送或原地更新指定频道的轻量问答入口，并清理重复入口。"""
    panel = get_panel(channel.id)
    target = None
    if panel and panel.get("message_id"):
        try:
            target = await channel.fetch_message(int(panel["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    duplicates = []
    try:
        async for old_message in channel.history(limit=200):
            if not _is_egg_qa_panel_message(old_message):
                continue
            if target is None:
                target = old_message
            elif old_message.id != target.id:
                duplicates.append(old_message)
    except (AttributeError, discord.Forbidden, discord.HTTPException):
        pass

    for duplicate in duplicates:
        try:
            await duplicate.delete(reason="清理重复小蛋问答入口")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    if target is None:
        target = await channel.send(embed=build_entry_embed(), view=EggQAEntryView())
    else:
        await target.edit(embed=build_entry_embed(), view=EggQAEntryView())
    save_panel(channel.id, target.id)
    return target


async def refresh_bottom_egg_qa_panel(channel) -> discord.Message:
    """清理所有旧入口后只重发一个，确保入口位于频道底部。"""
    old_messages = []
    try:
        async for message in channel.history(limit=200):
            if _is_egg_qa_panel_message(message):
                old_messages.append(message)
    except (AttributeError, discord.Forbidden, discord.HTTPException):
        panel = get_panel(channel.id)
        if panel and panel.get("message_id"):
            try:
                old_messages.append(await channel.fetch_message(int(panel["message_id"])))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    for message in old_messages:
        try:
            await message.delete(reason="刷新置底小蛋问答入口")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    message = await channel.send(embed=build_entry_embed(), view=EggQAEntryView())
    save_panel(channel.id, message.id)
    return message
