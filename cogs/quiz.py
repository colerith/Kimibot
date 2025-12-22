import discord
from discord.ext import commands
import asyncio
import random
import datetime
from config import IDS, STYLE
from quiz_data import QUIZ_QUESTIONS

# --- 配置区 ---
SECOND_REVIEW_CHANNEL_ID = IDS.get("SECOND_REVIEW_CHANNEL_ID", 1419599094988537856)
SUPER_EGG_ROLE_ID = IDS.get("SUPER_EGG_ROLE_ID", 1417724603253395526)
QUIZ_LOG_CHANNEL_ID = 1452485785939869808
MAX_ATTEMPTS = 3          # 最大尝试次数
RETRY_COOLDOWN = 20       # 重试冷却时间（秒）

# --- 数据存储 ---
quiz_sessions = {}
quiz_history = {}

# ======================================================================================
# --- 辅助函数 ---
# ======================================================================================

def check_user_can_start(user_id):
    """检查用户是否符合开始答题的条件（次数和冷却）"""
    history = quiz_history.get(user_id, {"count": 0, "last_end_time": None})
    
    # 1. 检查次数
    if history["count"] >= MAX_ATTEMPTS:
        return False, f"🚫 你的 {MAX_ATTEMPTS} 次答题机会已用尽，无法再次答题。请联系管理员。"
    
    # 2. 检查冷却
    if history["last_end_time"]:
        elapsed = (datetime.datetime.utcnow() - history["last_end_time"]).total_seconds()
        if elapsed < RETRY_COOLDOWN:
            wait_time = int(RETRY_COOLDOWN - elapsed)
            return False, f"⏳ 请休息一下！你需要等待 {wait_time} 秒后才能再次尝试。"
            
    return True, None

def record_attempt_end(user_id):
    """记录一次答题结束（扣除次数，记录时间）"""
    if user_id not in quiz_history:
        quiz_history[user_id] = {"count": 0, "last_end_time": None}
    
    quiz_history[user_id]["count"] += 1
    quiz_history[user_id]["last_end_time"] = datetime.datetime.utcnow()
    
    return quiz_history[user_id]["count"]

def get_ticket_info_from_channel(channel):
    """从频道Topic提取工单信息"""
    info = {}
    if not channel.topic: return info
    try:
        parts = channel.topic.split(" | ")
        for part in parts:
            if ": " in part:
                key, value = part.split(": ", 1)
                info[key] = value
    except: pass
    return info

# ======================================================================================
# --- 视图类 (Views) ---
# ======================================================================================

