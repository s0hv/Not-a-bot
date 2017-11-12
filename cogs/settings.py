import discord
from discord.ext.commands import cooldown

from bot.bot import group, command
from cogs.cog import Cog
from utils.utilities import get_channel_id, split_string
from bot.globals import Perms
from collections import OrderedDict


class Settings(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @property
    def cache(self):
        return self.bot.server_cache

    # Required perms for all settings commands: Manage server
    @group(pass_context=True, required_perms=discord.Permissions(32), invoke_without_command=True)
    async def settings(self, ctx):
        server = ctx.message.server
        prefix = self.cache.prefix(server.id)
        embed = discord.Embed(title='Current settings for %s' % server.name, description=
                              'To change these settings use %ssettings <name> <value>\n'
                              'The name for each setting is specified in brackets\n'
                              'Value depends on the setting.' % prefix)
        fields = OrderedDict([('modlog', 'Moderation log'), ('keeproles', 'Re-add roles to user if they rejoin'),
                              ('prefix', 'Command prefix'), ('mute_role', 'Role that is used with timeout and mute')])
        value_conversions = {True: 'Yes', False: 'No', None: 'Not set'}
        type_conversions = {'modlog': lambda c: '<#%s>' % c, 'mute_role': lambda r: '<@&%s>' % r}

        for k, v in fields.items():
            value = self.cache.get_settings(server.id).get(k, None)
            if value is not None and k in type_conversions:
                value = type_conversions[k](value)
            embed.add_field(name='%s (%s)' % (v, k), value=value_conversions.get(value, str(value)), inline=True)

        await self.bot.send_message(ctx.message.channel, embed=embed)

    @cooldown(1, 5)
    @settings.command(pass_context=True, ignore_extra=True)
    async def modlog(self, ctx, channel: str=None):
        if channel is None:
            modlog = self.bot.server_cache.modlog(ctx.message.server.id)
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
            role = self.bot.get_role(server, self.bot.server_cache.mute_role(server.id))
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

    @cooldown(2, 20)
    @settings.command(pass_context=True, ignore_extra=True)
    async def keeproles(self, ctx, boolean: bool=None):
        server = ctx.message.server
        current = self.cache.keeproles(server.id)

        if current == boolean:
            return await self.bot.say('Keeproles is already set to %s' % boolean)

        self.cache.set_keeproles(server.id, boolean)
        if boolean:
            bot_member = server.get_member(self.bot.user.id)
            perms = bot_member.server_permissions
            if not perms.administrator and not perms.manage_roles:
                return await self.bot.say('This bot needs manage roles permissions to enable this feature')
            if not await self.bot.dbutils.index_server_member_roles(server):
                return await self.bot.say('Failed to index user roles')

        await self.bot.say('Keeproles set to %s' % boolean)

    @cooldown(1, 5)
    @command(pass_context=True, required_perms=Perms.MANAGE_ROLE_CHANNEL)
    async def automute_blacklist(self, ctx, *, channels):
        server = ctx.message.server
        ids = []
        failed = []
        for channel in channels.split(' '):
            channel_id = get_channel_id(channel)
            if channel_id:
                channel_ = self.bot.get_channel(channel_id)
                if not channel_ or channel_.server.id != server.id:
                    failed.append(channel)
                else:
                    ids.append(channel_.id)

            else:
                failed.append(channel)

        if failed:
            s = "Couldn't find channels %s" % ', '.join(failed)
            for msg in split_string(s, maxlen=2000, splitter=', '):
                await self.bot.say(msg)

        session = self.bot.get_session
        sql = 'SELECT * FROM `automute_blacklist` WHERE server_id=%s' % server.id
        try:
            rows = session.execute(sql).fetchall()
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
                session.rollback()
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
                session.rollback()
                await self.bot.say('Failed to add automute blacklist')

            else:
                s = split_string('Automute is now blacklisted in %s' % ' '.join(map(lambda cid: '<#%s>' % cid, ids)))
                for msg in s:
                    await self.bot.say(msg)


def setup(bot):
    bot.add_cog(Settings(bot))
