import discord
from discord.ext import commands

from cogs.points.storage import format_shells, modify_user_points
from cogs.shared.utils import is_super_egg

from .storage import claim_reply_reward, find_question_by_message, revoke_reply_reward
from .views import EggQAPanelView, build_panel_embed


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
        if question.get("author_id") == str(message.author.id):
            return

        reward = claim_reply_reward(
            question_id=question["id"],
            user_id=message.author.id,
            reply_message_id=message.id,
        )
        if not reward:
            return

        amount = int(reward["amount"])
        try:
            balance = modify_user_points(
                message.author.id,
                amount,
                message.guild.id,
                source="egg_qa_reply",
                reason=f"question_id={question['id']};reply_message_id={message.id}",
            )
        except Exception as error:
            revoke_reply_reward(
                question_id=question["id"],
                user_id=message.author.id,
                reply_message_id=message.id,
            )
            print(f"[EggQA] reward failed: reply={message.id} error={error}")
            return

        reward_embed = discord.Embed(
            description=(
                f"🥚 **回答彩蛋掉落！** {message.author.mention} 获得了 "
                f"**{amount} 蛋壳**\n当前余额：**{format_shells(balance)} 蛋壳**"
            ),
            color=0xF3B83F,
        )
        try:
            await message.reply(
                embed=reward_embed,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @discord.slash_command(name="小蛋问答面板", description="（仅限超级小蛋）在当前频道发布小蛋问答面板")
    @is_super_egg()
    async def deploy_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        await ctx.channel.send(embed=build_panel_embed(), view=EggQAPanelView())
        await ctx.followup.send("✅ 小蛋问答面板已发送到当前频道。", ephemeral=True)
