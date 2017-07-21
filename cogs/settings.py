from cogs.cog import Cog
from bot.bot import group, command
from discord.ext.commands import cooldown


class Settings(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @group()
    async def settings(self):
        pass

    @cooldown(1, 5)
    @settings.command(pass_context=True, owner_only=True, ignore_extra=True)
    async def modlog(self, ctx, channel: str=None):
        if channel is None:
            modlog = self.bot.server_cache.get_modlog(ctx.message.server.id)
            modlog = self.bot.get_channel(str(modlog))
            if modlog:
                await self.bot.say('Current modlog channel is %s' % modlog.mention)
            else:
                await self.bot.say('No modlog channel set')
            return

        try:
            int(channel)
            channel = self.bot.get_channel(channel)
        except:
            if not ctx.message.channel_mentions:
                return await self.bot.say('No valid channel or channel id mentioned')

            channel_ = ctx.message.channel_mentions[0]

            if channel_.mention != channel:
                return await self.bot.say('%s is not a valid channel mention' % channel)

            channel = channel_

        self.bot.server_cache.set_modlog(channel.server.id, channel.id)
        await self.bot.send_message(channel, 'Modlog set to this channel')


def setup(bot):
    bot.add_cog(Settings(bot))