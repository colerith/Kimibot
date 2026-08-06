from discord.ext import commands

from .views import PreQuizPanelView


class PreQuizCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(PreQuizPanelView())
        print("[PreQuiz] Cog loaded and persistent view registered.")
