# cogs/welcome/cog.py

import discord
from discord.ext import commands, tasks
import asyncio
import random

from config import IDS, STYLE, MANUAL_REVIEW_ENABLED
from .data import QUIZ_QUESTIONS
from .views import QuizStartView

# --- 配置区 ---
RETRY_COOLDOWN = 900
from .quiz_logic import QUIZ_DURATION, is_correct as answer_is_correct, expected_answers
QUIZ_SETTLEMENT_GRACE = 10
QUIZ_LOG_CHANNEL_ID = IDS.get("QUIZ_LOG_CHANNEL_ID")
PUBLIC_RESULT_CHANNEL_ID = 1452485785939869808
MANUAL_REVIEW_URL = "https://discord.com/channels/1397629012292931726/1417572579304013885"


def build_newbie_approved_dm(member: discord.Member, guild: discord.Guild, score: int) -> discord.Embed:
    """Build the private welcome card sent after the entrance quiz passes."""
    embed = discord.Embed(
        title="🐣 欢迎成为新兵蛋子！",
        description=(
            f"嗨，**{member.display_name}**！你已经顺利通过 **{guild.name}** 的入站答题。\n"
            "【新兵蛋子】身份已发放，基础社区权限现已解锁啦 ✨"
        ),
        color=STYLE.get("KIMI_YELLOW", 0xF7C873),
    )
    embed.add_field(
        name="🎉 本次答题",
        value=f"最终得分：**{score}/100**\n身份状态：✅ 已通过并发放",
        inline=False,
    )
    if MANUAL_REVIEW_ENABLED:
        embed.add_field(
            name="🔓 想解锁更多内容？（可选）",
            value=(
                "人工审核是用于申请更多社区权限的**自愿选项，并不是必须步骤**。\n"
                "不参加人工审核也不会影响你已经获得的【新兵蛋子】身份和现有权限。\n\n"
                f"如果之后有需要，可以前往 [人工审核入口]({MANUAL_REVIEW_URL}) 查看说明。"
            ),
            inline=False,
        )
    embed.add_field(
        name="💛 温馨提醒",
        value="记得阅读频道说明和社区守则；慢慢逛、开心玩就好～",
        inline=False,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=("人工审核完全自愿 · 不申请不会影响当前的新兵蛋子身份"
                           if MANUAL_REVIEW_ENABLED else "欢迎加入社区 · 祝你玩得开心"))
    return embed


