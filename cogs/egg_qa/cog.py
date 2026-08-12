import discord
from discord.ext import commands

from cogs.points.storage import modify_user_points
from cogs.shared.utils import is_super_egg

from .storage import claim_reply_reward, find_question_by_message, revoke_reply_reward
from .views import EggQAPanelView, build_panel_embed


REWARD_NUMBER_EMOJIS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
}


def _reward_reactions(amount: int) -> list[str]:
    """用 Discord 数字反应表达 3～15；11～15 表示为 10 加余数。"""
    if amount <= 10:
        emoji = REWARD_NUMBER_EMOJIS.get(amount)
        return [emoji] if emoji else []
    remainder = amount - 10
    return [REWARD_NUMBER_EMOJIS[10], REWARD_NUMBER_EMOJIS[remainder]]


class EggQACog(commands.Cog, name="小蛋问答"):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(EggQAPanelView())
        print("[EggQA] Cog loaded and persistent view registered.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.reference:
            return
        if not message.content.strip() and not message.attachments:
            return

        referenced_id = message.reference.message_id
        if not referenced_id:
            return
        question = find_question_by_message(referenced_id)
        if not question:
            return
        if question.get("guild_id") != str(message.guild.id):
            return
        if question.get("channel_id") != str(message.channel.id):
            return
        is_self_answer = question.get("author_id") == str(message.author.id)

        reward = claim_reply_reward(
            question_id=question["id"],
            user_id=message.author.id,
            reply_message_id=message.id,
            is_self_answer=is_self_answer,
        )
        if not reward:
            return

        amount = int(reward["amount"])
        try:
            modify_user_points(
                message.author.id,
                amount,
                message.guild.id,
                source="egg_qa_self_reply" if is_self_answer else "egg_qa_reply",
                reason=(
                    f"question_id={question['id']};reply_message_id={message.id};"
                    f"self_answer={str(is_self_answer).lower()}"
                ),
            )
        except Exception as error:
            revoke_reply_reward(
                question_id=question["id"],
                user_id=message.author.id,
                reply_message_id=message.id,
            )
            print(f"[EggQA] reward failed: reply={message.id} error={error}")
            return

        for emoji in _reward_reactions(amount):
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                pass

    @discord.slash_command(name="小蛋问答面板", description="（仅限超级小蛋）在当前频道发布小蛋问答面板")
    @is_super_egg()
    async def deploy_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        await ctx.channel.send(embed=build_panel_embed(), view=EggQAPanelView())
        await ctx.followup.send("✅ 小蛋问答面板已发送到当前频道。", ephemeral=True)
