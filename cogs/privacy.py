import textwrap

import discord
from discord.ext.commands import BucketType

from bot.bot import command, cooldown
from cogs.cog import Cog


class Privacy(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command()
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
        
        You can get the support server invite with a command name `support` or use the command `feedback` if you want 
        support or your data removed. This will not however stop the collection
        of data so you need to leave or remove the bot from any servers you're in.
        This does not however mean that data used exclusively for moderation will be removed.
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
