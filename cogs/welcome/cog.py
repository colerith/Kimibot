# cogs/welcome/cog.py

import discord
from discord.ext import commands
import asyncio
import random

from config import IDS, STYLE
from .data import QUIZ_QUESTIONS
from .views import QuizStartView

# --- 配置区 ---
RETRY_COOLDOWN = 900
QUIZ_DURATION = 120
QUIZ_LOG_CHANNEL_ID = IDS.get("QUIZ_LOG_CHANNEL_ID")
PUBLIC_RESULT_CHANNEL_ID = 1452485785939869808

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ✨ 修改点：将会话和历史记录作为Cog的实例属性，进行统一管理
        self.sessions = {}
        self.history = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # ✨ 修改点：注册持久化视图时，将 Cog 自身实例传入
        self.bot.add_view(QuizStartView(self))
        print("[Welcome & Quiz] Cog loaded and views registered.")

    # --- 欢迎新成员 (保持不变) ---
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
                    # 使用 self 调用方法
                    await self.finalize_quiz(interaction, user_id, is_timeout=True)
        except Exception as e:
            print(f"答题计时任务出错: {e}")

    async def finalize_quiz(self, interaction: discord.Interaction, user_id: int, is_timeout: bool = False):
        """结算答题结果的核心函数"""
        if user_id not in self.sessions:
            return

        session = self.sessions.pop(user_id)
        self.history[user_id] = discord.utils.utcnow()

        score = 0
        details = []
        for i, q in enumerate(session["questions"]):
            ans = session["answers"].get(i)
            is_correct = (ans == q["answer"])
            if is_correct: score += 10
            details.append(f"Q{i+1}: {'✅' if is_correct else '❌'} (选{ans or '未答'}/对{q['answer']})")

        passed = score >= 60
        title_prefix = "⏱️ 答题超时" if is_timeout else "📝 答题结束"

        embed = discord.Embed(
            title=title_prefix,
            description=f"**最终得分: {score}/100**",
            color=0x00FF00 if passed else 0xFF0000
        )

        if passed:
            embed.description += "\n\n🎉 **恭喜通过！**\n✅ 已自动获得【新兵蛋子】身份组，并解锁部分频道。"
            role = interaction.guild.get_role(IDS["VERIFICATION_ROLE_ID"])
            if role:
                try:
                    member = interaction.guild.get_member(user_id) or await interaction.guild.fetch_member(user_id)
                    await member.add_roles(role, reason="自助答题通过")
                except Exception as e:
                    print(f"为用户 {user_id} 添加身份组失败: {e}")
        else:
            embed.description += f"\n\n❌ **未通过 (需60分)**\n请仔细阅读规则或群公告。\n你可以在 **{RETRY_COOLDOWN // 60}分钟** 后再次尝试。"

        # --- 核心修改部分 ---
        try:
            # 如果是超时，交互对象很旧，只能用 followup 发送新消息
            if is_timeout:
                await interaction.followup.send(embed=embed, ephemeral=True)
            # 如果是正常答完，交互对象是新鲜的，直接编辑当前消息
            else:
                await interaction.response.edit_message(embed=embed, view=None)

        # 备用方案：如果编辑失败（例如用户关闭了窗口），尝试用followup发送
        except discord.NotFound:
            try:
                await interaction.followup.send(content="答题会话已结束。", embed=embed, ephemeral=True)
            except Exception as final_e:
                print(f"最终发送答题结果失败: {final_e}")
        except Exception as e:
            print(f"发送答题结果时发生未知错误: {e}")
            try:
                await interaction.followup.send(content="处理结果时发生错误。", embed=embed, ephemeral=True)
            except Exception as final_e:
                print(f"最终发送答题结果失败: {final_e}")
        # --- 修改结束 ---

        # 发送日志的逻辑保持不变
        self._send_public_log(interaction, user_id, score, passed, is_timeout, details)

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

        log_channel = self.bot.get_channel(QUIZ_LOG_CHANNEL_ID)
        if log_channel:
            member = interaction.guild.get_member(user_id)
            user_name = member.display_name if member else f"ID: {user_id}"
            log_embed = discord.Embed(
                title=f"答题详情: {user_name}",
                description=f"分数: {score}\n结果: {'通过' if passed else '失败'}\n\n" + "\n".join(details)
            )
            asyncio.create_task(log_channel.send(embed=log_embed))

    # --- 答题管理命令 (保持不变) ---
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
                "• 账号需注册满30天，且不为可疑账号\n"
                "• 通过后自动获得 `新兵蛋子` 身份，解锁部分频道\n\n"
                "**准备好了吗？点击下方按钮开始！**"
            ),
            color=STYLE["KIMI_YELLOW"]
        )
        # ✨ 修改点：发送面板时，将 Cog 自身实例传入
        await channel.send(embed=embed, view=QuizStartView(self))
        await ctx.respond("✅ 答题面板已成功发送！", ephemeral=True)
