import textwrap

import discord
from discord.ext.commands import BucketType

from bot.bot import command, cooldown, Context
from cogs.cog import Cog
from utils.utilities import wait_for_words


class Privacy(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command()
    @cooldown(1, 5, BucketType.guild)
    async def privacy(self, ctx):
        can_embed = ctx.channel.permissions_for(ctx.guild.get_member(self.bot.user.id)).embed_links

        d = '''
        **Data**  
        This bot needs to collect data that the discord api provides
        in order to function properly. This data consist mainly of your user id combined with other ids such as 
        server and role ids. Non moderation uses include the first date a user joined a server,
        stats with the mute_roll command, commands you have used, 
        the date you last interacted in a server (e.g. by sending a message)
        and image urls for image manipulation commands (only the url and channel are stored here).
        Moderation uses include timeouts, reasons for the timeouts and mutes,
        temproles, command permissions, saving roles and botbans. 
        Message ids are also saved in a handful of server for message purging reasons.
        
        The bot also saves the latest image links sent in a channel for up to 1 day.
        This is to make the image commands more convenient to use.
        
        Message content is saved in memory for a short amount of time. 
        This is used for message delete and edit tracking for servers that have it enabled.
        
        **Agreement**  
        By having this bot in your guild you agree to inform users that
        this bot collects data that the discord api provides in order to function.
        The creator of this bot is not responsible for any damage this bot causes
        including but not limited to failure of a service this bot provides
        
        You can get the support server invite with a command name `support` or use the command `delete_data` if you want 
        your data removed (not including moderation data) and command `do_not_track` will prevent the bot from saving data of you (does not include data used for moderation).
        '''

        d = textwrap.dedent(d).strip('\n')
        if can_embed:
            d = d.format('[here](https://github.com/s0hv/Not-a-bot)')
            embed = discord.Embed(title='Privacy statement', description=d)
            await ctx.send(embed=embed)
        else:
            d = d.format('here https://github.com/s0hv/Not-a-bot')
            await ctx.send(d)

    @command()
    @cooldown(1, 10, BucketType.user)
    async def delete_data(self, ctx: Context):
        """
        Deletes your user data saved to the bot and prevents further data from being saved.
        Moderation related data such as timeouts are not affected.
        Server owners need to manually delete those.
        Also does not delete do not track status if that has been set on.
        """
        await ctx.send('You are about the delete your user data in the bot. This is irreversible. '
                       'Will not prevent further storage of data (see do_not_track command). Type confirm to continue.')

        if not await wait_for_words(ctx, ['confirm'], timeout=30):
            ctx.command.undo_use(ctx)
            return

        try:
            await self.bot.dbutil.delete_user_data(ctx.author.id)
        except:
            await ctx.send('Failed to delete user data. Try again later.')
            raise

        await ctx.send('User data deleted')

    @command()
    @cooldown(1, 5, BucketType.user)
    async def do_not_track(self, ctx, status: bool = None):
        """
        Prevents the bot from passively saving some data of you in non moderation cases.
        If you use the bot some data such as used commands and mute_roll statistics will still be saved.
        """

        is_not_tracked = await self.bot.dbutil.do_not_track_is_on(ctx.author.id)
        on_off = 'on' if is_not_tracked else 'off'

        if status is None:
            await ctx.send(f'Do not track is currently set {on_off}')
            return

        if status is is_not_tracked:
            await ctx.send(f'Do not track is already set to {on_off}')
            return

        on_off = 'on' if status else 'off'
        if await self.bot.dbutil.set_do_not_track(ctx.author.id, status):
            await ctx.send(f'Do not track set to {on_off}. It should take into effect shortly.')
        else:
            await ctx.send(f'Failed to set do not track to {on_off}.')


def setup(bot):
    bot.add_cog(Privacy(bot))
