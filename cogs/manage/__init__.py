# cogs/manage/__init__.py

from .moderation_cog import ModerationCog
from .punishment_cog import PunishmentCog

def setup(bot):
    """此函数在加载扩展时由 discord.py 调用"""
    bot.add_cog(ModerationCog(bot))
    bot.add_cog(PunishmentCog(bot))