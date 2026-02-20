# cogs/welcome/__init__.py

from .cog import WelcomeCog

def setup(bot):
    """此函数由 discord.py 在加载扩展时调用"""
    bot.add_cog(WelcomeCog(bot))