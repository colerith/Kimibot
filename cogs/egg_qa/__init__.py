from .cog import EggQACog


def setup(bot):
    bot.add_cog(EggQACog(bot))
