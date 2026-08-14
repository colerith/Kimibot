from discord.ext import commands

from .views import (
    OwnerReplyView,
    RecommendationActionView,
    SubmissionPanelView,
    refresh_all_submission_panels,
    refresh_submission_main_panel,
)


class SubmissionsCog(commands.Cog):
    """奇米蛋投稿面板。"""

    def __init__(self, bot):
        self.bot = bot
        self.submission_panels_refreshed = False

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(SubmissionPanelView())
        self.bot.add_view(OwnerReplyView())
        self.bot.add_view(RecommendationActionView())
        print("[Submissions] Cog loaded and persistent views registered.")
        self.bot.loop.create_task(self._refresh_submission_panels_on_ready())

    async def _refresh_submission_panels_on_ready(self):
        if self.submission_panels_refreshed:
            return
        self.submission_panels_refreshed = True
        await self.bot.wait_until_ready()
        try:
            main_panel_refreshed = await refresh_submission_main_panel(self.bot)
            result = await refresh_all_submission_panels(self.bot)
            print(
                f"[Submissions] main panel refreshed={main_panel_refreshed}; "
                f"refreshed {result['refreshed']} submission panels, skipped={result['skipped']}."
            )
        except Exception as e:
            print(f"[Submissions] submission-panel-refresh-failed: {e}")
