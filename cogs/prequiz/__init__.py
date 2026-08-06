from .cog import PreQuizCog


def setup(bot):
    bot.add_cog(PreQuizCog(bot))
