import logging

from discord import ApplicationContext
from discord.ext.commands import Cog

from bot.bot import Context

logger = logging.getLogger('terminal')


class BasicLogging(Cog):
    def __init__(self, bot):
        self.bot = bot

    @Cog.listener()
    async def on_application_command(self, ctx: ApplicationContext):
        cmd_name = ctx.interaction.qualified_name()
        if ctx.guild:
            s = '{0.name}/{0.id}/{1.name}/{1.id} {2.id} called {3}'.format(
                ctx.guild, ctx.channel, ctx.author, cmd_name)
        else:
            s = 'DM/{0.id} called {1}'.format(ctx.author, cmd_name)
        logger.info(s)

    @Cog.listener()
    async def on_command(self, ctx: Context):
        if ctx.guild:
            s = '{0.name}/{0.id}/{1.name}/{1.id} {2.id} called {3}'.format(
                ctx.guild, ctx.channel, ctx.author, ctx.command.qualified_name)
        else:
            s = 'DM/{0.id} called {1}'.format(ctx.author, ctx.command.qualified_name)
        logger.info(s)


def setup(bot):
    bot.add_cog(BasicLogging(bot))
