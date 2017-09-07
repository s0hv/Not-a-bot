import discord
from discord.ext.commands import cooldown

from bot.bot import group
from cogs.cog import Cog


class Settings(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @property
    def cache(self):
        return self.bot.server_cache

    # Required perms for all settings commands: Manage server
    @group(required_perms=discord.Permissions(32))
    async def settings(self):
        pass

    @cooldown(1, 5)
    @settings.command(pass_context=True, ignore_extra=True)
    async def modlog(self, ctx, channel: str=None):
        if channel is None:
            modlog = self.bot.server_cache.get_modlog(ctx.message.server.id)
            modlog = self.bot.get_channel(str(modlog))
            if modlog:
                await self.bot.say('Current modlog channel is %s' % modlog.mention)
            else:
                await self.bot.say('No modlog channel set')

            ctx.command.reset_cooldown(ctx)
            return

        try:
            int(channel)
            channel = self.bot.get_channel(channel)
        except:
            if not ctx.message.channel_mentions or ctx.message.channel_mentions[0].mention != channel:
                ctx.command.reset_cooldown(ctx)
                return await self.bot.say('No valid channel or channel id mentions')

            channel = ctx.message.channel_mentions[0]

        self.bot.server_cache.set_modlog(channel.server.id, channel.id)
        await self.bot.send_message(channel, 'Modlog set to this channel')

    @cooldown(1, 5)
    @settings.command(pass_context=True, ignore_extra=True)
    async def mute_role(self, ctx, role=None):
        server = ctx.message.server
        if role is None:
            role = self.bot.get_role(server, self.bot.server_cache.get_mute_role(server.id))
            if role:
                await self.bot.say('Current role for muted people is {0} `{0.id}`'.format(role))
            else:
                await self.bot.say('No role set for muted people')
            ctx.command.reset_cooldown(ctx)
            return

        try:
            int(role)
            role = self.bot.get_role(server, role)
        except:
            if not ctx.message.raw_role_mentions or ctx.message.raw_role_mentions[0] not in role:
                ctx.command.reset_cooldown(ctx)
                return await self.bot.say('No valid role or role id mentions')

            role = self.bot.get_role(server, ctx.message.raw_role_mentions[0])

        self.bot.server_cache.set_mute_role(server.id, role.id)
        await self.bot.say('Muted role set to {0} `{0.id}`'.format(role))

    @cooldown(1, 5)
    @settings.command(pass_context=True, ignore_extra=True)
    async def keeproles(self, ctx, boolean: bool=None):
        server = ctx.message.server
        if boolean is None:
            return await self.bot.say('Current keeproles value: %s' % self.cache.keeproles(server.id))

        self.cache.set_keeproles(server.id, boolean)
        await self.bot.say('Keeproles set to %s' % boolean)


def setup(bot):
    bot.add_cog(Settings(bot))
