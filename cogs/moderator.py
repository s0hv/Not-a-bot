from cogs.cog import Cog
from bot.bot import command
from random import randint
import discord


class Moderator(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(pass_context=True)
    async def add_role(self, ctx, name, random_color=True, mentionable=True):
        if ctx.message.server is None:
            return await self.bot.say('Cannot create roles in DM')

        perms = ctx.message.channel.permissions_for(ctx.message.author)
        if not perms.manage_roles:
            return await self.bot.say('You need manage roles permissions to use this command')

        default_perms = ctx.message.server.default_role.permissions
        color = None
        if random_color:
            color = discord.Color(randint(0, 16777215))
        try:
            await self.bot.create_role(ctx.message.server, name=name, permissions=default_perms,
                                       colour=color, mentionable=mentionable)
        except Exception as e:
            return await self.bot.say('Could not create role because of an error\n```%s```' % e)

        await self.bot.say('Successfully created role %s' % name)


def setup(bot):
    bot.add_cog(Moderator(bot))