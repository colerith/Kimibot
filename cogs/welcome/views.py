# cogs/welcome/views.py

import discord
import asyncio
import random
from discord.ext import commands

from config import IDS, STYLE
from .data import QUIZ_QUESTIONS
from cog import quiz_sessions, quiz_history, check_cooldown, finalize_quiz,PUBLIC_RESULT_CHANNEL_ID, QUIZ_LOG_CHANNEL_ID

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

async def timer_task(interaction, user_id):
    try:
        await asyncio.sleep(QUIZ_DURATION)
        if user_id in quiz_sessions:
            session = quiz_sessions[user_id]
            elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()
            if elapsed >= QUIZ_DURATION:
                # 超时结算
                await finalize_quiz(interaction, user_id, is_timeout=True)
    except Exception as e:
        print(f"计时任务出错: {e}")

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

async def finalize_quiz(interaction, user_id, is_timeout=False):
    if user_id not in quiz_sessions: 
        return

    session = quiz_sessions.pop(user_id)
    quiz_history[user_id] = discord.utils.utcnow()

    score = 0
    details = []

    for i, q in enumerate(session["questions"]):
        ans = session["answers"].get(i, None)
        is_correct = (ans == q["answer"])
        if is_correct: score += 10
        details.append(f"Q{i+1}: {'✅' if is_correct else '❌'} (选{ans}/对{q['answer']})")

    passed = score >= 60
    embed = discord.Embed(
        title="📝 答题结束",
        description=f"**最终得分: {score}/100**\n" + ("⏱️ 超时提交" if is_timeout else ""),
        color=0x00FF00 if passed else 0xFF0000
    )

    if passed:
        embed.description += "\n\n🎉 **恭喜通过！**\n✅ 已自动获得【新兵蛋子】身份组。\n🔓 已解锁：象牙塔、极光及部分分区。"
        role = interaction.guild.get_role(IDS["VERIFICATION_ROLE_ID"])
        if role:
            try:
                # 获取 member 对象，interaction.user 有时只是 User 类型
                member = interaction.guild.get_member(user_id) or interaction.user
                await member.add_roles(role, reason="自助答题通过")
            except Exception as e:
                print(f"加身份组失败: {e}")
    else:
        embed.description += f"\n\n❌ **未通过 (需60分)**\n请仔细阅读规则或群公告。\n**请等待 15分钟 后再次尝试。**"

    # 结果展示：这里最容易出错，需要兼容不同的 interaction 状态
    try:
        if is_timeout:
            # 超时是由后台任务触发的，interaction 可能已经过期，尝试 followup
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            # 正常答完，因为 SelectCallback 里 defer 过了，所以用 edit_original_response
            try:
                await interaction.edit_original_response(embed=embed, view=None)
            except:
                await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"发送结果给用户失败 (可能是token彻底过期): {e}")

    # 下面是发送到公开频道和日志频道 (无需修改，这些通常不会报 interaction 错误)
    try:
        public_channel = interaction.guild.get_channel(PUBLIC_RESULT_CHANNEL_ID)
        if public_channel:
            status_emoji = "🟢" if passed else "🔴"
            status_text = "**通过**" if passed else "**未通过**"
            # 获取用户 mention
            user_mention = f"<@{user_id}>"
            
            public_embed = discord.Embed(
                description=f"{status_emoji} 用户 {user_mention} 完成了入站答题。\n📊 结果：{status_text} (得分: `{score}`) {'⏱️ (超时)' if is_timeout else ''}",
                color=0x00FF00 if passed else 0xFF0000
            )
            if not passed:
                public_embed.set_footer(text="请在冷却时间结束后再试")
            await public_channel.send(embed=public_embed)
    except Exception as e:
        print(f"发送公开结果失败: {e}")

    try:
        log_channel = interaction.guild.get_channel(QUIZ_LOG_CHANNEL_ID)
        if log_channel:
            user_name = interaction.user.display_name if hasattr(interaction.user, 'display_name') else str(user_id)
            log_embed = discord.Embed(title=f"答题详情: {user_name} ({user_id})", description=f"分数: {score}\n结果: {'通过' if passed else '失败'}\n\n" + "\n".join(details))
            await log_channel.send(embed=log_embed)
    except Exception as e:
        print(f"发送日志失败: {e}")