# 视图1：初始开始按钮 / 失败后的重试按钮
class QuizStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="✅ 我准备好了，开始答题！", style=discord.ButtonStyle.success, custom_id="quiz_start_button")
    async def start_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # 1. 检查是否已经在答题中
        if user_id in quiz_sessions:
            await interaction.response.send_message("你已经在答题中了哦！请先完成当前的答题。", ephemeral=True)
            return
        
        # 2. 检查次数限制和冷却时间
        can_start, reason = check_user_can_start(user_id)
        if not can_start:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        
        # 3. 初始化题目
        selected_questions = random.sample(QUIZ_QUESTIONS, 10)
        history = quiz_history.get(user_id, {"count": 0})
        attempts_left = MAX_ATTEMPTS - history["count"]
        
        # 创建答题会话
        quiz_sessions[user_id] = {
            "questions": selected_questions,
            "answers": {},
            "start_time": None,
            "current_q": 0,
            "channel_id": interaction.channel_id
        }
        
        embed = discord.Embed(
            title="📝 二审问卷",
            description=f"{interaction.user.mention} 你好！\n\n"
                       f"本次测试共有 **10道题**，满分 **100分**。\n"
                       f"当前剩余机会：**{attempts_left}/{MAX_ATTEMPTS}** 次\n\n"
                       "**规则说明：**\n"
                       "• 点击下方按钮开始答题，**2分钟倒计时**自动开始\n"
                       "• 题目将**逐题显示**，每次只能看到一道题\n"
                       "• 答题过程中**不会**告知你答案是否正确\n"
                       "• 时间到或答完所有题后，系统会公布成绩\n\n"
                       "**准备好了吗？点击下方按钮开始答题！**",
            color=STYLE["KIMI_YELLOW"]
        )
        
        view = QuizBeginView(user_id)
        view.interaction_ref = interaction
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# 视图2：重试引导视图（仅在失败时显示）
class QuizRetryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # 不超时，让按钮留着

    @discord.ui.button(label="🔄 再次尝试 (需等待20秒)", style=discord.ButtonStyle.primary, custom_id="quiz_retry_btn")
    async def retry(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 复用 StartView 的逻辑，因为逻辑是一样的（检查冷却+检查次数）
        # 这里直接创建一个 StartView 实例并调用其 start_quiz 方法
        start_view = QuizStartView()
        # 为了适配 start_quiz 的参数要求，我们需要手动传入 button
        await start_view.start_quiz(button, interaction)

# 视图3：确认开始计时视图
class QuizBeginView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.interaction_ref = None
    
    async def on_timeout(self):
        # 清理未开始的会话（还在看规则没点开始）
        if self.user_id in quiz_sessions:
            session = quiz_sessions[self.user_id]
            if session.get("start_time") is None:  
                del quiz_sessions[self.user_id]
                if self.interaction_ref:
                    try:
                        timeout_embed = discord.Embed(
                            title="⏰ 会话已过期",
                            description="你太久没有点击开始，请重新点击“准备好了”按钮。",
                            color=0xFF0000
                        )
                        await self.interaction_ref.edit_original_response(embed=timeout_embed, view=None)
                    except: pass
    
    @discord.ui.button(label="🚀 开始答题", style=discord.ButtonStyle.primary, custom_id="quiz_begin")
    async def begin_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.interaction_ref = interaction
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这不是你的答题按钮哦！", ephemeral=True)
            return
        
        session = quiz_sessions.get(self.user_id)
        if not session:
            await interaction.response.send_message("会话已过期，请重新开始。", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # 开始计时
        session["start_time"] = datetime.datetime.utcnow()
        
        # 显示第一题
        await self.show_question(interaction, session, 0)
        
        # 启动全局2分钟倒计时任务
        asyncio.create_task(self.timer_task(interaction.user, session))
    
    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary, custom_id="quiz_cancel")
    async def cancel_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这不是你的答题按钮哦！", ephemeral=True)
            return
        
        if self.user_id in quiz_sessions:
            del quiz_sessions[self.user_id]
        
        cancel_embed = discord.Embed(title="✅ 已取消", description="已取消答题。这不会扣除你的答题次数。", color=STYLE["KIMI_YELLOW"])
        await interaction.response.edit_message(embed=cancel_embed, view=None)
    
    async def show_question(self, interaction, session, q_index):
        if q_index >= len(session["questions"]):
            # 正常答完所有题目
            await finalize_quiz_result(interaction.user, interaction, session, is_timeout=False)
            return
        
        question = session["questions"][q_index]
        session["current_q"] = q_index
        
        # 计算剩余时间
        elapsed = (datetime.datetime.utcnow() - session["start_time"]).total_seconds()
        remaining = max(0, 120 - int(elapsed))
        
        embed = discord.Embed(
            title=f"📋 第 {q_index + 1}/10 题",
            description=f"**{question['question']}**\n\n" + 
                       "\n".join([f"{key}. {value}" for key, value in question["options"].items()]),
            color=STYLE["KIMI_YELLOW"]
        )
        embed.set_footer(text=f"⏱️ 剩余时间：{remaining // 60}:{remaining % 60:02d}")
        
        view = QuizAnswerView(self.user_id, q_index, list(question["options"].keys()))
        await interaction.edit_original_response(embed=embed, view=view)

    async def timer_task(self, user, session):
        # 等待120秒
        await asyncio.sleep(120)
        
        # 检查用户是否还在会话中（如果没有被手动提交删除）
        if user.id in quiz_sessions:
            # 获取交互对象（用于编辑消息）
            # 注意：在超时任务中很难获取原interaction进行edit，通常只能发新消息
            channel = user.guild.get_channel(session["channel_id"]) if session.get("channel_id") else None
            
            # 调用统一结算逻辑
            if channel:
                await finalize_quiz_result(user, channel, session, is_timeout=True)

# 视图4：答题选项视图
class QuizAnswerView(discord.ui.View):
    def __init__(self, user_id, q_index, options):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.q_index = q_index
        for option in options:
            button = discord.ui.Button(label=option, style=discord.ButtonStyle.secondary)
            button.callback = self.create_callback(option)
            self.add_item(button)
    
    def create_callback(self, option):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("这不是你的答题按钮哦！", ephemeral=True)
                return
            
            session = quiz_sessions.get(self.user_id)
            if not session:
                await interaction.response.send_message("会话已过期。", ephemeral=True)
                return
            
            await interaction.response.defer()
            session["answers"][self.q_index] = option
            
            # 下一题
            next_q = self.q_index + 1
            if next_q < len(session["questions"]):
                # 使用 QuizBeginView 中的逻辑显示下一题
                view = QuizBeginView(self.user_id)
                await view.show_question(interaction, session, next_q)
            else:
                # 答完最后一题
                await finalize_quiz_result(interaction.user, interaction, session, is_timeout=False)
        return callback

# ======================================================================================
# --- 核心逻辑：统一结算函数 ---
# ======================================================================================

async def finalize_quiz_result(user, interface, session, is_timeout=False):
    """
    统一处理答题结束逻辑
    :param user: Discord User对象
    :param interface: 可能是 Interaction (正常答完) 或 Channel (超时)
    :param session: 会话数据
    :param is_timeout: 是否因为超时结束
    """
    # 1. 防止重复结算
    if user.id not in quiz_sessions:
        return
    
    # 删除会话
    del quiz_sessions[user.id]
    
    # 2. 计算分数
    score = 0
    details = []
    for i, question in enumerate(session["questions"]):
        user_answer = session["answers"].get(i, "未作答")
        correct = user_answer == question["answer"]
        if correct: score += 10
        details.append({
            "question": question["question"],
            "user_answer": user_answer,
            "correct_answer": question["answer"],
            "is_correct": correct
        })
    
    # 3. 记录次数和时间
    attempts_used = record_attempt_end(user.id)
    attempts_left = MAX_ATTEMPTS - attempts_used
    
    # 4. 准备结果消息 (公屏)
    is_passed = score >= 60
    color = 0x00FF00 if is_passed else 0xFF0000
    
    title_text = "⏰ 答题超时！" if is_timeout else "🎉 答题完成！"
    desc_text = f"{user.mention} 你的二审答题已结束。\n\n**最终成绩：{score}/100分**\n"
    
    view = None
    footer_text = ""

    if is_passed:
        desc_text += "\n✅ **恭喜你通过了测试！** 请等待审核小蛋进行后续操作。"
        footer_text = "恭喜过审！"
    else:
        desc_text += f"\n❌ **未达到60分及格线。**"
        if attempts_left > 0:
            desc_text += f"\n\n你还有 **{attempts_left}** 次机会。\n请仔细复习后，**等待 {RETRY_COOLDOWN} 秒** 点击下方按钮重试。"
            footer_text = f"答题失败 | 剩余机会: {attempts_left}"
            view = QuizRetryView() # 显示重试按钮
        else:
            desc_text += f"\n\n🚫 **你的 {MAX_ATTEMPTS} 次机会已全部用尽。**\n请在工单内联系管理员说明情况。"
            footer_text = "机会用尽"

    public_embed = discord.Embed(title=title_text, description=desc_text, color=color)
    public_embed.set_footer(text=footer_text)

    # 5. 发送公屏消息 
    # 获取频道对象
    target_channel = interface.channel if isinstance(interface, discord.Interaction) else interface
    
    try:
        # 发送新消息到频道，确保大家都能看到
        await target_channel.send(embed=public_embed, view=view)
        
        # 如果是交互(按钮点击)，为了防止按钮一直转圈或保留，简单编辑一下原消息
        if isinstance(interface, discord.Interaction):
            try:
                # 把原来的题目变成简单的结束提示，避免占用版面
                simple_end_embed = discord.Embed(description="✅ 答题已提交，结果已发送至下方。", color=0xcccccc)
                await interface.edit_original_response(embed=simple_end_embed, view=None)
            except: pass
    except Exception as e:
        print(f"发送成绩时出错: {e}")

    # 6. 发送详细成绩单到指定频道 (ID: 1452485785939869808)
    # 获取工单信息
    ticket_info = get_ticket_info_from_channel(target_channel)
    ticket_id = ticket_info.get("工单ID", "未知")
    
    admin_embed = discord.Embed(
        title=f"📊 {user.display_name} 的详细成绩单 {'(超时)' if is_timeout else ''}",
        description=f"**工单号：{ticket_id}**\n**用户：{user.mention} (ID: {user.id})**\n**总分：{score}/100**\n**已用机会：{attempts_used}/{MAX_ATTEMPTS}**\n",
        color=color
    )
    for i, detail in enumerate(details, 1):
        status = "✅" if detail["is_correct"] else "❌"
        admin_embed.add_field(
            name=f"{status} 第{i}题",
            value=f"问: {detail['question'][:20]}...\n答: {detail['user_answer']} | 正: {detail['correct_answer']}",
            inline=False
        )

    # 获取日志频道并发送
    try:
        log_channel = target_channel.guild.get_channel(QUIZ_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(embed=admin_embed)
        else:
            print(f"警告：找不到答题日志频道 ID {QUIZ_LOG_CHANNEL_ID}")
    except Exception as e:
        print(f"发送答题日志失败: {e}")


# ======================================================================================
# --- Cog 类 ---
# ======================================================================================

class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(QuizStartView())
        self.bot.add_view(QuizRetryView()) # 注册重试视图
        print("唷呐！二审答题系统(含重试限制)已成功注册！")
    
    @discord.slash_command(name="setup_quiz", description="（仅限管理员）设置二审答题面板")
    async def setup_quiz(self, ctx: discord.ApplicationContext):
        if not any(role.id == SUPER_EGG_ROLE_ID for role in ctx.author.roles):
            await ctx.respond("你没有权限使用此命令！", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📝 二审自助答题系统",
            description="欢迎来到二审答题环节！\n\n"
                       "**答题说明：**\n"
                       "• 本次测试共10道题，满分100分\n"
                       f"• **每人仅限 {MAX_ATTEMPTS} 次机会**\n"
                       f"• 每次失败需等待 {RETRY_COOLDOWN} 秒冷却\n"
                       "• 答题时限2分钟，超时将自动提交\n\n"
                       "**准备好了就点击下方按钮开始吧！**",
            color=STYLE["KIMI_YELLOW"]
        )
        await ctx.send(embed=embed, view=QuizStartView())
        await ctx.respond("答题面板已发送！", ephemeral=True)
    
    @discord.slash_command(name="reset_quiz", description="（管理员）重置指定用户的答题状态和次数")
    async def reset_quiz(
        self, 
        ctx: discord.ApplicationContext,
        user: discord.Option(discord.Member, description="要重置答题状态的用户", required=True)
    ):
        if not any(role.id == SUPER_EGG_ROLE_ID for role in ctx.author.roles):
            await ctx.respond("你没有权限使用此命令！", ephemeral=True)
            return
        
        user_id = user.id
        msg = []
        
        # 清除进行中的会话
        if user_id in quiz_sessions:
            del quiz_sessions[user_id]
            msg.append("✅ 已中断进行中的答题。")
            
        # 清除历史记录（次数重置）
        if user_id in quiz_history:
            del quiz_history[user_id]
            msg.append(f"✅ 已重置历史次数 (原已用: {MAX_ATTEMPTS}次)。")
        
        if not msg:
            await ctx.respond(f"ℹ️ {user.mention} 当前没有答题记录或进行中的会话。", ephemeral=True)
        else:
            await ctx.respond(f"{user.mention} 操作成功：\n" + "\n".join(msg), ephemeral=True)
    
    @discord.slash_command(name="check_quiz_status", description="（管理员）查看指定用户的答题状态")
    async def check_quiz_status(
        self,
        ctx: discord.ApplicationContext,
        user: discord.Option(discord.Member, description="要查看答题状态的用户", required=True)
    ):
        if not any(role.id == SUPER_EGG_ROLE_ID for role in ctx.author.roles):
            await ctx.respond("你没有权限使用此命令！", ephemeral=True)
            return
        
        user_id = user.id
        embed = discord.Embed(title=f"📊 {user.display_name} 的答题档案", color=STYLE["KIMI_YELLOW"])
        
        # 历史信息
        history = quiz_history.get(user_id, {"count": 0, "last_end_time": None})
        attempts_str = f"{history['count']}/{MAX_ATTEMPTS}"
        last_time_str = history['last_end_time'].strftime("%H:%M:%S") if history['last_end_time'] else "无"
        embed.add_field(name="历史记录", value=f"已用次数: **{attempts_str}**\n上次结束: {last_time_str}", inline=False)
        
        # 进行中状态
        if user_id in quiz_sessions:
            session = quiz_sessions[user_id]
            if session.get("start_time") is None:
                status = "⏳ 准备阶段（已点按钮未开始）"
            else:
                elapsed = (datetime.datetime.utcnow() - session["start_time"]).total_seconds()
                status = f"✍️ 答题中 (第 {session['current_q']+1}/10 题, 耗时 {int(elapsed)}s)"
            embed.add_field(name="当前状态", value=status, inline=False)
        else:
            embed.add_field(name="当前状态", value="⚪ 未在答题中", inline=False)
            
        await ctx.respond(embed=embed, ephemeral=True)

def setup(bot):
    bot.add_cog(Quiz(bot))
