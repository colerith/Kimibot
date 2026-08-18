# cogs/welcome/views.py

import discord
import asyncio
import random
from discord.ext import commands

from config import IDS, STYLE
from cogs.shared.utils import get_account_wait_status, has_verification_role
from .data import QUIZ_QUESTIONS

# --- 配置区 ---
QUIZ_DURATION = 120
MIN_ACCOUNT_AGE_DAYS = 30

class QuizStartView(discord.ui.View):
    # ✨ 修改点：初始化时接收 cog 实例
    def __init__(self, cog: commands.Cog):
        super().__init__(timeout=None)
        self.cog = cog 

    async def _collect_risk_reasons(self, interaction: discord.Interaction):
        """仅校验账号注册时长和可疑账号标记。"""
        reasons = []

        # This reads the same points JSON used by a sign-in burst. Waiting for
        # its threading lock on the event loop would freeze every quiz answer.
        wait_status = await asyncio.to_thread(
            get_account_wait_status,
            interaction.user,
            interaction.guild_id,
        )
        if not wait_status["eligible"]:
            reasons.append(
                f"账号还需等待 {wait_status['remaining_wait_days']} 天"
                f"（账号已注册 {wait_status['account_age_days']} 天，"
                f"当前要求 {wait_status['required_wait_days']} 天，"
                f"已加速 {wait_status['acceleration_days']} 天）"
            )

        public_flags = getattr(interaction.user, "public_flags", None)
        is_suspected_spammer = bool(getattr(public_flags, "spammer", False)) if public_flags else False
        if is_suspected_spammer:
            reasons.append("账号被系统标记为可疑/疑似垃圾账号")

        return reasons

    @discord.ui.button(label="📝 点击开始答题", style=discord.ButtonStyle.success, custom_id="quiz_entry_start")
    async def start_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        user_id = interaction.user.id

        if has_verification_role(interaction.user):
            return await interaction.followup.send("你已经是新兵蛋子或正式成员啦，不需要再答题咯！", ephemeral=True)

        risk_reasons = await self._collect_risk_reasons(interaction)
        if risk_reasons:
            reason_text = "\n".join(f"• {reason}" for reason in risk_reasons)
            return await interaction.followup.send(
                f"⚠️ 当前账号暂不满足自助答题条件：\n{reason_text}",
                ephemeral=True,
            )

        if user_id in self.cog.sessions:
            session = self.cog.sessions[user_id]
            elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()
            if elapsed < QUIZ_DURATION:
                remaining = int(QUIZ_DURATION - elapsed)
                q_index = len(session["answers"])
                if q_index >= len(session["questions"]): q_index = len(session["questions"]) - 1
                question = session["questions"][q_index]
                view = QuizQuestionView(self.cog, user_id, q_index)
                embed = view.build_embed(q_index, question, remaining)
                await interaction.followup.send(
                    content="⚠️ **检测到你有未完成的答题，已为你恢复进度：**",
                    embed=embed, view=view, ephemeral=True
                )
                return
            else:
                del self.cog.sessions[user_id]

        can_start, wait_time = self.cog.check_cooldown(user_id)
        if not can_start:
            await interaction.followup.send(f"⏳ 答题冷却中！\n请休息一下，再过 **{wait_time // 60}分{wait_time % 60}秒** 才能再次尝试哦。", ephemeral=True)
            return

        questions = random.sample(QUIZ_QUESTIONS, 10)
        self.cog.sessions[user_id] = {
            "questions": questions,
            "answers": {},
            "start_time": discord.utils.utcnow(),
            "channel_id": interaction.channel_id
        }

        view = QuizQuestionView(self.cog, user_id, 0)
        embed = view.build_embed(0, questions[0], 120)
        try:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception:
            self.cog.sessions.pop(user_id, None)
            raise

        # Start the two-minute clock only after Discord has actually accepted
        # the first question; time spent queued behind a busy API no longer
        # consumes the user's answering time.
        session = self.cog.sessions.get(user_id)
        if session:
            session["start_time"] = discord.utils.utcnow()
            asyncio.create_task(self.cog.timer_task(interaction, user_id))

class QuizQuestionView(discord.ui.View):
    # ✨ 修改点：初始化时接收 cog 实例
    def __init__(self, cog: commands.Cog, user_id: int, q_index: int):
        super().__init__(timeout=QUIZ_DURATION)
        self.cog = cog # 保存 cog 实例
        self.user_id = user_id
        self.q_index = q_index

        # ✨ 修改点：通过 self.cog 访问
        session = self.cog.sessions.get(user_id)
        if session and q_index < len(session["questions"]):
            question = session["questions"][q_index]
            options = [
                discord.SelectOption(
                    label=f"选项 {key}",
                    description=(val[:48] + "...") if len(val) > 48 else val,
                    value=key,
                    emoji="👉"
                ) for key, val in question["options"].items()
            ]
            select = discord.ui.Select(
                placeholder="请选择你的答案 (完整内容见上方)",
                options=options,
                custom_id=f"quiz_select_{q_index}_{user_id}"
            )
            select.callback = self.select_callback
            self.add_item(select)

    def build_embed(self, index, question, remaining_time):
        desc = f"### **{question['question']}**\n\n"
        for key, val in question["options"].items():
            desc += f"> **{key}.** {val}\n"
        embed = discord.Embed(title=f"📝 第 {index + 1}/10 题", description=desc, color=STYLE["KIMI_YELLOW"])
        embed.set_footer(text=f"⏱️ 剩余时间: {remaining_time}秒 (总共2分钟)")
        return embed

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("这不是你的考卷！", ephemeral=True)

        # Discord 要求组件交互在约 3 秒内完成首次确认。先确认交互，避免
        # 事件循环短暂繁忙时，后面的 edit_message 收到 10062。
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return

        session = self.cog.sessions.get(self.user_id)
        if not session:
             await interaction.edit_original_response(content="❌ 会话已超时或已结束，请重新开始。", view=None, embed=None)
             return

        session["answers"][self.q_index] = interaction.data['values'][0]

        next_index = self.q_index + 1
        if next_index < len(session["questions"]):
            next_q = session["questions"][next_index]
            elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()
            remaining = max(0, QUIZ_DURATION - int(elapsed))

            view = QuizQuestionView(self.cog, self.user_id, next_index)
            embed = view.build_embed(next_index, next_q, remaining)

            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await self.cog.finalize_quiz(interaction, self.user_id, is_timeout=False)
