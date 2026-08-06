from .cog import BoostThanksCog


def setup(bot):
    bot.add_cog(BoostThanksCog(bot))