def build_manual_review_link_view() -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label="前往人工审核入口（可选）",
            emoji="🔎",
            style=discord.ButtonStyle.link,
            url=MANUAL_REVIEW_URL,
        )
    )
    return view

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ✨ 修改点：将会话和历史记录作为Cog的实例属性，进行统一管理
        self.sessions = {}
        self.history = {}
        self.quiz_panel_lock = asyncio.Lock()
        self.quiz_view_registered = False

    @commands.Cog.listener()
    async def on_ready(self):
        # ✨ 修改点：注册持久化视图时，将 Cog 自身实例传入
        if not self.quiz_view_registered:
            self.bot.add_view(QuizStartView(self))
            self.quiz_view_registered = True
        if not self.quiz_panel_refresh.is_running():
            self.quiz_panel_refresh.start()
        print("[Welcome & Quiz] Cog loaded and views registered.")

    @tasks.loop(minutes=10)
    async def quiz_panel_refresh(self):
        try:
            await self.deploy_quiz_panel()
        except Exception as error:
            print(f"[Welcome] 答题入口刷新失败，将重试: {error!r}")

    @quiz_panel_refresh.before_loop
    async def before_quiz_panel_refresh(self):
        await self.bot.wait_until_ready()

    def cog_unload(self):
        self.quiz_panel_refresh.cancel()

    # --- 欢迎新成员与入门指引 ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return
        channel_id = 1397629013152894978
        channel = member.guild.get_channel(channel_id) or member.guild.system_channel
        if not channel:
            print(f"无法找到欢迎频道 (ID: {channel_id})")
            return
        embed = discord.Embed(
            title=f"🎉 欢迎来到 \"🔮LOFI-加载中\" 社区！",
            description=f"你好呀，{member.mention}！\n\n"
                        "💡 **新蛋入门指引**\n"
                        "• **先读规则：**请仔细阅读 <#1417568378889175071>。\n"
                        "• **答题领身份：**[前往答题](https://discord.com/channels/1397629012292931726/1467034060026286090/1499984826931871808)，通过后获得【新兵蛋子】身份，即可下载预设。账号注册满30天可立即答题，未满30天需按注册时间等待缓冲期。\n"
                        "• **安心等待：**缓冲期内只要遵守社区规则，不会因暂时无法答题被清理。\n"
                        "• **蛋壳加速：**积攒蛋壳可兑换加速卡，缩短缓冲期。获取方式见 <#1468483568601927921> 的【使用帮助】；[参与预答题](https://discord.com/channels/1397629012292931726/1417568378889175071/1541643432202608781)可直接获得 **5个蛋壳**。\n"
                        "• **使用预设前：**请认真阅读 <#1536381368580178002> 和 <#1536941892288127016>。\n\n"
                        f"祝你玩得开心捏！✨",
            color=STYLE["KIMI_YELLOW"]
        )
        embed.set_thumbnail(url=member.display_avatar.url)
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
        from .attempts import day_key
        if day_key(history_time) != day_key():
            return True, 0
        elapsed = (discord.utils.utcnow() - history_time).total_seconds()
        if elapsed < RETRY_COOLDOWN:
            return False, int(RETRY_COOLDOWN - elapsed)
        return True, 0

    async def timer_task(self, interaction: discord.Interaction, user_id: int, expected_session=None):
        """答题超时计时器"""
        try:
            # Leave a small settlement window for a selection that Discord has
            # delivered near the deadline while the bot/API is briefly busy.
            await asyncio.sleep(QUIZ_DURATION + QUIZ_SETTLEMENT_GRACE)
            if user_id in self.sessions:
                session = self.sessions[user_id]
                elapsed = (discord.utils.utcnow() - session["start_time"]).total_seconds()
                if (expected_session is None or session is expected_session) and elapsed >= QUIZ_DURATION:
                    # 使用 self 调用方法
                    await self.finalize_quiz(interaction, user_id, is_timeout=True)
        except Exception as e:
            print(f"答题计时任务出错: {e}")

    async def finalize_quiz(self, interaction: discord.Interaction, user_id: int, is_timeout: bool = False):
        """结算答题结果的核心函数"""
        if user_id not in self.sessions:
            return

        session = self.sessions.pop(user_id)
        test_mode = bool(session.get("test_mode"))
        if not test_mode:
            self.history[user_id] = discord.utils.utcnow()

        correct_count = 0
        details = []
        for i, q in enumerate(session["questions"]):
            ans = session["answers"].get(i)
            is_correct = answer_is_correct(q, ans)
            if is_correct: correct_count += 1
            selected_text = "、".join(ans) if isinstance(ans, list) else (ans or "未答")
            correct_text = "、".join(sorted(expected_answers(q)))
            details.append(f"Q{i+1}: {'✅' if is_correct else '❌'} (选{selected_text}/对{correct_text})")

        passed = correct_count * 100 >= len(session["questions"]) * 60
        score = round(correct_count * 100 / len(session["questions"]), 1)
        title_prefix = "⏱️ 答题超时" if is_timeout else "📝 答题结束"

        embed = discord.Embed(
            title=title_prefix,
            description=f"**最终得分: {score}/100**",
            color=0x00FF00 if passed else 0xFF0000
        )

        approved_member = None
        if test_mode:
            embed.title = "🧪 测试模式 · " + title_prefix
            embed.description += f"\n\n{'✅ 测试通过' if passed else '❌ 测试未通过（需60分）'}\n不变更身份、不发送准入私信、不计入正式记录；可立即重新测试。"
            embed.add_field(name="逐题核对", value="\n".join(details), inline=False)
        elif passed:
            try:
                from cogs.shared.admission_restore import restore
                member = await interaction.guild.fetch_member(user_id)
                restored_role = await restore(member)
                embed.description += f"\n\n🎉 **恭喜通过！**\n✅ 已恢复／获得【{restored_role.name}】身份组。"
                approved_member = member
            except Exception as e:
                embed.description += "\n\n答题已通过，但身份恢复失败，请联系管理员或稍后重新答题；原身份记录已保留。"
                print(f"为用户 {user_id} 恢复身份组失败: {e}")
        else:
            from .attempts import used_today
            daily_used = await asyncio.to_thread(used_today, interaction.guild.id, user_id)
            retry_text = ("今日 3 次答题机会已用完，请等待北京时间次日 00:00 刷新。"
                          if daily_used >= 3 else
                          f"今日剩余 {3-daily_used} 次；冷却 {RETRY_COOLDOWN // 60} 分钟后可重试。")
            embed.description += f"\n\n❌ **未通过 (需60分，15题答对9题)**\n请仔细阅读规则或群公告。\n{retry_text}"

        from .attempts import quota_text
        quota_notice = await asyncio.to_thread(quota_text, interaction.guild.id, user_id, test_mode=test_mode)
        embed.add_field(name="今日答题次数", value=quota_notice, inline=False)

        # --- 核心修改部分 ---
        try:
            # 如果是超时，交互对象很旧，只能用 followup 发送新消息
            if is_timeout:
                await interaction.followup.send(embed=embed, ephemeral=True)
            # 选择题回调会先 defer，因此正常答完时编辑原消息。
            else:
                if interaction.response.is_done():
                    await interaction.edit_original_response(embed=embed, view=None)
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

        # 先完成答题交互，再发送私信，避免私信接口延迟影响结果页面。
        if passed and approved_member:
            try:
                dm_embed = build_newbie_approved_dm(approved_member, interaction.guild, score)
                if restored_role.id == int(IDS['HATCHED_ROLE_ID']):
                    dm_embed = discord.Embed(title="🐣 答题通过，身份已恢复", description="已恢复【破壳而出】身份，欢迎回到社区！", color=0x9BBE9D)
                await approved_member.send(
                    embed=dm_embed,
                    view=build_manual_review_link_view() if MANUAL_REVIEW_ENABLED else None,
                )
            except discord.Forbidden:
                print(f"无法发送新兵蛋子通过私信: user={user_id} reason=dm_closed")
            except discord.HTTPException as error:
                print(f"发送新兵蛋子通过私信失败: user={user_id} error={error!r}")

        # 发送日志的逻辑保持不变
        if not test_mode:
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

    async def deploy_quiz_panel(self) -> tuple[bool, str]:
        async with self.quiz_panel_lock:
            return await self._sync_quiz_panel()

    async def _sync_quiz_panel(self) -> tuple[bool, str]:
        """供 /社区面板 管理 统一调用。"""
        channel_id = IDS.get("QUIZ_CHANNEL_ID")
        if not channel_id:
            return False, "未在 config.py 中配置 QUIZ_CHANNEL_ID"
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not channel:
            return False, f"找不到配置的频道（ID: {channel_id}）"
        embed = discord.Embed(
            title="📝 新兵蛋子入站答题",
            description=(
                "欢迎来到 **🔮LOFI-加载中**！\n"
                "为了维护社区环境，请在开始答题前仔细阅读规则。\n\n"
                "**规则说明：**\n"
                "• 共15道题，涉及SillyTavern基础与社区规则\n"
                f"• **限时 {QUIZ_DURATION // 60} 分钟**，60分及格（答对9题）\n"
                "• 12 道单选 + 3 道多选；多选需确认，选全才得分\n"
                "• 每人每天最多 3 次，北京时间 00:00 刷新；开考即计次\n"
                f"• **答题失败需等待 {RETRY_COOLDOWN // 60} 分钟冷却**\n"
                "• 账号需注册满30天，且不为可疑账号\n"
                "• 首次通过发放新兵蛋子；处罚后重答恢复记录中的原身份\n"
                "• 点击【查看今日次数】查看个人剩余次数\n\n"
                "**准备好了吗？点击下方按钮开始！**"
            ),
            color=STYLE["KIMI_YELLOW"]
        )
        from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace
        key = f"welcome_quiz_panel:{channel_id}"
        state = await asyncio.to_thread(load_json_namespace, key, legacy_file=None, default={})
        candidates = []
        # Preserve the long-lived linked entrance instead of publishing another card.
        ids = set(state.get("message_ids", [])) | {1499984826931871808}
        for message_id in ids:
            try:
                message = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                continue
            if message.author.id == self.bot.user.id:
                candidates.append(message)
        if not state.get("discovered"):
            async for message in channel.history(limit=200):
                if (message.author.id == self.bot.user.id and
                    any(e.title == "📝 新兵蛋子入站答题" for e in message.embeds) and
                    message.id not in {m.id for m in candidates}):
                    candidates.append(message)
        if not candidates:
            candidates.append(await channel.send(embed=embed, view=QuizStartView(self)))
        else:
            for message in candidates:
                component_ids = {getattr(child, "custom_id", None) for row in message.components for child in row.children}
                if (not message.embeds or message.embeds[0].to_dict() != embed.to_dict() or
                    "quiz_entry_quota" not in component_ids):
                    await message.edit(embed=embed, view=QuizStartView(self))
                    await asyncio.sleep(1)
        await asyncio.to_thread(save_json_namespace, key,
                                {"message_ids": [m.id for m in candidates], "discovered": True})
        return True, "✅ 入站答题入口已更新，后续会自动同步文案。"
