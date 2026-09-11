from .core import Tickets
from .qq_bridge import setup_bridge

def setup(bot):
    bot.add_cog(Tickets(bot))
    setup_bridge(bot)
