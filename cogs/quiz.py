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

RETRY_COOLDOWN = 900      # 15分钟冷却 (900秒)
MAX_ATTEMPTS = 999        # 答题次数不限，但有冷却
QUIZ_DURATION = 120       # 2分钟倒计时

# --- 数据存储 ---
quiz_sessions = {}
quiz_history = {} # 记录上次答题时间用于冷却

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
        if newbie_role in interaction.user.roles:
            await interaction.response.send_message("你已经是新兵蛋子啦，不需要再答题咯！要去全区审核请前往审核频道~", ephemeral=True)
            return

        # 2. 检查是否在进行中
        if user_id in quiz_sessions:
            await interaction.response.send_message("你已经在答题中了哦！请继续完成。", ephemeral=True)
            return
        
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
    await asyncio.sleep(QUIZ_DURATION)
    if user_id in quiz_sessions:
        # 超时结算
        await finalize_quiz(interaction, user_id, is_timeout=True)

class QuizQuestionView(discord.ui.View):
    def __init__(self, user_id, q_index):
        super().__init__(timeout=QUIZ_DURATION)
        self.user_id = user_id
        self.q_index = q_index
        
        # 动态添加下拉菜单
        session = quiz_sessions.get(user_id)
        if session:
            question = session["questions"][q_index]
            options = []
            for key, val in question["options"].items():
                options.append(discord.SelectOption(label=f"{key}. {val}", value=key))
            
            select = discord.ui.Select(
                placeholder="请选择一个答案...",
                min_values=1,
                max_values=1, # 虽然你说允许多选，但题目是单选，为了逻辑正确这里限制为1，UI表现仍是下拉菜单
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
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("这不是你的考卷！", ephemeral=True)
        
        selected_val = self.children[0].values[0]
        session = quiz_sessions.get(self.user_id)
        if not session:
            return await interaction.response.send_message("会话已过期", ephemeral=True)
        
        # 记录答案
        session["answers"][self.q_index] = selected_val
        
        # 下一题
        next_index = self.q_index + 1
        if next_index < len(session["questions"]):
            next_q = session["questions"][next_index]
            
            elapsed = (datetime.datetime.utcnow() - session["start_time"]).total_seconds()
            remaining = max(0, QUIZ_DURATION - int(elapsed))
            
            view = QuizQuestionView(self.user_id, next_index)
            embed = view.build_embed(next_index, next_q, remaining)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            # 答完了
            await finalize_quiz(interaction, self.user_id, is_timeout=False)

async def finalize_quiz(interaction, user_id, is_timeout=False):
    if user_id not in quiz_sessions: return
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
            
        # 私信通知
        try:
            dm_embed = discord.Embed(title="🎉 恭喜获得新兵蛋子身份！", description="你已解锁社区基础权限！\n\n如果想查看**酒馆角色卡**等核心资源，请前往 **#申请全区权限** 频道创建工单进行人工审核。", color=STYLE["KIMI_YELLOW"])
            await interaction.user.send(embed=dm_embed)
        except: pass

    else:
        embed.description += f"\n\n❌ **未通过 (需60分)**\n请仔细阅读规则或群公告。\n**请等待 15分钟 后再次尝试。**"

    # 既然是 Interaction，edit 原消息
    try:
        if isinstance(interaction, discord.Interaction):
            # 避免 "Interaction already acknowledged" 错误，如果是超时触发的可能是不同情况
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except:
                await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            # 这里如果是超时任务调用的，interaction 可能是旧的，直接发到频道可能更好，但 ephemeral 限制了
            pass 
    except: pass
    
    # 日志
    log_channel = interaction.guild.get_channel(QUIZ_LOG_CHANNEL_ID)
    if log_channel:
        log_embed = discord.Embed(title=f"答题记录: {interaction.user.display_name}", description=f"分数: {score}\n结果: {'通过' if passed else '失败'}\n\n" + "\n".join(details))
        await log_channel.send(embed=log_embed)

class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(QuizStartView())
        print("Quiz views registered.")

    @discord.slash_command(name="setup_quiz_panel", description="（管理员）发送入站答题面板")
    async def setup_quiz_panel(self, ctx):
        if not ctx.guild.get_role(SUPER_EGG_ROLE_ID) in ctx.author.roles:
            return await ctx.respond("无权操作", ephemeral=True)
        
        channel = ctx.guild.get_channel(IDS["QUIZ_CHANNEL_ID"])
        if not channel:
            return await ctx.respond("找不到答题频道配置", ephemeral=True)

        embed = discord.Embed(
            title="📝 新兵蛋子入站答题",
            description="欢迎来到 **🔮LOFI-加载中**！\n为了防止广告机并确保你了解基础知识，请完成下方答题。\n\n"
                        "**规则说明：**\n"
                        "• 共10道题，涉及SillyTavern基础与社区规则\n"
                        "• **限时 2 分钟**，60分及格\n"
                        "• **答题失败需等待 15 分钟冷却**\n"
                        "• 通过后自动获得 `新兵蛋子` 身份，解锁象牙塔、极光区\n\n"
                        "**准备好了吗？点击下方按钮开始！**",
            color=STYLE["KIMI_YELLOW"]
        )
        await channel.send(embed=embed, view=QuizStartView())
        await ctx.respond("面板已发送", ephemeral=True)

def setup(bot):
    bot.add_cog(Quiz(bot))