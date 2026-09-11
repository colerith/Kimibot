from .core import EntertainmentCog


def setup(bot):
    bot.add_cog(EntertainmentCog(bot))
