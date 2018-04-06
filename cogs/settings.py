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
        self._guild_locks = {'keeproles': {}}

    @property
    def cache(self):
        return self.bot.guild_cache

    # Required perms for all settings commands: Manage server
    @cooldown(1, 5)
    @group(invoke_without_command=True, no_pm=True)
    async def settings(self, ctx):
        """Gets the current settings on the server"""
        guild = ctx.guild
        prefix = self.cache.prefixes(guild.id)[0]
        embed = discord.Embed(title='Current settings for %s' % guild.name, description=
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
                value = value(guild.id)
            if value is not None and k in value_conversions:
                value = value_conversions[k](value)
            embed.add_field(name='%s (%s)' % (v, k), value=type_conversions.get(value, str(value)), inline=True)

        await ctx.send(embed=embed)

    async def _add_prefix(self, ctx, guild_id, prefix):
        prefixes = self.cache.prefixes(guild_id, use_set=True)

        if len(prefixes) >= 10:
            return await ctx.send('You can only have a maximum of 10 prefixes at one time. Remove some prefixes before proceeding')

        if len(prefix) > 30:
            return await ctx.send('Maximum length for a prefix is 30. This prefixes length is {}'.format(len(prefix)))

        try:
            success = self.cache.add_prefix(guild_id, prefix)
        except exceptions.PrefixExists:
            return await ctx.send('Prefix already in use')

        if not success:
            return await ctx.send('Failed to add prefix {}'.format(prefix))

        await ctx.send('Added prefix {}'.format(prefix))

    async def _remove_prefix(self, ctx, guild_id, prefix):
        try:
            success = self.cache.remove_prefix(guild_id, prefix)
        except exceptions.NotEnoughPrefixes:
            return await ctx.send('Need a minimum of 1 prefix')
        except exceptions.PrefixDoesntExist:
            return await ctx.send("Prefix doesn't exist")

        if not success:
            return await ctx.send('Failed to remove prefix {}'.format(prefix))

        await ctx.send('Removed prefix {}'.format(prefix))

    @cooldown(1, 5)
    @group(no_pm=True, invoke_without_command=True, aliases=['prefixes'])
    async def prefix(self, ctx):
        """Shows all the active prefixes on this server"""
        prefixes = self.cache.prefixes(ctx.guild.id)
        await ctx.send('Current prefixes on server\n`{}`'.format('` `'.join(prefixes)))

    @cooldown(2, 10)
    @prefix.command(required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_GUILD)
    async def add(self, ctx, prefix):
        """Add a prefix to this server"""
        await self._add_prefix(ctx, ctx.guild.id, prefix)

    @cooldown(2, 10)
    @prefix.command(aliases=['delete', 'del'], required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_GUILD)
    async def remove(self, ctx, prefix):
        """Remove and active prefix from use"""
        await self._remove_prefix(ctx, ctx.guild.id, prefix)

    @cooldown(1, 5, type=BucketType.guild)
    @settings.command(ignore_extra=True, required_perms=Perms.MANAGE_GUILD | Perms.MANAGE_CHANNEL)
    async def modlog(self, ctx, channel: str=None):
        """If no parameters are passed gets the current modlog
        If channel is provided modlog will be set to that channel.
        channel can be a channel mention, channel id or channel name (case sensitive)"""
        if channel is None:
            modlog = self.bot.guild_cache.modlog(ctx.guild.id)
            modlog = self.bot.get_channel(modlog)
            if modlog:
                await ctx.send('Current modlog channel is %s' % modlog.mention)
            else:
                await ctx.send('No modlog channel set')

            ctx.command.reset_cooldown(ctx)
            return

        channel_ = get_channel(ctx.guild.channels, channel, name_matching=True)
        if not channel_:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send('No channel found with {}'.format(channel))

        self.bot.guild_cache.set_modlog(channel_.guild.id, channel_.id)
        await channel_.send('Modlog set to this channel')

    @cooldown(1, 5, type=BucketType.guild)
    @settings.command(ignore_extra=True, required_perms=Perms.MANAGE_ROLES)
    async def mute_role(self, ctx, role=None):
        """Get the current role for muted people on this server or set it"""
        guild = ctx.guild
        if role is None:
            role = get_role(guild, self.bot.guild_cache.mute_role(guild.id), name_matching=True)
            if role:
                await ctx.send('Current role for muted people is {0} `{0.id}`'.format(role))
            else:
                await ctx.send('No role set for muted people')
            ctx.command.reset_cooldown(ctx)
            return

        try:
            int(role)
            role = self.bot.get_role(role, guild)
        except ValueError:
            if not ctx.message.raw_role_mentions or ctx.message.raw_role_mentions[0] not in role:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send('No valid role or role id mentions')

            role = self.bot.get_role(ctx.message.raw_role_mentions[0], guild)

        self.bot.guild_cache.set_mute_role(guild.id, role.id)
        await ctx.send('Muted role set to {0} `{0.id}`'.format(role))

    @cooldown(2, 20, type=BucketType.guild)
    @settings.command(ignore_extra=True, required_perms=Perms.ADMIN)
    async def keeproles(self, ctx, boolean: bool=None):
        """Get the current keeproles value on this server or change it.
        Keeproles makes the bot save every users roles so it can give them even if that user rejoins"""
        guild = ctx.guild
        current = self.cache.keeproles(guild.id)

        if current == boolean:
            return await ctx.send('Keeproles is already set to %s' % boolean)

        lock = self._guild_locks['keeproles'].get(guild.id, None)
        if lock is None:
            lock = Lock(loop=self.bot.loop)
            self._guild_locks['keeproles'][guild.id] = lock

        if lock.locked():
            return await ctx.send('Hol up b')

        if boolean:
            t = time.time()
            await lock.acquire()
            try:
                bot_member = guild.get_member(self.bot.user.id)
                perms = bot_member.guild_permissions
                if not perms.administrator and not perms.manage_roles:
                    return await ctx.send('This bot needs manage roles permissions to enable this feature')
                msg = await ctx.send('indexing roles')
                if not await self.bot.dbutils.index_guild_member_roles(guild):
                    return await ctx.send('Failed to index user roles')

                await msg.edit(content='Indexed roles in {0:.2f}s'.format(time.time()-t))
            except:
                pass
            finally:
                lock.release()

        self.cache.set_keeproles(guild.id, boolean)
        await ctx.send('Keeproles set to %s' % str(boolean))

    @settings.command(required_perms=Perms.MANAGE_ROLES|Perms.MANAGE_GUILD)
    @cooldown(2, 10, BucketType.guild)
    async def random_color(self, ctx, value: bool=None):
        """Check if random color is on or change the current value of it.
        Random color will make the bot give a random color role to all new users who join
        if color roles exist on the server"""
        guild = ctx.guild
        if value is None:
            value = self.cache.random_color(guild.id)
            value = 'on' if value else 'off'
            return await ctx.send('Random color on join is currently ' + value)

        success = self.cache.set_random_color(guild.id, value)
        if not success:
            return await ctx.send('Failed to change value because of an error')
        value = 'on' if value else 'off'
        await ctx.send('Changed the value to ' + value)

    @settings.command(required_perms=Perms.MANAGE_ROLES | Perms.MANAGE_GUILD, ignore_extra=True)
    @cooldown(2, 10, BucketType.guild)
    async def automute(self, ctx, value: bool=None):
        """Check or set the status of automatic muting"""
        guild = ctx.guild
        if value is None:
            value = 'on' if self.cache.automute(guild.id) else 'off'
            return await ctx.send('Automute is currently set {}'.format(value))

        success = self.cache.set_automute(guild.id, value)
        if not success:
            return ctx.send('Failed to set automute value')

        value = 'on' if value else 'off'
        await ctx.send('Set automute value to ' + value)

    @settings.command(required_perms=Perms.MANAGE_ROLES | Perms.MANAGE_GUILD, ignore_extra=True)
    @cooldown(2, 10, BucketType.guild)
    async def automute_limit(self, ctx, limit: int=None):
        """Check or set the limit of mentions in a message for the bot to mute a user"""
        guild = ctx.guild
        if limit is None:
            return await ctx.send('Current limit is {}'.format(self.cache.automute_limit(guild.id)))

        if limit <= 4:
            return await ctx.send('Value must be higher than 4')
        if limit > 30:
            return await ctx.send('Value must be equal to or lower than 30')

        success = self.cache.set_automute_limit(guild.id, limit)

        if not success:
            return ctx.send('Failed to set automute limit')

        await ctx.send('Set automute limit to ' + str(limit))

    @group(invoke_without_command=True)
    @cooldown(2, 10, BucketType.guild)
    async def on_delete(self, ctx):
        """
        Gives the current message format that is used when a message is deleted if logging is enabled for deleted messages
        If a format isn't set the default format is used.
        To see formatting help use {prefix}formatting
        """
        guild = ctx.guild
        message = self.cache.on_delete_message(guild.id)
        channel = self.cache.on_delete_channel(guild.id)
        if message is None and channel is None:
            return await ctx.send("On message delete message format hasn't been set")
        elif message is None:
            message = self.cache.on_delete_message(guild.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await ctx.send(msg)

    @on_delete.command(required_permissions=Perms.MANAGE_GUILD | Perms.MANAGE_CHANNEL)
    @cooldown(2, 10, BucketType.guild)
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
            return await ctx.send('Failed to use format because it returned an error.```py\n{}```'.format(e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 2:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = self.cache.set_on_delete_message(message.guild.id, message_format)
        if not success:
            await ctx.send('Failed to set message format because of an error')
        else:
            await ctx.send('Successfully set the message format')

    @on_delete.command(required_permissions=Perms.MANAGE_GUILD | Perms.MANAGE_CHANNEL)
    @cooldown(2, 10, BucketType.guild)
    async def channel(self, ctx, *, channel=None):
        """Check or set the channel deleted messages are logged in to"""
        guild = ctx.guild
        if channel is None:
            channel = self.cache.on_delete_channel(guild.id)
            if channel is None:
                await ctx.send('Currently not logging deleted messages')
            else:
                await ctx.send('Currently logging deleted messages to <#{}>'.format(channel))
            return

        channel = get_channel(guild.channels, channel, name_matching=True)
        if channel is None:
            return await ctx.send('No channel id or mention provided')

        success = self.cache.set_on_delete_channel(guild.id, channel.id)
        if not success:
            await ctx.send('Failed to set channel because of an error')
        else:
            await ctx.send('channel set to {0.name} {0.mention}'.format(channel))

    @group(invoke_without_command=True)
    @cooldown(2, 10, BucketType.guild)
    async def on_edit(self, ctx):
        """
        Gives the current message format that is used when a message is edited if logging is enabled for edited messages
        If a format isn't set the default format is used.
        To see formatting help use {prefix}formatting
        """
        guild = ctx.guild
        message = self.cache.on_edit_message(guild.id)
        channel = self.cache.on_edit_channel(guild.id)
        if message is None and channel is None:
            return await ctx.send("On message edit message format hasn't been set")
        elif message is None:
            message = self.cache.on_edit_message(guild.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await ctx.send(msg)

    @on_edit.command(name='set', required_permissions=Perms.MANAGE_GUILD | Perms.MANAGE_CHANNEL)
    @cooldown(2, 10, BucketType.guild)
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
            return await ctx.send('Failed to use format because it returned an error.```py\n{}```'.format(e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 2:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = self.cache.set_on_edit_message(message.guild.id, message_format)
        if not success:
            await ctx.send('Failed to set message format because of an error')
        else:
            await ctx.send('Successfully set the message format')

    @on_edit.command(name='channel', required_permissions=Perms.MANAGE_GUILD | Perms.MANAGE_CHANNEL)
    @cooldown(2, 10, BucketType.guild)
    async def channel_(self, ctx, *, channel=None):
        """Check or set the channel message edits are logged to"""
        guild = ctx.guild
        if channel is None:
            channel = self.cache.on_edit_channel(guild.id)
            if channel is None:
                await ctx.send('Currently not logging edited messages')
            else:
                await ctx.send('Currently logging edited messages to <#{}>'.format(channel))
            return

        channel = get_channel(guild.channels, channel, name_matching=True)
        if channel is None:
            return await ctx.send('No channel id or mention provided')

        success = self.cache.set_on_edit_channel(guild.id, channel.id)
        if not success:
            await ctx.send('Failed to set channel because of an error')
        else:
            await ctx.send('channel set to {0.name} {0.mention}'.format(channel))

    @group(invoke_without_command=True, aliases=['on_join', 'welcome_message'])
    @cooldown(2, 10, BucketType.guild)
    async def join_message(self, ctx):
        """Get the welcome/join message on this server"""
        guild = ctx.guild
        message = self.cache.join_message(guild.id)
        channel = self.cache.join_channel(guild.id)
        if message is None and channel is None:
            return await ctx.send("Member join message format hasn't been set")
        elif message is None:
            message = self.cache.join_message(guild.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await ctx.send(msg)

    @join_message.command(name='set', required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_GUILD)
    @cooldown(2, 10, BucketType.guild)
    async def join_set(self, ctx, *, message):
        """Set the welcome message on this server
        See {prefix}formatting for help on formatting the message"""
        guild = ctx.guild
        try:
            formatted = format_join_leave(ctx.author, message)
        except Exception as e:
            return await ctx.send('Failed to use format because it returned an error.```py\n{}```'.format(e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 1:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = self.cache.set_join_message(guild.id, message)
        if not success:
            await ctx.send('Failed to set message format because of an error')
        else:
            await ctx.send('Successfully set the message format')

    @join_message.command(name='channel', required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_GUILD)
    @cooldown(2, 10, BucketType.guild)
    async def join_channel(self, ctx, *, channel=None):
        """Check or set the join/welcome message channel"""
        guild = ctx.guild
        if channel is None:
            channel = self.cache.join_channel(guild.id)
            if channel is None:
                await ctx.send('Currently not logging members who join')
            else:
                await ctx.send('Currently logging members who join in <#{}>'.format(channel))
            return

        channel = get_channel(guild.channels, channel, name_matching=True)
        if channel is None:
            return await ctx.send('No channel id or mention provided')

        success = self.cache.set_join_channel(guild.id, channel.id)
        if not success:
            await ctx.send('Failed to set channel because of an error')
        else:
            await ctx.send('channel set to {0.name} {0.mention}'.format(channel))

    @group(invoke_without_command=True, aliases=['on_leave'])
    @cooldown(2, 10, BucketType.guild)
    async def leave_message(self, ctx):
        """Get the current message that is sent when a user leaves the server"""
        guild = ctx.guild
        message = self.cache.leave_message(guild.id)
        channel = self.cache.leave_channel(guild.id)
        if message is None and channel is None:
            return await ctx.send("Member leave message format hasn't been set")
        elif message is None:
            message = self.cache.leave_message(guild.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await ctx.send(msg)

    @leave_message.command(name='set', required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_GUILD)
    @cooldown(2, 10, BucketType.guild)
    async def leave_set(self, ctx, *, message):
        """Set the leave message on this server
        See {prefix}formatting for help on formatting the message"""
        guild = ctx.guild
        try:
            formatted = format_join_leave(ctx.author, message)
        except Exception as e:
            return await ctx.send('Failed to use format because it returned an error.```py\n{}```'.format(e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 1:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = self.cache.set_leave_message(guild.id, message)
        if not success:
            await ctx.send('Failed to set message format because of an error')
        else:
            await ctx.send('Successfully set the message format')

    @leave_message.command(name='channel', required_perms=Perms.MANAGE_CHANNEL | Perms.MANAGE_GUILD)
    @cooldown(2, 10, BucketType.guild)
    async def leave_channel(self, ctx, *, channel=None):
        """Set the channel that user leave messages are sent to"""
        guild = ctx.guild
        if channel is None:
            channel = self.cache.leave_channel(guild.id)
            if channel is None:
                await ctx.send('Currently not logging members who leave')
            else:
                await ctx.send('Currently logging members who leave in <#{}>'.format(channel))
            return

        channel = get_channel(guild.channels, channel, name_matching=True)
        if channel is None:
            return await ctx.send('No channel id or mention provided')

        success = self.cache.set_leave_channel(guild.id, channel.id)
        if not success:
            await ctx.send('Failed to set channel because of an error')
        else:
            await ctx.send('channel set to {0.name} {0.mention}'.format(channel))


def setup(bot):
    bot.add_cog(Settings(bot))
