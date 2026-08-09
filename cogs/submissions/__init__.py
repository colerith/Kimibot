from .cog import SubmissionsCog


def setup(bot):
    bot.add_cog(SubmissionsCog(bot))
