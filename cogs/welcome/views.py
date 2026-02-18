# cogs/welcome/views.py

import discord
import asyncio
import random
from discord.ext import commands

from config import IDS, STYLE
from .data import QUIZ_QUESTIONS
from .cog import quiz_sessions, check_cooldown, finalize_quiz,PUBLIC_RESULT_CHANNEL_ID, QUIZ_LOG_CHANNEL_ID, timer_task

# --- 配置区 ---
QUIZ_DURATION = 120

class QuizStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 点击开始答题", style=discord.ButtonStyle.success, custom_id="quiz_entry_start")
    async def start_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 1. 【核心修复】立即 Defer，防止 10062 错误
        await interaction.response.defer(ephemeral=True)
        
        user_id = interaction.user.id

        # 2. 检查是否已有身份组
        newbie_role = interaction.guild.get_role(IDS["VERIFICATION_ROLE_ID"])
        hatched_role = interaction.guild.get_role(IDS.get("HATCHED_ROLE_ID"))

        has_newbie = newbie_role and newbie_role in interaction.user.roles
        has_hatched = hatched_role and hatched_role in interaction.user.roles

        if has_newbie or has_hatched:
            return await interaction.followup.send("你已经是新兵蛋子或正式成员啦，不需要再答题咯！", ephemeral=True)

        if user_id in quiz_sessions:
            session = quiz_sessions[user_id]
            elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()

            if elapsed < QUIZ_DURATION:
                remaining = int(QUIZ_DURATION - elapsed)
                q_index = len(session["answers"])
                if q_index >= len(session["questions"]):
                    q_index = len(session["questions"]) - 1

                question = session["questions"][q_index]
                view = QuizQuestionView(user_id, q_index)
                embed = view.build_embed(q_index, question, remaining)

                # 使用 followup 发送
                await interaction.followup.send(
                    content="⚠️ **检测到你有未完成的答题，已为你恢复进度：**",
                    embed=embed,
                    view=view,
                    ephemeral=True
                )
                return
            else:
                del quiz_sessions[user_id]

        # 3. 检查冷却
        can_start, wait_time = check_cooldown(user_id)
        if not can_start:
            await interaction.followup.send(f"⏳ 答题冷却中！\n请休息一下，再过 **{wait_time // 60}分{wait_time % 60}秒** 才能再次尝试哦。", ephemeral=True)
            return

        # 4. 初始化
        questions = random.sample(QUIZ_QUESTIONS, 10)
        quiz_sessions[user_id] = {
            "questions": questions,
            "answers": {},
            "start_time": discord.utils.utcnow(),
            "channel_id": interaction.channel_id
        }

        # 5. 显示第一题 (使用 followup)
        view = QuizQuestionView(user_id, 0)
        embed = view.build_embed(0, questions[0], 120)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        # 启动计时任务
        asyncio.create_task(timer_task(interaction, user_id))

class QuizQuestionView(discord.ui.View):
    def __init__(self, user_id, q_index):
        super().__init__(timeout=QUIZ_DURATION)
        self.user_id = user_id
        self.q_index = q_index

        # 动态添加 Select
        session = quiz_sessions.get(user_id)
        if session and q_index < len(session["questions"]):
            question = session["questions"][q_index]
            options = []

            for key, val in question["options"].items():

                preview_text = (val[:48] + "...") if len(val) > 48 else val

                options.append(discord.SelectOption(
                    label=f"选项 {key}",       
                    description=preview_text,  
                    value=key,
                    emoji="👉" 
                ))

            select = discord.ui.Select(
                placeholder="请选择你的答案 (完整内容见上方)",
                min_values=1,
                max_values=1,
                options=options,
                custom_id=f"quiz_select_{q_index}_{user_id}"
            )
            select.callback = self.select_callback
            self.add_item(select)

    def build_embed(self, index, question, remaining_time):
        # 1. 题目部分
        desc = f"### **{question['question']}**\n\n" 

        for key, val in question["options"].items():
            desc += f"> **{key}.** {val}\n"

        embed = discord.Embed(
            title=f"📝 第 {index + 1}/10 题",
            description=desc,
            color=STYLE["KIMI_YELLOW"]
        )
        embed.set_footer(text=f"⏱️ 剩余时间: {remaining_time}秒 (总共2分钟)")
        return embed

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if interaction.user.id != self.user_id:
            return await interaction.followup.send("这不是你的考卷！", ephemeral=True)

        session = quiz_sessions.get(self.user_id)
        if not session:
            return await interaction.followup.send("❌ 会话已超时或已结束，请重新开始。", ephemeral=True)

        try:
            session["answers"][self.q_index] = interaction.data['values'][0]
        except:
             session["answers"][self.q_index] = interaction.values[0]

        next_index = self.q_index + 1
        if next_index < len(session["questions"]):
            next_q = session["questions"][next_index]
            elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()
            remaining = max(0, QUIZ_DURATION - int(elapsed))

            view = QuizQuestionView(self.user_id, next_index)
            embed = view.build_embed(next_index, next_q, remaining)

            try:
                await interaction.edit_original_response(embed=embed, view=view)
            except Exception as e:
                print(f"Edit error: {e}")
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await finalize_quiz(interaction, self.user_id, is_timeout=False)