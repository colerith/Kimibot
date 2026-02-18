# cogs/welcome/cog.py

import discord
from discord.ext import commands
import asyncio

from config import IDS, STYLE
from .views import QuizStartView, QuizQuestionView

# --- 配置区 ---
RETRY_COOLDOWN = 900
QUIZ_DURATION = 120
QUIZ_LOG_CHANNEL_ID = IDS.get("QUIZ_LOG_CHANNEL_ID")
PUBLIC_RESULT_CHANNEL_ID = 1452485785939869808

# --- 数据存储 ---
quiz_sessions = {}
quiz_history = {} 

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 将会话和历史记录作为Cog的实例属性，进行统一管理
        self.sessions = {}
        self.history = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # 机器人启动时，注册持久化视图，并传入自身实例
        self.bot.add_view(QuizStartView(self))
        print("[Welcome & Quiz] Cog loaded and views registered.")

    # --- 欢迎新成员 (从 general/core.py 迁移) ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return

        channel_id = 1397629013152894978
        channel = member.guild.get_channel(channel_id) or member.guild.system_channel
        if not channel:
            print(f"无法找到欢迎频道 (ID: {channel_id})")
            return

        quiz_channel_id = IDS.get("QUIZ_CHANNEL_ID", "未知频道")
        ticket_channel_id = IDS.get("TICKET_PANEL_CHANNEL_ID", "未知频道")

        embed = discord.Embed(
            title=f"🎉 欢迎来到 \"🔮LOFI-加载中\" 社区！",
            description=f"你好呀，{member.mention}！\n\n"
                        f"🚪 **第一步：获取基础权限**\n"
                        f"请前往 <#{quiz_channel_id}> 参与答题，答对后即可获得【新兵蛋子】身份。\n\n"
                        f"🔑 **第二步：解锁全区**\n"
                        f"如需访问更多内容，请前往 <#{ticket_channel_id}> 申请人工审核。\n\n"
                        f"祝你玩得开心捏！✨",
            color=STYLE["KIMI_YELLOW"]
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text="记得先看社区守则哦~")

        try:
            await channel.send(content=member.mention, embed=embed)
        except discord.Forbidden:
            print(f"权限不足，无法在频道 {channel.name} 发送欢迎消息。")

    # --- 答题核心逻辑 ---
    def check_cooldown(self, user_id: int):
        """检查用户答题冷却时间"""
        history_time = self.history.get(user_id)
        if not history_time:
            return True, 0
        elapsed = (discord.utils.utcnow() - history_time).total_seconds()
        if elapsed < RETRY_COOLDOWN:
            return False, int(RETRY_COOLDOWN - elapsed)
        return True, 0

    async def timer_task(self, interaction: discord.Interaction, user_id: int):
        """答题超时计时器"""
        try:
            await asyncio.sleep(QUIZ_DURATION)
            if user_id in self.sessions:
                session = self.sessions[user_id]
                elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()
                if elapsed >= QUIZ_DURATION:
                    await self.finalize_quiz(interaction, user_id, is_timeout=True)
        except Exception as e:
            print(f"答题计时任务出错: {e}")

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

        def _send_public_log(self, interaction, user_id, score, passed, is_timeout, details):
            public_channel = self.bot.get_channel(PUBLIC_RESULT_CHANNEL_ID)
            if public_channel:
                status_emoji = "🟢" if passed else "🔴"
                status_text = "**通过**" if passed else "**未通过**"
                public_embed = discord.Embed(
                    description=f"{status_emoji} <@{user_id}>完成了入站答题。\n📊 结果: {status_text} (`{score}`分) {'⏱️(超时)' if is_timeout else ''}",
                    color=0x00FF00 if passed else 0xFF0000
                )
                asyncio.create_task(public_channel.send(embed=public_embed))

            # 内部日志记录
            log_channel = self.bot.get_channel(QUIZ_LOG_CHANNEL_ID)
            if log_channel:
                member = interaction.guild.get_member(user_id)
                user_name = member.display_name if member else f"ID: {user_id}"
                log_embed = discord.Embed(
                    title=f"答题详情: {user_name}",
                    description=f"分数: {score}\n结果: {'通过' if passed else '失败'}\n\n" + "\n".join(details)
                )
                asyncio.create_task(log_channel.send(embed=log_embed))

    # --- 答题管理命令 ---
    @discord.slash_command(name="入站答题面板", description="（管理员）发送入站答题面板")
    @commands.has_role(IDS.get("SUPER_EGG_ROLE_ID")) 
    async def setup_quiz_panel(self, ctx: discord.ApplicationContext):
        channel_id = IDS.get("QUIZ_CHANNEL_ID")
        if not channel_id:
            return await ctx.respond("❌ 未在 config.py 中配置 `QUIZ_CHANNEL_ID`！", ephemeral=True)

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return await ctx.respond(f"❌ 找不到配置的频道 (ID: {channel_id})！", ephemeral=True)

        embed = discord.Embed(
            title="📝 新兵蛋子入站答题",
            description=(
                "欢迎来到 **🔮LOFI-加载中**！\n"
                "为了维护社区环境，请在开始答题前仔细阅读规则。\n\n"
                "**规则说明：**\n"
                "• 共10道题，涉及SillyTavern基础与社区规则\n"
                f"• **限时 {QUIZ_DURATION // 60} 分钟**，60分及格\n"
                f"• **答题失败需等待 {RETRY_COOLDOWN // 60} 分钟冷却**\n"
                "• 通过后自动获得 `新兵蛋子` 身份，解锁部分频道\n\n"
                "**准备好了吗？点击下方按钮开始！**"
            ),
            color=STYLE["KIMI_YELLOW"]
        )
        # 发送面板时，传入自身实例
        await channel.send(embed=embed, view=QuizStartView(self))
        await ctx.respond("✅ 答题面板已成功发送！", ephemeral=True)