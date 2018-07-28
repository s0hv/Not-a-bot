import textwrap

import discord
from discord.ext.commands import cooldown, BucketType

from bot.bot import command
from cogs.cog import Cog


class Privacy(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(ignore_extra=True)
    @cooldown(1, 5, BucketType.guild)
    async def privacy(self, ctx):
        can_embed = ctx.channel.permissions_for(ctx.guild.get_member(self.bot.user.id)).embed_links

        d = '''
        **Open source**
        This bot is open source meaning it's source code is available to anyone
        who has access to github. Source code can be found {}

        **Data**
        This bot needs to collect data that the discord api provides
        in order to function properly. This data includes but is not limited to
        user ids, usernames, message ids and attachments. If you do not agree
        that the bot collects this data, remove the bot from this guild.

        **Agreement**
        By having this bot in your guild you agree to inform users that
        this bot collects data that the discord api provides in order to function.
        The creator of this bot is not responsible for any damage this bot causes
        including but not limited to failure of a service this bot provides
        
        Currently no support server is made but you can contact s0hvaperuna#4758 `(uid: 123050803752730624)`
        for support.
        '''

        d = textwrap.dedent(d).strip('\n')
        if can_embed:
            d = d.format('[here](https://github.com/s0hvaperuna/Not-a-bot)')
            embed = discord.Embed(title='Privacy statement', description=d)
            await ctx.send(embed=embed)
        else:
            d = d.format('here https://github.com/s0hvaperuna/Not-a-bot')
            await ctx.send(d)


def setup(bot):
    bot.add_cog(Privacy(bot))
