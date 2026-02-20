# cogs/thread_tools/__init__.py

from .cog import ThreadToolsCog

def setup(bot):
    """此函数在加载扩展时由 discord.py 调用。"""
    bot.add_cog(ThreadToolsCog(bot))