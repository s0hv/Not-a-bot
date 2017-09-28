import discord
from discord.ext.commands import cooldown

from bot.bot import group, command
from cogs.cog import Cog
from utils.utilities import get_channel_id, split_string
from bot.globals import Perms


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

    @cooldown(1, 5)
    @command(pass_context=True, required_perms=Perms.MANAGE_ROLE_CHANNEL)
    async def automute_blacklist(self, ctx, *, channels):
        server = ctx.message.server
        ids = []
        failed = []
        for channel in channels:
            channel_id = get_channel_id(channel)
            if channel_id:
                channel = self.bot.get_channel(channel_id)
                if channel.server.id == server.id:
                    ids.append(channel.id)
                else:
                    failed.append(channel.id)

            else:
                failed.append(channel)
        s = "Couldn't find channels %s" % ', '.join(failed)
        for msg in split_string(s, maxlen=2000, splitter=', '):
            await self.bot.say(msg)

        session = self.bot.get_session
        sql = 'SELECT * FROM `automute_blacklist` WHERE server_id=%s' % server.id
        try:
            rows = session.execute(sql).fetchall
        except:
            return await self.bot.say('Failed to get old blacklist')

        delete = []
        for row in rows:
            if row['channel_id'] in ids:
                ids.remove(row['channel_id'])
                delete.append(row['channel_id'])

        if delete:
            sql = 'DELETE FROM `automute_blacklist` WHERE channel_id IN ' + '(%s)' % ', '.join(delete)
            try:
                session.execute(sql)
                session.commit()
            except:
                await self.bot.say('Failed to remove automute blacklist')
            else:
                s = split_string('Automute blacklist was removed from %s' % ' '.join(map(lambda cid: '<#%s>' % cid, delete)))
                for msg in s:
                    await self.bot.say(msg)

        if ids:
            sql = 'INSERT INTO `automute_blacklist` (`channel_id`, `server_id`) VALUES '
            sql += ', '.join(map(lambda id: '(%s, %s)' % (id, server.id), ids))
            try:
                session.execute(sql)
                session.commit()
            except:
                await self.bot.say('Failed to add automute blacklist')

            else:
                s = split_string('Automute is now blacklisted in %s' % ' '.join(map(lambda cid: '<#%s>' % cid, ids)))
                for msg in s:
                    await self.bot.say(msg)


def setup(bot):
    bot.add_cog(Settings(bot))
