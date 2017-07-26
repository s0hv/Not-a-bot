from cogs.cog import Cog
from bot.bot import command


class Admin(Cog):
    def __init__(self, bot):
        super().__init__(bot)


def setup(bot):
    bot.add_cog(Admin(bot))
