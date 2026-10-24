def setup(bot):
    from .cog import PromotionCog
    bot.add_cog(PromotionCog(bot))
