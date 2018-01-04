import time
from asyncio import Lock
from collections import OrderedDict

import discord
from discord.ext.commands import cooldown, BucketType

from bot.bot import group, command
from bot.globals import Perms
from cogs.cog import Cog
from utils.utilities import (split_string, format_on_edit, format_on_delete, get_channel,
                             format_join_leave, get_role)
from bot import exceptions


class Settings(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._server_locks = {'keeproles': {}}

    @property
    def cache(self):
        return self.bot.server_cache

    # Required perms for all settings commands: Manage server
    @cooldown(1, 5)
    @group(pass_context=True, invoke_without_command=True, no_pm=True)
    async def settings(self, ctx):
        """Gets the current settings on the server"""
        server = ctx.message.server
        prefix = self.cache.prefixes(server.id)[0]
        embed = discord.Embed(title='Current settings for %s' % server.name, description=
                              'To change these settings use {}settings <name> <value>\n'
                              'The name for each setting is specified in brackets\n'
                              'Value depends on the setting.'.format(prefix))
        fields = OrderedDict([('modlog', 'Moderation log'), ('keeproles', 'Re-add roles to user if they rejoin'),
                              ('prefixes', 'Command prefixes'), ('mute_role', 'Role that is used with timeout and mute'),
                              ('random_color', 'Add a random color to a user when they join'),
                              ('automute', 'Mute on too many mentions in a message'),
                              ('automute_limit', 'How many mentions needed for mute')])
        type_conversions = {True: 'On', False: 'Off', None: 'Not set'}
        value_conversions = {'modlog': lambda c: '<#%s>' % c, 'mute_role': lambda r: '<@&%s>' % r,
                             'prefixes': lambda p: '`' + '` `'.join(p) + '`'}

        for k, v in fields.items():
            value = getattr(self.cache, k, None)
            if callable(value):
                value = value(server.id)
            if value is not None and k in value_conversions:
                value = value_conversions[k](value)
            embed.add_field(name='%s (%s)' % (v, k), value=type_conversions.get(value, str(value)), inline=True)

        await self.bot.send_message(ctx.message.channel, embed=embed)

    async def _add_prefix(self, server_id, prefix):
        prefixes = self.cache.prefixes(server_id, use_set=True)

        if len(prefixes) >= 10:
            return await self.bot.say('You can only have a maximum of 10 prefixes at one time. Remove some prefixes before proceeding')

        if len(prefix) > 30:
            return await self.bot.say('Maximum length for a prefix is 30. This prefixes length is {}'.format(len(prefix)))

        try:
            success = self.cache.add_prefix(server_id, prefix)
        except exceptions.PrefixExists:
            return await self.bot.say('Prefix already in use')

        if not success:
            return await self.bot.say('Failed to add prefix {}'.format(prefix))

        await self.bot.say('Added prefix {}'.format(prefix))

    async def _remove_prefix(self, server_id, prefix):
        try:
            success = self.cache.remove_prefix(server_id, prefix)
        except exceptions.NotEnoughPrefixes:
            return await self.bot.say('Need a minimum of 1 prefix')
        except exceptions.PrefixDoesntExist:
            return await self.bot.say("Prefix doesn't exist")

        if not success:
            return await self.bot.say('Failed to remove prefix {}'.format(prefix))

        await self.bot.say('Removed prefix {}'.format(prefix))

    @cooldown(1, 5)
    @group(pass_context=True, no_pm=True, invoke_without_command=True, aliases=['prefixes'])
    async def prefix(self, ctx):
        """Shows all the active prefixes on this server"""
        prefixes = self.cache.prefixes(ctx.message.server.id)
        await self.bot.say('Current prefixes on server\n`{}`'.format('` `'.join(prefixes)))

    @cooldown(2, 10)
    @prefix.command(pass_context=True, required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_SERVER)
    async def add(self, ctx, prefix):
        """Add a prefix to this server"""
        await self._add_prefix(ctx.message.server.id, prefix)

    @cooldown(2, 10)
    @prefix.command(pass_context=True, aliases=['delete', 'del'],
                    required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_SERVER)
    async def remove(self, ctx, prefix):
        """Remove and active prefix from use"""
        await self._remove_prefix(ctx.message.server.id, prefix)

    @cooldown(1, 5, type=BucketType.server)
    @settings.command(pass_context=True, ignore_extra=True, required_perms=Perms.MANAGE_SERVER | Perms.MANAGE_CHANNEL)
    async def modlog(self, ctx, channel: str=None):
        """If no parameters are passed gets the current modlog
        If channel is provided modlog will be set to that channel.
        channel can be a channel mention, channel id or channel name (case sensitive)"""
        if channel is None:
            modlog = self.bot.server_cache.modlog(ctx.message.server.id)
            modlog = self.bot.get_channel(str(modlog))
            if modlog:
                await self.bot.say('Current modlog channel is %s' % modlog.mention)
            else:
                await self.bot.say('No modlog channel set')

            ctx.command.reset_cooldown(ctx)
            return

        channel_ = get_channel(ctx.message.server.channels, channel, name_matching=True)
        if not channel_:
            ctx.command.reset_cooldown(ctx)
            return await self.bot.say('No channel found with {}'.format(channel))

        self.bot.server_cache.set_modlog(channel_.server.id, channel_.id)
        await self.bot.send_message(channel_, 'Modlog set to this channel')

    @cooldown(1, 5, type=BucketType.server)
    @settings.command(pass_context=True, ignore_extra=True, required_perms=Perms.MANAGE_ROLES)
    async def mute_role(self, ctx, role=None):
        server = ctx.message.server
        if role is None:
            role = get_role(server, self.bot.server_cache.mute_role(server.id), name_matching=True)
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

    @cooldown(2, 20, type=BucketType.server)
    @settings.command(pass_context=True, ignore_extra=True, required_perms=Perms.ADMIN)
    async def keeproles(self, ctx, boolean: bool=None):
        server = ctx.message.server
        current = self.cache.keeproles(server.id)

        if current == boolean:
            return await self.bot.say('Keeproles is already set to %s' % boolean)

        lock = self._server_locks['keeproles'].get(server.id, None)
        if lock is None:
            lock = Lock()
            self._server_locks['keeproles'][server.id] = lock

        if lock.locked():
            return await self.bot.say('Hol up b')

        if boolean:
            t = time.time()
            await lock.acquire()
            try:
                bot_member = server.get_member(self.bot.user.id)
                perms = bot_member.server_permissions
                if not perms.administrator and not perms.manage_roles:
                    return await self.bot.say('This bot needs manage roles permissions to enable this feature')
                msg = await self.bot.say('indexing roles')
                if not await self.bot.dbutils.index_server_member_roles(server):
                    return await self.bot.say('Failed to index user roles')

                await self.bot.edit_message(msg, new_content='Indexed roles in {0:.2f}s'.format(time.time()-t))
            except:
                pass
            finally:
                lock.release()

        self.cache.set_keeproles(server.id, boolean)
        await self.bot.say('Keeproles set to %s' % str(boolean))

    @settings.command(pass_context=True, required_perms=Perms.MANAGE_ROLES|Perms.MANAGE_SERVER)
    @cooldown(2, 10, BucketType.server)
    async def random_color(self, ctx, value: bool=None):
        server = ctx.message.server
        if value is None:
            value = self.cache.random_color(server.id)
            value = 'on' if value else 'off'
            return await self.bot.say('Random color on join is currently ' + value)

        success = self.cache.set_random_color(server.id, value)
        if not success:
            return await self.bot.say('Failed to change value because of an error')
        value = 'on' if value else 'off'
        await self.bot.say('Changed the value to ' + value)

    @settings.command(pass_context=True, required_perms=Perms.MANAGE_ROLES | Perms.MANAGE_SERVER, ignore_extra=True)
    @cooldown(2, 10, BucketType.server)
    async def automute(self, ctx, value: bool=None):
        server = ctx.message.server
        if value is None:
            value = 'on' if self.cache.automute(server.id) else 'off'
            return await self.bot.say('Automute is currently set {}'.format(value))

        success = self.cache.set_automute(server.id, value)
        if not success:
            return self.bot.say('Failed to set automute value')

        value = 'on' if value else 'off'
        await self.bot.say('Set automute value to ' + value)

    @settings.command(pass_context=True, required_perms=Perms.MANAGE_ROLES | Perms.MANAGE_SERVER, ignore_extra=True)
    @cooldown(2, 10, BucketType.server)
    async def automute_limit(self, ctx, limit: int=None):
        server = ctx.message.server
        if limit is None:
            return await self.bot.say('Current limit is {}'.format(self.cache.automute_limit(server.id)))

        if limit <= 4:
            return await self.bot.say('Value must be higher than 4')
        if limit > 30:
            return await self.bot.say('Value must be equal to or lower than 30')

        success = self.cache.set_automute_limit(server.id, limit)

        if not success:
            return self.bot.say('Failed to set automute limit')

        await self.bot.say('Set automute limit to ' + str(limit))

    @group(pass_context=True, invoke_without_command=True)
    @cooldown(2, 10, BucketType.server)
    async def on_delete(self, ctx):
        """
        Gives the current message format that is used when a message is deleted if logging is enabled for deleted messages
        If a format isn't set the default format is used.
        To see formatting help use {prefix}formatting
        """
        server = ctx.message.server
        message = self.cache.on_delete_message(server.id)
        channel = self.cache.on_delete_channel(server.id)
        if message is None and channel is None:
            return await self.bot.say("On message delete message format hasn't been set")
        elif message is None:
            message = self.cache.on_delete_message(server.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await self.bot.say(msg)

    @on_delete.command(pass_context=True, required_permissions=Perms.MANAGE_SERVER|Perms.MANAGE_CHANNEL)
    @cooldown(2, 10, BucketType.server)
    async def set(self, ctx, *, message_format):
        """
        Set the message format for deleted message logging.
        See {prefix}formatting for more info on how to format messages.
        A default format is used if this is not specified
        """
        message = ctx.message
        try:
            formatted = format_on_delete(message, message_format)
        except Exception as e:
            return await self.bot.say('Failed to use format because it returned an error.```py\n{}```'.format(e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 2:
            return await self.bot.say('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = self.cache.set_on_delete_message(message.server.id, message_format)
        if not success:
            await self.bot.say('Failed to set message format because of an error')
        else:
            await self.bot.say('Successfully set the message format')

    @on_delete.command(pass_context=True)
    @cooldown(2, 10, BucketType.server)
    async def channel(self, ctx, *, channel=None):
        server = ctx.message.server
        if channel is None:
            channel = self.cache.on_delete_channel(server.id)
            if channel is None:
                await self.bot.say('Currently not logging deleted messages')
            else:
                await self.bot.say('Currently logging deleted messages to <#{}>'.format(channel))
            return

        channel = get_channel(server.channels, channel, name_matching=True)
        if channel is None:
            return await self.bot.say('No channel id or mention provided')

        success = self.cache.set_on_delete_channel(server.id, channel.id)
        if not success:
            await self.bot.say('Failed to set channel because of an error')
        else:
            await self.bot.say('channel set to {0.name} {0.mention}'.format(channel))

    @group(pass_context=True, invoke_without_command=True)
    @cooldown(2, 10, BucketType.server)
    async def on_edit(self, ctx):
        """
        Gives the current message format that is used when a message is edited if logging is enabled for edited messages
        If a format isn't set the default format is used.
        To see formatting help use {prefix}formatting
        """
        server = ctx.message.server
        message = self.cache.on_edit_message(server.id)
        channel = self.cache.on_edit_channel(server.id)
        if message is None and channel is None:
            return await self.bot.say("On message edit message format hasn't been set")
        elif message is None:
            message = self.cache.on_edit_message(server.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await self.bot.say(msg)

    @on_edit.command(pass_context=True, name='set', required_permissions=Perms.MANAGE_SERVER | Perms.MANAGE_CHANNEL)
    @cooldown(2, 10, BucketType.server)
    async def set_(self, ctx, *, message_format):
        """
        Set the message format for edited message logging.
        See {prefix}formatting for more info on how to format messages.
        A default format is used if this is not specified
        """
        message = ctx.message
        try:
            formatted = format_on_edit(message, message, message_format, check_equal=False)
        except Exception as e:
            return await self.bot.say('Failed to use format because it returned an error.```py\n{}```'.format(e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 2:
            return await self.bot.say('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = self.cache.set_on_edit_message(message.server.id, message_format)
        if not success:
            await self.bot.say('Failed to set message format because of an error')
        else:
            await self.bot.say('Successfully set the message format')

    @on_edit.command(pass_context=True, name='channel', required_permissions=Perms.MANAGE_SERVER|Perms.MANAGE_CHANNEL)
    @cooldown(2, 10, BucketType.server)
    async def channel_(self, ctx, *, channel=None):
        server = ctx.message.server
        if channel is None:
            channel = self.cache.on_edit_channel(server.id)
            if channel is None:
                await self.bot.say('Currently not logging edited messages')
            else:
                await self.bot.say('Currently logging edited messages to <#{}>'.format(channel))
            return

        channel = get_channel(server.channels, channel, name_matching=True)
        if channel is None:
            return await self.bot.say('No channel id or mention provided')

        success = self.cache.set_on_edit_channel(server.id, channel.id)
        if not success:
            await self.bot.say('Failed to set channel because of an error')
        else:
            await self.bot.say('channel set to {0.name} {0.mention}'.format(channel))

    @group(pass_context=True, invoke_without_command=True)
    @cooldown(2, 10, BucketType.server)
    async def join_message(self, ctx):
        server = ctx.message.server
        message = self.cache.join_message(server.id)
        channel = self.cache.join_channel(server.id)
        if message is None and channel is None:
            return await self.bot.say("Member join message format hasn't been set")
        elif message is None:
            message = self.cache.join_message(server.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await self.bot.say(msg)

    @join_message.command(pass_context=True, name='set', required_perms=Perms.MANAGE_CHANNEL|Perms.MANAGE_SERVER)
    @cooldown(2, 10, BucketType.server)
    async def join_set(self, ctx, *, message):
        server = ctx.message.server
        try:
            formatted = format_join_leave(ctx.message.author, message)
        except Exception as e:
            return await self.bot.say('Failed to use format because it returned an error.```py\n{}```'.format(e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 1:
            return await self.bot.say('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = self.cache.set_join_message(server.id, message)
        if not success:
            await self.bot.say('Failed to set message format because of an error')
        else:
            await self.bot.say('Successfully set the message format')

    @join_message.command(pass_context=True, name='channel',
                          required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_SERVER)
    @cooldown(2, 10, BucketType.server)
    async def join_channel(self, ctx, *, channel=None):
        server = ctx.message.server
        if channel is None:
            channel = self.cache.join_channel(server.id)
            if channel is None:
                await self.bot.say('Currently not logging members who join')
            else:
                await self.bot.say('Currently logging members who join in <#{}>'.format(channel))
            return

        channel = get_channel(server.channels, channel, name_matching=True)
        if channel is None:
            return await self.bot.say('No channel id or mention provided')

        success = self.cache.set_join_channel(server.id, channel.id)
        if not success:
            await self.bot.say('Failed to set channel because of an error')
        else:
            await self.bot.say('channel set to {0.name} {0.mention}'.format(channel))

    @group(pass_context=True, invoke_without_command=True)
    @cooldown(2, 10, BucketType.server)
    async def leave_message(self, ctx):
        server = ctx.message.server
        message = self.cache.leave_message(server.id)
        channel = self.cache.leave_channel(server.id)
        if message is None and channel is None:
            return await self.bot.say("Member leave message format hasn't been set")
        elif message is None:
            message = self.cache.leave_message(server.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await self.bot.say(msg)

    @leave_message.command(pass_context=True, name='set',
                           required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_SERVER)
    @cooldown(2, 10, BucketType.server)
    async def leave_set(self, ctx, *, message):
        server = ctx.message.server
        try:
            formatted = format_join_leave(ctx.message.author, message)
        except Exception as e:
            return await self.bot.say(
                'Failed to use format because it returned an error.```py\n{}```'.format(
                    e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 1:
            return await self.bot.say(
                'The message generated using this format is too long. Please reduce the amount of text/variables')

        success = self.cache.set_leave_message(server.id, message)
        if not success:
            await self.bot.say(
                'Failed to set message format because of an error')
        else:
            await self.bot.say('Successfully set the message format')

    @leave_message.command(pass_context=True, name='channel',
                           required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_SERVER)
    @cooldown(2, 10, BucketType.server)
    async def leave_channel(self, ctx, *, channel=None):
        server = ctx.message.server
        if channel is None:
            channel = self.cache.leave_channel(server.id)
            if channel is None:
                await self.bot.say('Currently not logging members who leave')
            else:
                await self.bot.say('Currently logging members who leave in <#{}>'.format(channel))
            return

        channel = get_channel(server.channels, channel, name_matching=True)
        if channel is None:
            return await self.bot.say('No channel id or mention provided')

        success = self.cache.set_leave_channel(server.id, channel.id)
        if not success:
            await self.bot.say('Failed to set channel because of an error')
        else:
            await self.bot.say('channel set to {0.name} {0.mention}'.format(channel))


def setup(bot):
    bot.add_cog(Settings(bot))
