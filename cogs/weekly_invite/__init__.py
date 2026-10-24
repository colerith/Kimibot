def setup(bot):
    from .cog import WeeklyInviteCog
    bot.add_cog(WeeklyInviteCog(bot))
