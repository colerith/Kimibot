import discord

import config
from config import STYLE
from cogs.points.storage import format_shells, modify_user_points
from cogs.shared.utils import has_verification_role

from .storage import draw_prequiz_questions, get_prequiz_access, load_question_bank, save_attempt


def _format_cooldown(seconds: int) -> str:
    minutes = seconds // 60
    remain = seconds % 60
    if minutes and remain:
        return f"{minutes}分{remain}秒"
    if minutes:
        return f"{minutes}分钟"
    return f"{remain}秒"


class PreQuizShortAnswerModal(discord.ui.Modal):
    def __init__(self, parent_view: "PreQuizQuestionView"):
        super().__init__(title="预答题简答")
        self.parent_view = parent_view
        short_question = parent_view.questions.get("short_question", {})
        question_text = str(short_question.get("question", "请填写简答题答案")).strip()
        self.answer_input = discord.ui.InputText(
            label=question_text[:45],
            placeholder="必须和固定答案完全一致",
            required=True,
            max_length=100,
        )
        self.add_item(self.answer_input)

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.finalize(interaction, str(self.answer_input.value or "").strip())


class PreQuizShortAnswerView(discord.ui.View):
    """第 5 题完成后的简答入口；Modal 打开失败时用户可以重试。"""

    def __init__(self, parent_view: "PreQuizQuestionView"):
        super().__init__(timeout=600)
        self.parent_view = parent_view

    @discord.ui.button(label="填写简答题", emoji="✍️", style=discord.ButtonStyle.primary)
    async def open_short_answer(self, button, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.user_id:
            try:
                await interaction.response.send_message("这不是你的预答题面板。", ephemeral=True)
            except discord.NotFound:
                pass
            return
        try:
            await interaction.response.send_modal(PreQuizShortAnswerModal(self.parent_view))
        except discord.NotFound:
            # 交互到达 Bot 时已过期；保留按钮供用户再次点击。
            return


class PreQuizAnswerSelect(discord.ui.Select):
    def __init__(self, parent_view: "PreQuizQuestionView", index: int, question: dict):
        self.parent_view = parent_view
        self.index = index
        options = [
            discord.SelectOption(
                label=f"{key}. {str(value)[:80]}",
                value=key,
            )
            for key, value in question["options"].items()
        ]
        super().__init__(
            placeholder=f"第 {index + 1} 题",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id=f"prequiz_select_{index}",
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.user_id:
            try:
                await interaction.response.send_message("这不是你的预答题面板。", ephemeral=True)
            except discord.NotFound:
                pass
            return
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.parent_view.answers[self.index] = self.values[0]
        next_index = self.index + 1
        if next_index < len(self.parent_view.questions["multiple_choice"]):
            view = PreQuizQuestionView(
                self.parent_view.user_id,
                self.parent_view.questions,
                next_index,
                self.parent_view.answers,
                test_mode=self.parent_view.test_mode,
            )
            await interaction.edit_original_response(embed=view.build_embed(), view=view)
        else:
            embed = discord.Embed(
                title="🥚 小蛋预答题 5/5",
                description=(
                    "✅ 5 道客观题已经全部作答。\n\n"
                    "点击下方按钮填写最后一道简答题并提交结果。"
                ),
                color=STYLE["KIMI_YELLOW"],
            )
            embed.set_footer(text="如果简答题窗口没有弹出，可以再次点击按钮。")
            await interaction.edit_original_response(
                embed=embed,
                view=PreQuizShortAnswerView(self.parent_view),
            )


class PreQuizQuestionView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        questions: dict,
        index: int = 0,
        answers: dict[int, str] | None = None,
        *,
        test_mode: bool = False,
    ):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.questions = questions
        self.index = index
        self.answers = answers or {}
        self.test_mode = test_mode
        self.add_item(PreQuizAnswerSelect(self, index, questions["multiple_choice"][index]))

    async def finalize(self, interaction: discord.Interaction, short_answer: str):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        if has_verification_role(interaction.user) and not self.test_mode:
            return await interaction.followup.send(
                "你已经通过验证答题啦，不需要再参加预答题。",
                ephemeral=True,
            )

        if not self.test_mode:
            access = get_prequiz_access(interaction.user.id, interaction.guild_id)
            if not access["allowed"]:
                if access["reason"] == "passed":
                    return await interaction.followup.send(
                        "你已经全对通过预答题并领取过奖励啦，每个用户只能领取一次。",
                        ephemeral=True,
                    )
                if access["reason"] == "cooldown":
                    return await interaction.followup.send(
                        f"上次没有全对，需要等待 **{_format_cooldown(access['remaining_seconds'])}** 后再试。",
                        ephemeral=True,
                    )

        mc_details = []
        correct_count = 0
        for index, question in enumerate(self.questions["multiple_choice"]):
            selected = self.answers.get(index)
            is_correct = selected == question["answer"]
            if is_correct:
                correct_count += 1
            mc_details.append(
                {
                    "id": question["id"],
                    "selected": selected,
                    "answer": question["answer"],
                    "correct": is_correct,
                }
            )

        short_question = self.questions["short_question"]
        short_correct = short_answer == short_question["answer"]
        passed = correct_count == 5 and short_correct
        score = correct_count * 20
        reward = float(getattr(config, "PRE_QUIZ_REWARD", 5.0)) if passed else 0.0
        reward_granted = False
        balance = None
        if passed and not self.test_mode:
            balance = modify_user_points(
                interaction.user.id,
                reward,
                interaction.guild_id,
                source="prequiz",
                reason="prequiz_passed",
            )
            reward_granted = True

        if not self.test_mode:
            save_attempt(
                user_id=interaction.user.id,
                guild_id=interaction.guild_id,
                passed=passed,
                score=score,
                mc_details=mc_details,
                short_question=short_question,
                short_answer=short_answer,
                reward_granted=reward_granted,
            )

        embed = discord.Embed(
            title=("🧪 预答题测试通过" if passed else "🧪 预答题测试未通过") if self.test_mode else ("✅ 预答题通过" if passed else "❌ 预答题未通过"),
            color=0x00AA66 if passed else 0xCC3333,
        )
        desc = [
            f"客观题：**{correct_count}/5**",
            f"简答题：**{'正确' if short_correct else '错误'}**",
        ]
        if passed and not self.test_mode:
            desc.append(f"奖励：+**{format_shells(reward)}** 蛋壳")
            desc.append(f"当前余额：**{format_shells(balance)}** 蛋壳")
        elif self.test_mode:
            desc.append("测试模式：不记录次数，不发放蛋壳。")
            desc.append(f"简答题题干：{short_question['question']}")
            desc.append(f"固定答案：`{short_question['answer']}`")
        else:
            desc.append("没有全对，5 分钟后可以重新答题。")
        embed.description = "\n".join(desc)
        await interaction.followup.send(embed=embed, ephemeral=True)

    def build_embed(self) -> discord.Embed:
        index = self.index
        question = self.questions["multiple_choice"][index]
        lines = []
        lines.append(f"**{index + 1}. {question['question']}**")
        for key, value in question["options"].items():
            lines.append(f"{key}. {value}")
        if index == len(self.questions["multiple_choice"]) - 1:
            lines.append("")
            lines.append("选择本题后会弹出简答题。")
        embed = discord.Embed(
            title=f"🥚 小蛋预答题 {index + 1}/5",
            description="\n".join(lines)[:4000],
            color=STYLE["KIMI_YELLOW"],
        )
        embed.set_footer(text="必须全部答对才可领取奖励；未全对需等待 5 分钟后重试。")
        if self.test_mode:
            embed.set_footer(text="管理员测试模式：不会记录答题次数或发放奖励。")
        return embed


class PreQuizPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="预备答题", style=discord.ButtonStyle.success, emoji="📝", custom_id="prequiz_start")
    async def start_callback(self, button, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        if has_verification_role(interaction.user):
            return await interaction.followup.send(
                "你已经通过验证答题啦，不需要再参加预答题。",
                ephemeral=True,
            )
        access = get_prequiz_access(interaction.user.id, interaction.guild_id)
        if not access["allowed"]:
            if access["reason"] == "passed":
                return await interaction.followup.send(
                    "你已经全对通过预答题并领取过奖励啦，每个用户只能领取一次。",
                    ephemeral=True,
                )
            if access["reason"] == "cooldown":
                remaining_text = _format_cooldown(access["remaining_seconds"])
                attempt = access.get("attempt", {})
                correct = int(attempt.get("score", 0) or 0) // 20
                return await interaction.followup.send(
                    f"上次没有全对（客观题 **{correct}/5**），需要等待 **{remaining_text}** 后再试。",
                    ephemeral=True,
                )

        questions = draw_prequiz_questions()
        if not questions:
            return await interaction.followup.send("题库数量不足，请联系管理员检查预答题题库。", ephemeral=True)

        view = PreQuizQuestionView(interaction.user.id, questions)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)


def build_prequiz_panel_embed() -> discord.Embed:
    bank = load_question_bank()
    embed = discord.Embed(
        title="🥚 小蛋预答题",
        description=(
            "提前完成一次小蛋预答题，通过后固定获得 **5 蛋壳**。\n\n"
            "题型：随机 5 道客观题 + 1 道简答题。\n"
            "简答题必须与固定答案完全一致。\n"
            "必须全部答对才可领取奖励；没有全对时，5 分钟后可以重新答题。"
        ),
        color=STYLE["KIMI_YELLOW"],
    )
    embed.set_footer(text=f"题库：{len(bank['multiple_choice'])} 道客观题 / {len(bank['short_questions'])} 道简答题")
    return embed


async def deploy_prequiz_panel(bot) -> str:
    channel_id = getattr(config, "PRE_QUIZ_CHANNEL_ID", None)
    if not channel_id:
        return "missing_channel_id"
    channel = bot.get_channel(int(channel_id))
    if not channel:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except Exception:
            return "channel_not_found"
    await channel.send(embed=build_prequiz_panel_embed(), view=PreQuizPanelView())
    return "sent"
