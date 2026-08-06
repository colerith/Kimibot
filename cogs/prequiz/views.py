import discord

import config
from config import STYLE
from cogs.points.storage import format_shells, modify_user_points

from .storage import draw_prequiz_questions, get_attempt, load_question_bank, save_attempt


class PreQuizShortAnswerModal(discord.ui.Modal):
    def __init__(self, parent_view: "PreQuizQuestionView"):
        super().__init__(title="预答题简答")
        self.parent_view = parent_view
        self.answer_input = discord.ui.InputText(
            label="简答题答案",
            placeholder="必须和固定答案完全一致",
            required=True,
            max_length=100,
        )
        self.add_item(self.answer_input)

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.finalize(interaction, str(self.answer_input.value or "").strip())


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
            return await interaction.response.send_message("这不是你的预答题面板。", ephemeral=True)
        self.parent_view.answers[self.index] = self.values[0]
        next_index = self.index + 1
        if next_index < len(self.parent_view.questions["multiple_choice"]):
            view = PreQuizQuestionView(
                self.parent_view.user_id,
                self.parent_view.questions,
                next_index,
                self.parent_view.answers,
            )
            await interaction.response.edit_message(embed=view.build_embed(), view=view)
        else:
            await interaction.response.send_modal(PreQuizShortAnswerModal(self.parent_view))


class PreQuizQuestionView(discord.ui.View):
    def __init__(self, user_id: int, questions: dict, index: int = 0, answers: dict[int, str] | None = None):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.questions = questions
        self.index = index
        self.answers = answers or {}
        self.add_item(PreQuizAnswerSelect(self, index, questions["multiple_choice"][index]))

    async def finalize(self, interaction: discord.Interaction, short_answer: str):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)

        if get_attempt(interaction.user.id, interaction.guild_id):
            return await interaction.response.send_message("你已经完成过预答题了，每个用户只能答一次。", ephemeral=True)

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
        if passed:
            balance = modify_user_points(
                interaction.user.id,
                reward,
                interaction.guild_id,
                source="prequiz",
                reason="prequiz_passed",
            )
            reward_granted = True

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
            title="✅ 预答题通过" if passed else "❌ 预答题未通过",
            color=0x00AA66 if passed else 0xCC3333,
        )
        desc = [
            f"客观题：**{correct_count}/5**",
            f"简答题：**{'正确' if short_correct else '错误'}**",
        ]
        if passed:
            desc.append(f"奖励：+**{format_shells(reward)}** 蛋壳")
            desc.append(f"当前余额：**{format_shells(balance)}** 蛋壳")
        else:
            desc.append("预答题每个用户只能提交一次。")
        embed.description = "\n".join(desc)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
        embed.set_footer(text="每个用户只能提交一次。")
        return embed


class PreQuizPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="预备答题", style=discord.ButtonStyle.success, emoji="📝", custom_id="prequiz_start")
    async def start_callback(self, button, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)
        existing = get_attempt(interaction.user.id, interaction.guild_id)
        if existing:
            status = "通过" if existing.get("passed") else "未通过"
            return await interaction.response.send_message(
                f"你已经完成过预答题了，结果：**{status}**。",
                ephemeral=True,
            )

        questions = draw_prequiz_questions()
        if not questions:
            return await interaction.response.send_message("题库数量不足，请联系管理员检查预答题题库。", ephemeral=True)

        view = PreQuizQuestionView(interaction.user.id, questions)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


def build_prequiz_panel_embed() -> discord.Embed:
    bank = load_question_bank()
    embed = discord.Embed(
        title="🥚 小蛋预答题",
        description=(
            "提前完成一次小蛋预答题，通过后固定获得 **5 蛋壳**。\n\n"
            "题型：随机 5 道客观题 + 1 道简答题。\n"
            "简答题必须与固定答案完全一致。\n"
            "每个用户只能提交一次。"
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
