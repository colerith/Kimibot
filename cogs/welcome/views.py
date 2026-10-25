# cogs/welcome/views.py

import discord
import asyncio
import random
from discord.ext import commands

from config import IDS, STYLE
from cogs.shared.utils import get_account_wait_status, has_verification_role
from .data import QUIZ_QUESTIONS

# --- 配置区 ---
from .quiz_logic import QUIZ_DURATION, draw_questions
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
        test_mode = bool(interaction.guild and (user_id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator))

        if not test_mode and has_verification_role(interaction.user):
            return await interaction.followup.send("你已经是新兵蛋子或正式成员啦，不需要再答题咯！", ephemeral=True)

        risk_reasons = [] if test_mode else await self._collect_risk_reasons(interaction)
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
                await self.cog.finalize_quiz(interaction, user_id, is_timeout=True)
                return

        if not test_mode:
            from .attempts import used_today
            if await asyncio.to_thread(used_today, interaction.guild_id, user_id) >= 3:
                return await interaction.followup.send("今日 3 次答题机会已用完，请等待北京时间次日 00:00 刷新。", ephemeral=True)
        can_start, wait_time = (True, 0) if test_mode else self.cog.check_cooldown(user_id)
        if not can_start:
            await interaction.followup.send(f"⏳ 答题冷却中！\n请休息一下，再过 **{wait_time // 60}分{wait_time % 60}秒** 才能再次尝试哦。", ephemeral=True)
            return

        questions = draw_questions(QUIZ_QUESTIONS)
        quota_token, daily_used = None, 0
        if not test_mode:
            from .attempts import reserve, release
            quota_token, daily_used = await asyncio.to_thread(reserve, interaction.guild_id, user_id)
            if quota_token is None:
                return await interaction.followup.send("今日 3 次答题机会已用完，请等待北京时间次日 00:00 刷新。", ephemeral=True)
            if user_id in self.cog.sessions:
                await asyncio.to_thread(release, quota_token)
                return await interaction.followup.send("你已有正在进行的答题，请重新点击入口恢复。", ephemeral=True)
        self.cog.sessions[user_id] = {
            "questions": questions,
            "test_mode": test_mode,
            "quota_token": quota_token,
            "daily_used": daily_used,
            "answers": {},
            "drafts": {},
            "lock": asyncio.Lock(),
            "start_time": discord.utils.utcnow(),
            "channel_id": interaction.channel_id
        }

        view = QuizQuestionView(self.cog, user_id, 0)
        embed = view.build_embed(0, questions[0], QUIZ_DURATION)
        try:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception:
            self.cog.sessions.pop(user_id, None)
            if quota_token:
                await asyncio.to_thread(release, quota_token)
            raise

        # Start the five-minute clock only after Discord has actually accepted
        # the first question; time spent queued behind a busy API no longer
        # consumes the user's answering time.
        session = self.cog.sessions.get(user_id)
        if session:
            session["start_time"] = discord.utils.utcnow()
            asyncio.create_task(self.cog.timer_task(interaction, user_id, session))

class QuizQuestionView(discord.ui.View):
    # ✨ 修改点：初始化时接收 cog 实例
    def __init__(self, cog: commands.Cog, user_id: int, q_index: int):
        super().__init__(timeout=QUIZ_DURATION)
        self.cog = cog # 保存 cog 实例
        self.user_id = user_id
        self.q_index = q_index

        # ✨ 修改点：通过 self.cog 访问
        session = self.cog.sessions.get(user_id)
        self.session = session
        if session and q_index < len(session["questions"]):
            question = session["questions"][q_index]
            options = [
                discord.SelectOption(
                    label=f"选项 {key}",
                    description=(val[:48] + "...") if len(val) > 48 else val,
                    value=key,
                    default=key in session.get("drafts", {}).get(q_index, []),
                    emoji="👉"
                ) for key, val in question["options"].items()
            ]
            select = discord.ui.Select(
                placeholder="请选择你的答案 (完整内容见上方)",
                options=options,
                min_values=1,
                max_values=len(options) if question.get("type") == "multiple" else 1,
                custom_id=f"quiz_select_{q_index}_{user_id}"
            )
            select.callback = self.select_callback
            self.add_item(select)
            if question.get("type") == "multiple":
                confirm = discord.ui.Button(label="确认本题", style=discord.ButtonStyle.success,
                    disabled=not session.get("drafts", {}).get(q_index))
                confirm.callback = self.confirm_callback
                self.add_item(confirm)

    def build_embed(self, index, question, remaining_time):
        kind = "多选 · 选全才得分，少选、多选、错选均不得分；选好后点击确认" if question.get("type") == "multiple" else "单选"
        mode = "🧪 管理员测试模式 · 不变更身份、不计入正式记录\n" if self.session and self.session.get("test_mode") else ""
        desc = f"{mode}**{kind}**\n### **{question['question']}**\n\n"
        for key, val in question["options"].items():
            desc += f"> **{key}.** {val}\n"
        embed = discord.Embed(title=f"📝 第 {index + 1}/{len(self.session['questions'])} 题", description=desc, color=STYLE["KIMI_YELLOW"])
        embed.set_footer(text=f"⏱️ 剩余时间: {remaining_time}秒 (总共5分钟)")
        return embed

    async def select_callback(self, interaction):
        await self.handle_answer(interaction, confirm=False)

    async def confirm_callback(self, interaction):
        await self.handle_answer(interaction, confirm=True)

    async def handle_answer(self, interaction, *, confirm):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("这不是你的考卷！", ephemeral=True)
        await interaction.response.defer()
        session = self.cog.sessions.get(self.user_id)
        if session is None or session is not self.session:
            return await interaction.followup.send("这份考卷已结束，请使用当前答题面板。", ephemeral=True)
        async with session.setdefault("lock", asyncio.Lock()):
            if self.cog.sessions.get(self.user_id) is not session:
                return
            if self.q_index != len(session["answers"]):
                return await interaction.followup.send("本题已确认，请在最新页面继续。", ephemeral=True)
            elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()
            if elapsed >= QUIZ_DURATION:
                return await self.cog.finalize_quiz(interaction, self.user_id, is_timeout=True)
            question = session["questions"][self.q_index]
            multiple = question.get("type") == "multiple"
            drafts = session.setdefault("drafts", {})
            values = drafts.get(self.q_index, []) if confirm else interaction.data.get("values", [])
            if (not values or len(values) != len(set(values)) or not set(values) <= set(question["options"])
                    or (not multiple and len(values) != 1)):
                return await interaction.followup.send("请选择有效答案后再确认。", ephemeral=True)
            if multiple and not confirm:
                drafts[self.q_index] = list(values)
                view = QuizQuestionView(self.cog, self.user_id, self.q_index)
                return await interaction.edit_original_response(
                    embed=view.build_embed(self.q_index, question, max(0, int(QUIZ_DURATION-elapsed))), view=view)
            session["answers"][self.q_index] = list(values)
            drafts.pop(self.q_index, None)
            next_index = self.q_index + 1
            if next_index == len(session["questions"]):
                return await self.cog.finalize_quiz(interaction, self.user_id, is_timeout=False)
            view = QuizQuestionView(self.cog, self.user_id, next_index)
            await interaction.edit_original_response(embed=view.build_embed(next_index,
                session["questions"][next_index], max(0, int(QUIZ_DURATION-elapsed))), view=view)
