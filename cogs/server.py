from bot.bot import command
from cogs.cog import Cog
from discord.ext.commands import cooldown


class Server(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(no_pm=True, pass_context=True)
    @cooldown(1, 20)
    async def top(self, ctx):
        server = ctx.message.server

        sorted_users = sorted(server.members, key=lambda u: len(u.roles), reverse=True)

        s = 'Leaderboards for **%s**\n\n```md\n' % server.name

        for idx, u in enumerate(sorted_users[:10]):
            s += '{}. {} with {} roles\n'.format(idx + 1, u, len(u.roles) - 1)

        s += '```'

        await self.bot.say(s)


def setup(bot):
    bot.add_cog(Server(bot))
