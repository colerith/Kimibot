# cogs/manage/__init__.py

from .moderation_cog import ModerationCog
from .punishment_cog import PunishmentCog
from .blocker_cog import ScamBlockerCog
from .complaint_cog import ComplaintCog
from .daily_report_cog import ServerDailyReportCog

def setup(bot):
    """此函数在加载扩展时由 discord.py 调用"""
    bot.add_cog(ModerationCog(bot))
    bot.add_cog(PunishmentCog(bot))
    bot.add_cog(ScamBlockerCog(bot))
    bot.add_cog(ComplaintCog(bot))
    bot.add_cog(ServerDailyReportCog(bot))
