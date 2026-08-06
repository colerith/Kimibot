from .cog import RedPacketCog


def setup(bot):
    bot.add_cog(RedPacketCog(bot))
