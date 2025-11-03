import discord
from discord.ext import commands
import asyncio
import random
import datetime
from config import IDS, STYLE
from quiz_data import QUIZ_QUESTIONS

# 二审频道ID（需要配置）
SECOND_REVIEW_CHANNEL_ID = IDS.get("SECOND_REVIEW_CHANNEL_ID", 1419599094988537856)
SUPER_EGG_ROLE_ID = IDS.get("SUPER_EGG_ROLE_ID", 1417724603253395526)

# 答题会话存储 {user_id: {questions, answers, start_time, current_q}}
quiz_sessions = {}

# 准备开始答题的视图
class QuizStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="✅ 我准备好了，开始答题！", style=discord.ButtonStyle.success, custom_id="quiz_start_button")
    async def start_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # 检查是否已经在答题中
        if user_id in quiz_sessions:
            await interaction.response.send_message("你已经在答题中了哦！请先完成当前的答题。", ephemeral=True)
            return
        
        # 随机抽取10道题
        selected_questions = random.sample(QUIZ_QUESTIONS, 10)
        
        # 创建答题会话
        quiz_sessions[user_id] = {
            "questions": selected_questions,
            "answers": {},
            "start_time": None,
            "current_q": 0,
            "channel_id": interaction.channel_id
        }
        
        # 发送问卷说明
        embed = discord.Embed(
            title="📝 二审问卷",
            description=f"{interaction.user.mention} 你好！\n\n"
                       "本次测试共有 **10道题**，满分 **100分**（每题10分）\n\n"
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

# 开始计时的视图
class QuizBeginView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.interaction_ref = None
    
    async def on_timeout(self):
        # 清理未开始的会话
        if self.user_id in quiz_sessions:
            session = quiz_sessions[self.user_id]
            if session.get("start_time") is None:  # 如果还没有开始答题
                del quiz_sessions[self.user_id]
                if self.interaction_ref:
                    try:
                        timeout_embed = discord.Embed(
                            title="⏰ 超时",
                            description="你太久没有开始答题了，会话已过期。\n\n请重新点击\"准备好了\"按钮开始答题。",
                            color=0xFF0000
                        )
                        await self.interaction_ref.edit_original_response(embed=timeout_embed, view=None)
                    except:
                        pass
    
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
        
        # 先defer响应
        await interaction.response.defer()
        
        # 开始计时
        session["start_time"] = datetime.datetime.utcnow()
        
        # 发送第一题
        await self.show_question(interaction, session, 0)
        
        # 启动2分钟倒计时
        asyncio.create_task(self.timer_task(interaction.user, session))
    
    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary, custom_id="quiz_cancel")
    async def cancel_quiz(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这不是你的答题按钮哦！", ephemeral=True)
            return
        
        # 清理会话
        if self.user_id in quiz_sessions:
            del quiz_sessions[self.user_id]
        
        cancel_embed = discord.Embed(
            title="✅ 已取消",
            description="已取消答题，如需重新答题请点击\"准备好了\"按钮。",
            color=STYLE["KIMI_YELLOW"]
        )
        await interaction.response.edit_message(embed=cancel_embed, view=None)
    
    async def show_question(self, interaction, session, q_index):
        if q_index >= len(session["questions"]):
            # 答题结束
            await self.finish_quiz(interaction, session)
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
        
        # 始终使用edit_original_response（因为我们已经defer了）
        await interaction.edit_original_response(embed=embed, view=view)
    
    async def finish_quiz(self, interaction, session):
        # 计算分数
        score = 0
        details = []
        
        for i, question in enumerate(session["questions"]):
            user_answer = session["answers"].get(i, "未作答")
            correct = user_answer == question["answer"]
            if correct:
                score += 10
            
            details.append({
                "question": question["question"],
                "user_answer": user_answer,
                "correct_answer": question["answer"],
                "is_correct": correct
            })
        
        # 删除会话
        del quiz_sessions[self.user_id]
        
        # 发送成绩单
        await self.show_results(interaction, score, details)
    
    async def show_results(self, interaction, score, details):
        user = interaction.user
        
        # 从频道topic获取工单信息
        channel = interaction.channel
        ticket_info = self.get_ticket_info(channel)
        ticket_id = ticket_info.get("工单ID", "未知")
        reviewer_id = ticket_info.get("ReviewerID")
        
        # 公屏成绩单
        public_embed = discord.Embed(
            title="🎉 答题完成！",
            description=f"{user.mention} 完成了二审答题！\n\n**最终成绩：{score}/100分**",
            color=0x00FF00 if score >= 60 else 0xFF0000
        )
        
        # 管理员详细成绩单
        admin_embed = discord.Embed(
            title=f"📊 {user.display_name} 的详细成绩单",
            description=f"**工单号：{ticket_id}**\n**总分：{score}/100分**\n**正确率：{score}%**\n",
            color=0x00FF00 if score >= 60 else 0xFF0000
        )
        
        for i, detail in enumerate(details, 1):
            status = "✅" if detail["is_correct"] else "❌"
            admin_embed.add_field(
                name=f"{status} 第{i}题：{detail['question'][:30]}...",
                value=f"你的答案：{detail['user_answer']} | 正确答案：{detail['correct_answer']}",
                inline=False
            )
        
        # 发送公屏消息
        await interaction.channel.send(embed=public_embed)
        
        # 只给当前审核员发送详细成绩单
        if reviewer_id:
            try:
                reviewer = await interaction.guild.fetch_member(int(reviewer_id))
                if reviewer:
                    try:
                        await reviewer.send(embed=admin_embed)
                    except discord.Forbidden:
                        # 如果无法私信审核员，就在频道发送提示
                        await channel.send(f"{reviewer.mention} 详细成绩单已生成，但无法私信你！请检查私信设置。", delete_after=10)
            except:
                # 找不到审核员，发送给所有超级小蛋（备用方案）
                pass
        
        # 更新用户的消息
        result_embed = discord.Embed(
            title="✅ 答题结束",
            description=f"你的成绩：**{score}/100分**\n\n成绩已公布在频道中！",
            color=0x00FF00 if score >= 60 else 0xFF0000
        )
        await interaction.edit_original_response(embed=result_embed, view=None)
    
    def get_ticket_info(self, channel):
        """从频道topic中解析工单信息"""
        info = {}
        if not channel.topic:
            return info
        try:
            parts = channel.topic.split(" | ")
            for part in parts:
                if ": " in part:
                    key, value = part.split(": ", 1)
                    info[key] = value
        except:
            pass
        return info
    
    async def timer_task(self, user, session):
        await asyncio.sleep(120)
        
        # 时间到，自动提交
        if user.id in quiz_sessions:
            # 找到用户的交互
            channel = user.guild.get_channel(session["channel_id"]) if session.get("channel_id") else None
            if channel:
                try:
                    # 计算分数并显示
                    score = 0
                    details = []
                    
                    for i, question in enumerate(session["questions"]):
                        user_answer = session["answers"].get(i, "未作答")
                        correct = user_answer == question["answer"]
                        if correct:
                            score += 10
                        
                        details.append({
                            "question": question["question"],
                            "user_answer": user_answer,
                            "correct_answer": question["answer"],
                            "is_correct": correct
                        })
                    
                    del quiz_sessions[user.id]
                    
                    # 从频道topic获取工单信息（使用独立函数）
                    ticket_info = {}
                    if channel.topic:
                        try:
                            parts = channel.topic.split(" | ")
                            for part in parts:
                                if ": " in part:
                                    key, value = part.split(": ", 1)
                                    ticket_info[key] = value
                        except:
                            pass
                    ticket_id = ticket_info.get("工单ID", "未知")
                    reviewer_id = ticket_info.get("ReviewerID")
                    
                    # 发送超时成绩单
                    timeout_embed = discord.Embed(
                        title="⏰ 时间到！",
                        description=f"{user.mention} 的答题时间已到！\n\n**最终成绩：{score}/100分**",
                        color=0xFFA500
                    )
                    await channel.send(embed=timeout_embed)
                    
                    # 给审核员发送详细信息
                    admin_embed = discord.Embed(
                        title=f"📊 {user.display_name} 的详细成绩单（超时）",
                        description=f"**工单号：{ticket_id}**\n**总分：{score}/100分**\n**正确率：{score}%**\n",
                        color=0xFFA500
                    )
                    
                    for i, detail in enumerate(details, 1):
                        status = "✅" if detail["is_correct"] else "❌"
                        admin_embed.add_field(
                            name=f"{status} 第{i}题：{detail['question'][:30]}...",
                            value=f"答案：{detail['user_answer']} | 正确：{detail['correct_answer']}",
                            inline=False
                        )
                    
                    # 只给当前审核员发送详细成绩单
                    if reviewer_id:
                        try:
                            reviewer = await user.guild.fetch_member(int(reviewer_id))
                            if reviewer:
                                try:
                                    await reviewer.send(embed=admin_embed)
                                except discord.Forbidden:
                                    await channel.send(f"{reviewer.mention} 详细成绩单已生成，但无法私信你！请检查私信设置。", delete_after=10)
                        except:
                            pass
                except:
                    pass

# 答题选择视图
class QuizAnswerView(discord.ui.View):
    def __init__(self, user_id, q_index, options):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.q_index = q_index
        
        # 动态添加选项按钮
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
            
            # 先defer响应
            await interaction.response.defer()
            
            # 记录答案
            session["answers"][self.q_index] = option
            
            # 显示下一题
            next_q = self.q_index + 1
            if next_q < len(session["questions"]):
                await QuizBeginView(self.user_id).show_question(interaction, session, next_q)
            else:
                # 答题完成
                await QuizBeginView(self.user_id).finish_quiz(interaction, session)
        
        return callback

# Cog主类
class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(QuizStartView())
        print("唷呐！二审答题系统已成功注册！")
    
    @discord.slash_command(name="setup_quiz", description="（仅限管理员）设置二审答题面板")
    async def setup_quiz(self, ctx: discord.ApplicationContext):
        # 检查权限
        if not any(role.id == SUPER_EGG_ROLE_ID for role in ctx.author.roles):
            await ctx.respond("你没有权限使用此命令！", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📝 二审自助答题系统",
            description="欢迎来到二审答题环节！\n\n"
                       "**答题说明：**\n"
                       "• 本次测试共10道题，满分100分\n"
                       "• 题库共20道题，每次随机抽取10道\n"
                       "• 答题时限2分钟，逐题显示\n"
                       "• 答题过程中不会告知对错\n"
                       "• 答题结束后公布成绩\n\n"
                       "**准备好了就点击下方按钮开始吧！**",
            color=STYLE["KIMI_YELLOW"]
        )
        
        await ctx.send(embed=embed, view=QuizStartView())
        await ctx.respond("答题面板已发送！", ephemeral=True)
    
    @discord.slash_command(name="reset_quiz", description="（管理员）重置指定用户的答题状态")
    async def reset_quiz(
        self, 
        ctx: discord.ApplicationContext,
        user: discord.Option(discord.Member, description="要重置答题状态的用户", required=True)
    ):
        # 检查权限
        if not any(role.id == SUPER_EGG_ROLE_ID for role in ctx.author.roles):
            await ctx.respond("你没有权限使用此命令！", ephemeral=True)
            return
        
        user_id = user.id
        
        # 检查用户是否有答题会话
        if user_id in quiz_sessions:
            # 删除会话
            del quiz_sessions[user_id]
            await ctx.respond(f"✅ 已成功重置 {user.mention} 的答题状态！他们现在可以重新开始答题了。", ephemeral=True)
        else:
            await ctx.respond(f"ℹ️ {user.mention} 当前没有进行中的答题会话。", ephemeral=True)
    
    @discord.slash_command(name="check_quiz_status", description="（管理员）查看指定用户的答题状态")
    async def check_quiz_status(
        self,
        ctx: discord.ApplicationContext,
        user: discord.Option(discord.Member, description="要查看答题状态的用户", required=True)
    ):
        # 检查权限
        if not any(role.id == SUPER_EGG_ROLE_ID for role in ctx.author.roles):
            await ctx.respond("你没有权限使用此命令！", ephemeral=True)
            return
        
        user_id = user.id
        
        # 检查用户是否有答题会话
        if user_id in quiz_sessions:
            session = quiz_sessions[user_id]
            
            # 构建状态信息
            embed = discord.Embed(
                title=f"📊 {user.display_name} 的答题状态",
                color=STYLE["KIMI_YELLOW"]
            )
            
            # 判断答题阶段
            if session.get("start_time") is None:
                status = "⏳ 准备阶段（尚未开始答题）"
                progress = "等待点击【开始答题】按钮"
            else:
                current_q = session.get("current_q", 0)
                total_q = len(session["questions"])
                answered = len(session.get("answers", {}))
                
                status = f"✍️ 答题中"
                progress = f"已回答 {answered}/{total_q} 题"
                
                # 计算剩余时间
                start_time = session.get("start_time")
                if start_time:
                    elapsed = (datetime.datetime.now() - start_time).total_seconds()
                    remaining = max(0, 120 - elapsed)
                    progress += f"\n⏱️ 剩余时间：{int(remaining)}秒"
            
            embed.add_field(name="状态", value=status, inline=False)
            embed.add_field(name="进度", value=progress, inline=False)
            embed.add_field(name="答题频道", value=f"<#{session.get('channel_id', '未知')}>", inline=False)
            embed.set_footer(text="使用 /reset_quiz 可重置该用户的答题状态")
            
            await ctx.respond(embed=embed, ephemeral=True)
        else:
            await ctx.respond(f"ℹ️ {user.mention} 当前没有进行中的答题会话。", ephemeral=True)

def setup(bot):
    bot.add_cog(Quiz(bot))
