# quiz.py
import discord
from discord.ext import commands
import asyncio
import random
import datetime
from config import IDS, STYLE
from quiz_data import QUIZ_QUESTIONS

# --- 配置区 ---
QUIZ_CHANNEL_ID = IDS.get("QUIZ_CHANNEL_ID")
SUPER_EGG_ROLE_ID = IDS.get("SUPER_EGG_ROLE_ID")
QUIZ_LOG_CHANNEL_ID = IDS.get("QUIZ_LOG_CHANNEL_ID") 
PUBLIC_RESULT_CHANNEL_ID = 1452485785939869808

RETRY_COOLDOWN = 900      # 15分钟冷却 (900秒)
MAX_ATTEMPTS = 999        # 答题次数不限，但有冷却
QUIZ_DURATION = 120       # 2分钟倒计时

# --- 数据存储 ---
quiz_sessions = {}
quiz_history = {} 

# ======================================================================================
# --- 辅助函数 ---
# ======================================================================================

def check_cooldown(user_id):
    """检查用户是否在冷却中"""
    history = quiz_history.get(user_id)
    if not history:
        return True, 0

    elapsed = (datetime.datetime.utcnow() - history).total_seconds()
    if elapsed < RETRY_COOLDOWN:
        return False, int(RETRY_COOLDOWN - elapsed)
    return True, 0

# ======================================================================================
# --- 视图类 (Views) ---
# ======================================================================================

class QuizStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 点击开始答题", style=discord.ButtonStyle.success, custom_id="quiz_entry_start")
    async def start_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        user_id = interaction.user.id

        # 1. 检查是否已有身份组
        newbie_role = interaction.guild.get_role(IDS["VERIFICATION_ROLE_ID"])
        hatched_role = interaction.guild.get_role(IDS.get("HATCHED_ROLE_ID"))

        has_newbie = newbie_role and newbie_role in interaction.user.roles
        has_hatched = hatched_role and hatched_role in interaction.user.roles

        if has_newbie or has_hatched:
            await interaction.response.send_message("你已经是新兵蛋子或正式成员啦，不需要再答题咯！要去全区审核请前往审核频道~", ephemeral=True)
            return

        if user_id in quiz_sessions:
            session = quiz_sessions[user_id]
            elapsed = (datetime.datetime.utcnow() - session["start_time"]).total_seconds()

            if elapsed < QUIZ_DURATION:
                remaining = int(QUIZ_DURATION - elapsed)
                # 找到第一个未答的题
                q_index = len(session["answers"])
                if q_index >= len(session["questions"]):
                    q_index = len(session["questions"]) - 1

                question = session["questions"][q_index]
                view = QuizQuestionView(user_id, q_index)
                embed = view.build_embed(q_index, question, remaining)

                # 使用 ephemeral 发送，当作“恢复现场”
                await interaction.response.send_message(
                    content="⚠️ **检测到你有未完成的答题，已为你恢复进度：**",
                    embed=embed,
                    view=view,
                    ephemeral=True
                )
                return
            else:
                # 已经超时了但因为某种原因session没清掉，强制清除，继续走下面的新流程
                del quiz_sessions[user_id]

        # 3. 检查冷却
        can_start, wait_time = check_cooldown(user_id)
        if not can_start:
            await interaction.response.send_message(f"⏳ 答题冷却中！\n请休息一下，再过 **{wait_time // 60}分{wait_time % 60}秒** 才能再次尝试哦。", ephemeral=True)
            return

        # 4. 初始化
        questions = random.sample(QUIZ_QUESTIONS, 10)
        quiz_sessions[user_id] = {
            "questions": questions,
            "answers": {},
            "start_time": datetime.datetime.utcnow(),
            "channel_id": interaction.channel_id
        }

        # 5. 显示第一题
        view = QuizQuestionView(user_id, 0)
        embed = view.build_embed(0, questions[0], 120)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # 启动计时任务
        asyncio.create_task(timer_task(interaction, user_id))

