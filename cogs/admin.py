from cogs.cog import Cog
from bot.bot import command


class Admin(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(pass_context=True, ignore_extra=True)
    async def lock(self, ctx):
        channel = ctx.message.channel
        perms = channel.permissions_for(ctx.message.author)
        if not perms.manage_channel or not perms.manage_roles:
            return await self.bot.say("You need manage channel and manage roles permissions to use this command")

        everyone = ctx.message.server.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False
        try:
            await channel.edit_channel_permissions(channel, everyone, overwrite)
        except Exception as e:
            return await self.bot.say('Failed to lock channel because of an error: %s. '
                                      'Bot might lack the permissions to do so' % e)


def setup(bot):
    bot.add_cog(Admin(bot))