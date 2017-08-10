from bot.bot import command
from cogs.cog import Cog
from discord.ext.commands import cooldown


class Server(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(no_pm=True, pass_context=True)
    @cooldown(1, 20)
    async def top(self, ctx, page: str='1'):
        try:
            page = int(page)
            if page <= 0:
                page = 1
        except:
            page = 1

        server = ctx.message.server

        sorted_users = sorted(server.members, key=lambda u: len(u.roles), reverse=True)

        s = 'Leaderboards for **%s**\n\n```md\n' % server.name

        added = 0
        p = page*10
        for idx, u in enumerate(sorted_users[p-10:p]):
            added += 1
            s += '{}. {} with {} roles\n'.format(idx + p-10, u, len(u.roles) - 1)

        if added == 0:
            return await self.bot.say('Page out of range')
        s += '```'

        await self.bot.say(s)


def setup(bot):
    bot.add_cog(Server(bot))