async def timer_task(interaction, user_id):
    try:
        await asyncio.sleep(QUIZ_DURATION)
        # 检查在此期间是否已经完成（不在session里了）
        if user_id in quiz_sessions:
            # 再次检查时间，防止刚刚好交卷导致的冲突
            session = quiz_sessions[user_id]
            elapsed = (datetime.datetime.utcnow() - session["start_time"]).total_seconds()
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

        # 检查session是否存在，再动态添加下拉菜单
        session = quiz_sessions.get(user_id)
        if session and q_index < len(session["questions"]):
            question = session["questions"][q_index]
            options = []
            for key, val in question["options"].items():
                options.append(discord.SelectOption(label=f"{key}. {val}", value=key))

            select = discord.ui.Select(
                placeholder="请选择一个答案...",
                min_values=1,
                max_values=1,
                options=options,
                custom_id=f"quiz_select_{q_index}"
            )
            select.callback = self.select_callback
            self.add_item(select)

    def build_embed(self, index, question, remaining_time):
        embed = discord.Embed(title=f"第 {index + 1}/10 题", description=f"**{question['question']}**", color=STYLE["KIMI_YELLOW"])
        embed.set_footer(text=f"⏱️ 剩余时间: {remaining_time}秒 (总共2分钟)")
        return embed

    async def select_callback(self, interaction: discord.Interaction):
        # 用户验证
        if interaction.user.id != self.user_id:
            try:
                return await interaction.response.send_message("这不是你的考卷！", ephemeral=True)
            except:
                return

        # 确认session存在
        session = quiz_sessions.get(self.user_id)
        if not session:
            try:
                return await interaction.response.send_message("❌ 会话已超时或已结束，请重新开始。", ephemeral=True)
            except:
                return

        # 记录答案
        session["answers"][self.q_index] = interaction.values[0]

        # 下一题
        next_index = self.q_index + 1
        if next_index < len(session["questions"]):
            next_q = session["questions"][next_index]

            elapsed = (datetime.datetime.utcnow() - session["start_time"]).total_seconds()
            remaining = max(0, QUIZ_DURATION - int(elapsed))

            view = QuizQuestionView(self.user_id, next_index)
            embed = view.build_embed(next_index, next_q, remaining)
            
            try:
                # 尝试编辑消息
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    # Fallback：如果已响应过，则用followup
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            except discord.errors.NotFound:
                # 交互已过期，忽略
                pass
            except Exception as e:
                print(f"编辑消息出错: {e}")
        else:
            # 答完了，调用finalize
            try:
                await finalize_quiz(interaction, self.user_id, is_timeout=False)
            except Exception as e:
                print(f"结果处理出错: {e}")

