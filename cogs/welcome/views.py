# cogs/welcome/views.py

import discord
import asyncio
import random
from datetime import timedelta
from discord.ext import commands

from config import IDS, STYLE
from .data import QUIZ_QUESTIONS

# --- 配置区 ---
QUIZ_DURATION = 120
MIN_ACCOUNT_AGE_DAYS = 30
MIN_MUTUAL_GUILDS = 2

class QuizStartView(discord.ui.View):
    # ✨ 修改点：初始化时接收 cog 实例
    def __init__(self, cog: commands.Cog):
        super().__init__(timeout=None)
        self.cog = cog 

    def _collect_risk_reasons(self, interaction: discord.Interaction):
        """收集不允许答题的风控原因。"""
        reasons = []
        user = interaction.user
        now = discord.utils.utcnow()

        account_age = now - user.created_at
        if account_age < timedelta(days=MIN_ACCOUNT_AGE_DAYS):
            reasons.append(f"账号注册时间不足 {MIN_ACCOUNT_AGE_DAYS} 天")

        owner_id = IDS.get("SERVER_OWNER_ID")
        mutual_guild_count = self._get_mutual_guild_count_with_owner(user.id, owner_id)
        if mutual_guild_count is not None and mutual_guild_count < MIN_MUTUAL_GUILDS:
            reasons.append("当前仅加入本服务器，暂不开放自助答题")

        public_flags = getattr(user, "public_flags", None)
        is_suspected_spammer = bool(getattr(public_flags, "spammer", False)) if public_flags else False
        if is_suspected_spammer:
            reasons.append("账号被系统标记为可疑/疑似垃圾账号")

        return reasons

    def _get_mutual_guild_count_with_owner(self, user_id: int, owner_id: int | None):
        """统计“用户与服主”共同所在服务器数；无法可靠判断时返回 None。"""
        if not owner_id:
            return None

        if not getattr(self.cog.bot.intents, "members", False):
            return None

        mutual_count = 0
        owner_visible = False
        for guild in self.cog.bot.guilds:
            owner_member = guild.get_member(owner_id)
            if not owner_member:
                continue

            owner_visible = True
            if guild.get_member(user_id):
                mutual_count += 1

        if not owner_visible:
            return None

        return mutual_count
        return None

    @discord.ui.button(label="📝 点击开始答题", style=discord.ButtonStyle.success, custom_id="quiz_entry_start")
    async def start_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id

        newbie_role = interaction.guild.get_role(IDS["VERIFICATION_ROLE_ID"])
        hatched_role = interaction.guild.get_role(IDS.get("HATCHED_ROLE_ID"))
        has_newbie = newbie_role and newbie_role in interaction.user.roles
        has_hatched = hatched_role and hatched_role in interaction.user.roles
        if has_newbie or has_hatched:
            return await interaction.followup.send("你已经是新兵蛋子或正式成员啦，不需要再答题咯！", ephemeral=True)

        risk_reasons = self._collect_risk_reasons(interaction)
        if risk_reasons:
            reason_text = "\n".join(f"• {reason}" for reason in risk_reasons)
            return await interaction.followup.send(
                "⚠️ 当前账号暂不满足自助答题条件：\n"
                f"{reason_text}\n\n"
                "请先在社区正常活跃一段时间，再联系管理员进行人工核验。",
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
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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

        session = self.cog.sessions.get(self.user_id)
        if not session:
             await interaction.response.edit_message(content="❌ 会话已超时或已结束，请重新开始。", view=None, embed=None)
             return

        session["answers"][self.q_index] = interaction.data['values'][0]

        next_index = self.q_index + 1
        if next_index < len(session["questions"]):
            next_q = session["questions"][next_index]
            elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()
            remaining = max(0, QUIZ_DURATION - int(elapsed))

            view = QuizQuestionView(self.cog, self.user_id, next_index)
            embed = view.build_embed(next_index, next_q, remaining)

            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await self.cog.finalize_quiz(interaction, self.user_id, is_timeout=False)