async def finalize_quiz(interaction, user_id, is_timeout=False):
    # 安全检查：确保还在session里，防止多次调用
    if user_id not in quiz_sessions: 
        return

    session = quiz_sessions.pop(user_id)
    quiz_history[user_id] = datetime.datetime.utcnow() # 记录结束时间用于冷却

    score = 0
    details = []

    for i, q in enumerate(session["questions"]):
        ans = session["answers"].get(i, None)
        is_correct = (ans == q["answer"])
        if is_correct: score += 10
        details.append(f"Q{i+1}: {'✅' if is_correct else '❌'} (选{ans}/对{q['answer']})")

    # 结果判定
    passed = score >= 60

    # 1. 给用户的反馈 Embed
    embed = discord.Embed(
        title="📝 答题结束",
        description=f"**最终得分: {score}/100**\n" + ("⏱️ 超时提交" if is_timeout else ""),
        color=0x00FF00 if passed else 0xFF0000
    )

    if passed:
        embed.description += "\n\n🎉 **恭喜通过！**\n✅ 已自动获得【新兵蛋子】身份组。\n🔓 已解锁：象牙塔、极光及部分分区。\n\n**⚠️ 如需解锁【卡区】等所有区域：**\n请前往 <#1417572579304013885> 申请人工审核。"

        # 发放身份组
        role = interaction.guild.get_role(IDS["VERIFICATION_ROLE_ID"])
        if role:
            try:
                await interaction.user.add_roles(role, reason="自助答题通过")
            except: pass
    else:
        embed.description += f"\n\n❌ **未通过 (需60分)**\n请仔细阅读规则或群公告。\n**请等待 15分钟 后再次尝试。**"

    # 编辑原消息显示结果
    try:
        if isinstance(interaction, discord.Interaction):
            try:
                # 检查响应是否已处理
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=None)
                else:
                    # 已响应过，使用followup
                    await interaction.followup.send(embed=embed, ephemeral=True)
            except discord.errors.NotFound:
                # 交互已过期，尝试followup
                try:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                except:
                    pass
            except Exception as e:
                print(f"发送结果失败: {e}")
    except Exception as e:
        print(f"响应结果异常: {e}")

    # 2. 发送公示到指定频道
    try:
        public_channel = interaction.guild.get_channel(PUBLIC_RESULT_CHANNEL_ID)
        if public_channel:
            status_emoji = "🟢" if passed else "🔴"
            status_text = "**通过**" if passed else "**未通过**"

            public_embed = discord.Embed(
                description=f"{status_emoji} 用户 {interaction.user.mention} 完成了入站答题。\n📊 结果：{status_text} (得分: `{score}`) {'⏱️ (超时)' if is_timeout else ''}",
                color=0x00FF00 if passed else 0xFF0000
            )
            if not passed:
                public_embed.set_footer(text="请在冷却时间结束后再试")

            await public_channel.send(embed=public_embed)
    except Exception as e:
        print(f"发送公开结果失败: {e}")

    # 3. 日志
    try:
        log_channel = interaction.guild.get_channel(QUIZ_LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(title=f"答题详情: {interaction.user.display_name} ({interaction.user.id})", description=f"分数: {score}\n结果: {'通过' if passed else '失败'}\n\n" + "\n".join(details))
            await log_channel.send(embed=log_embed)
    except Exception as e:
        print(f"发送日志失败: {e}")

class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            self.bot.add_view(QuizStartView())
            print("[Quiz] Views registered successfully.")
        except Exception as e:
            print(f"[Quiz] Failed to register views: {e}")

    @discord.slash_command(name="入站答题面板", description="（管理员）发送入站答题面板")
    async def setup_quiz_panel(self, ctx):
        try:
            if not ctx.guild.get_role(SUPER_EGG_ROLE_ID) in ctx.author.roles:
                return await ctx.respond("无权操作", ephemeral=True)

            channel = ctx.guild.get_channel(IDS["QUIZ_CHANNEL_ID"])
            if not channel:
                return await ctx.respond("找不到答题频道配置", ephemeral=True)

            embed = discord.Embed(
                title="📝 新兵蛋子入站答题",
                description=(
                    "欢迎来到 **🔮LOFI-加载中**！\n"
                    "为了维护社区环境，请在开始答题前仔细阅读以下内容。\n\n"

                    "📘 **第一步：阅读指引**\n"
                    "**请务必先前往 <#1417568378889175071> 仔细阅读频道指引！**\n"

                    "🛑 **第二步：社区核心原则确认**\n"
                    "1. **社区定位**：我们是非商业化 SillyTavern 女性社区，仅欢迎有酒馆使用经验的同好。\n"
                    "2. **资源红线**：严禁将社区资源用于商业云酒馆、付费服务或第三方软件（如Tavo、Omate）。\n"
                    "3. **拒绝商业**：坚决反对任何形式的商业化，请勿推荐非官方付费API或节点。\n\n"
                    "----------------------------------------------------\n"
                    "**同意以上条款后，请开始答题：**\n\n"
                    "**规则说明：**\n"
                    "• 共10道题，涉及SillyTavern基础与社区规则\n"
                    "• **限时 2 分钟**，60分及格\n"
                    "• **答题失败需等待 15 分钟冷却**\n"
                    "• 通过后自动获得 `新兵蛋子` 身份，解锁象牙塔、极光等频道\n\n"
                    "**准备好了吗？点击下方按钮开始！**"
                ),
                color=STYLE["KIMI_YELLOW"]
            )
            await channel.send(embed=embed, view=QuizStartView())
            await ctx.respond("面板已发送", ephemeral=True)
        except Exception as e:
            print(f"设置答题面板出错: {e}")
            await ctx.respond(f"❌ 发送面板失败: {str(e)}", ephemeral=True)

def setup(bot):
    bot.add_cog(Quiz(bot))
