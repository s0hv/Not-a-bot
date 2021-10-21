import logging
import time
from asyncio import Lock, TimeoutError
from collections import OrderedDict
from typing import Optional

import discord
from discord import AllowedMentions
from discord.ext.commands import BucketType

from bot import exceptions
from bot.bot import group, has_permissions, cooldown, command, \
    bot_has_permissions, Context
from bot.converters import TimeDelta, PossibleUser
from bot.formatter import Paginator
from cogs.cog import Cog
from utils.utilities import (split_string, format_on_edit, format_on_delete,
                             format_join_leave, timedelta2sql, seconds2str,
                             sql2timedelta, test_member, test_message,
                             basic_check, wait_for_yes)

logger = logging.getLogger('terminal')


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
    @bot_has_permissions(embed_links=True)
    async def settings(self, ctx):
        """
        Gets the current settings on the server
        To change the settings call `{prefix}{name} subcommand` where you replace
        subcommand with the word in parentheses in the embed
        """
        guild = ctx.guild
        embed = discord.Embed(title='Current settings for %s' % guild.name, description=
                              'To change these settings use {}settings <name> <value>\n'
                              'The name for each setting is specified in brackets\n'
                              'Value depends on the setting.'.format(ctx.prefix))
        fields = OrderedDict([('modlog', 'Moderation log'), ('keeproles', 'Re-add roles to user if they rejoin'),
                              ('prefixes', 'Command prefixes'), ('mute_role', 'Role that is used with timeout, mute, mute_roll'),
                              ('random_color', 'Add a random color to a user when they join'),
                              ('automute', 'Mute on too many mentions in a message'),
                              ('log_unmutes', 'Post message to modlog on unmutes')])
        type_conversions = {True: 'On', False: 'Off', None: 'Not set'}

        def convert_mute_role(r):
            r = guild.get_role(r)
            if not r:
                return 'deleted role'
            if ctx.guild.me.top_role <= r:
                return f'<@&{r.id}> Role is higher than my highest role so I cannot give it to others'

            return '<@&%s>' % r.id

        value_conversions = {'modlog': lambda c: '<#%s>' % c, 'mute_role': convert_mute_role,
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
            success = await self.cache.add_prefix(guild_id, prefix)
        except exceptions.PrefixExists:
            return await ctx.send('Prefix already in use')

        if not success:
            return await ctx.send('Failed to add prefix {}'.format(prefix))

        await ctx.send('Added prefix {}'.format(prefix))

    async def _remove_prefix(self, ctx, guild_id, prefix):
        try:
            success = await self.cache.remove_prefix(guild_id, prefix)
        except exceptions.NotEnoughPrefixes:
            return await ctx.send('Need a minimum of 1 prefix')
        except exceptions.PrefixDoesntExist:
            return await ctx.send("Prefix doesn't exist")

        if not success:
            return await ctx.send('Failed to remove prefix {}'.format(prefix))

        await ctx.send('Removed prefix {}'.format(prefix))

    @cooldown(1, 5, BucketType.guild)
    @group(no_pm=True, invoke_without_command=True, aliases=['prefixes'])
    async def prefix(self, ctx):
        """Shows all the active prefixes on this server"""
        prefixes = self.cache.prefixes(ctx.guild.id)
        await ctx.send(f'Current prefixes on server`{"` `".join(prefixes)}`\n'
                       f'Use `{ctx.prefix}{ctx.invoked_with} add` to add more prefixes')

    @prefix.command(no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_channels=True, manage_guild=True)
    async def add(self, ctx, prefix: str):
        """Add a prefix to this server"""
        await self._add_prefix(ctx, ctx.guild.id, prefix)

    @prefix.command(aliases=['delete', 'del'], no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_channels=True, manage_guild=True)
    async def remove(self, ctx, prefix: str):
        """Remove and active prefix from use"""
        await self._remove_prefix(ctx, ctx.guild.id, prefix)

    @settings.command(no_pm=True, cooldown_after_parsing=True)
    @cooldown(1, 10, type=BucketType.guild)
    @has_permissions(manage_channels=True, manage_guild=True)
    async def modlog(self, ctx, channel: discord.TextChannel=None):
        """If no parameters are passed gets the current modlog
        If channel is provided modlog will be set to that channel.
        channel can be a channel mention, channel id or channel name (case sensitive)
        **Bot needs embed links permissions in modlog**"""
        if channel is None:
            modlog = self.bot.guild_cache.modlog(ctx.guild.id)
            modlog = self.bot.get_channel(modlog)
            if modlog:
                await ctx.send(f'Current modlog channel is {modlog.mention}\n'
                               f'Use `{ctx.prefix}settings {ctx.invoked_with} channel_name` to change it')
            else:
                await ctx.send('No modlog channel set\n'
                               f'Use `{ctx.prefix}settings {ctx.invoked_with} channel_name` to set one')

            ctx.command.reset_cooldown(ctx)
            return

        if not channel.permissions_for(ctx.guild.me).embed_links:
            return await ctx.send(f"Bot doesn't have embed links permissions in {channel.mention}")

        await self.bot.guild_cache.set_modlog(channel.guild.id, channel.id)
        await channel.send('Modlog set to this channel')

    @settings.command(no_pm=True)
    @cooldown(2, 5, type=BucketType.guild)
    @has_permissions(manage_channels=True, manage_guild=True)
    async def log_unmutes(self, ctx, value: bool=None):
        """
        Determines if successful unmutes will be logged to modlog
        If no value is given will say current value
        """

        guild = ctx.guild
        old = self.cache.log_unmutes(guild.id)
        if value is None:
            v = 'enabled' if old else 'disabled'

            await ctx.send(f'Logging unmutes is currently {v}')
            return

        if value == old:
            await ctx.send(f'Value is already set to {"on" if old else "off"}')
            return

        await self.cache.set_log_unmutes(guild.id, value)
        v = 'enabled' if value else 'disabled'
        await ctx.send(f'Logging unmutes is now {v}')

    @settings.command(no_pm=True)
    @cooldown(1, 5, type=BucketType.guild)
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    async def mute_role(self, ctx, *, role: discord.Role=None):
        """Get the current role for muted people on this server or set it by specifying a role
        Mute role is used for timeouts, mutes, automutes and mute_roll"""
        guild = ctx.guild
        if role is None:
            role_id = self.bot.guild_cache.mute_role(guild.id)
            if role_id:
                role = guild.get_role(role_id) or '"Deleted role"'
                await ctx.send(f'Current role for muted people is {role} `{role_id}`\n'
                               f'Specify a role with the command to change it or say `clear` to clear the current role')

                try:
                    msg = await self.bot.wait_for('message', check=basic_check(ctx.author, ctx.channel), timeout=20)
                except TimeoutError:
                    await ctx.send('Cancelling')
                    return

                if msg.content and msg.content.strip().lower() == 'clear':
                    await self.bot.guild_cache.set_mute_role(guild.id, None)
                    await ctx.send('Removed current mute_role')
                    return

            else:
                await ctx.send('No role set for muted people. Specify a role to set it')
            ctx.command.reset_cooldown(ctx)
            return

        if ctx.guild.me.top_role < role:
            return await ctx.send('Mute role is higher than my top role.\n'
                                  'Put it lower so I can give it to users')

        if not await self.bot.guild_cache.set_mute_role(guild.id, role.id):
            return await ctx.send('Error while setting mute role')

        await ctx.send('Muted role set to {0} `{0.id}`'.format(role))

    @cooldown(2, 20, type=BucketType.guild)
    @settings.command(no_pm=True, name='keeproles')
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def keeproles_settings(self, ctx: Context, boolean: bool):
        """Get the current keeproles value on this server or change it.
        Keeproles makes the bot save every users roles so it can give them even if that user rejoins
        but only the roles the bot can give"""
        await self.keeproles.invoke(ctx)

    @cooldown(2, 20, type=BucketType.guild)
    @group(no_pm=True, invoke_without_command=True)
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def keeproles(self, ctx, boolean: bool):
        """Get the current keeproles value on this server or change it.
        Keeproles makes the bot save every users roles so it can give them even if that user rejoins
        but only the roles the bot can give"""
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
                msg = await ctx.send('Indexing roles. This could take a while depending on server size')
                if not await self.bot.dbutils.index_guild_member_roles(guild):
                    return await ctx.send('Failed to index user roles')

                await msg.edit(content='Indexed roles in {0:.2f}s'.format(time.time()-t))
            except discord.DiscordException:
                pass
            finally:
                lock.release()

        await self.cache.set_keeproles(guild.id, boolean)
        await ctx.send('Keeproles set to %s' % str(boolean))

    @cooldown(2, 3, type=BucketType.guild)
    @keeproles.command(name='show', no_pm=True)
    async def keeproles_show(self, ctx: Context, *, user: PossibleUser):
        """
        Shows the saved roles for the given user
        """
        user_id = user if isinstance(user, int) else user.id
        roles = await self.bot.dbutil.get_user_keeproles(ctx.guild.id, user_id)
        if not roles:
            await ctx.send(f'No saved roles found for <@{user_id}>', allowed_mentions=AllowedMentions.none())
            return

        paginator = Paginator(title=f'Saved roles for {user}', page_count=False)
        paginator.add_field('Roles', '')

        for role in roles:
            paginator.add_to_field(f'<@&{role}>\n')

        paginator.finalize()
        for embed in paginator.pages:
            await ctx.send(embed=embed)

    @staticmethod
    def role_check(author: discord.Member, role: discord.Role):
        return author.guild.owner_id == author.id or author.top_role > role

    @cooldown(2, 3, type=BucketType.guild)
    @keeproles.command(name='remove', no_pm=True, aliases=['delete'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    async def keeproles_delete(self, ctx: Context, user: PossibleUser, *, role: discord.Role):
        """
        Removes the role from the user even if they are not in the server
        """
        if not self.role_check(ctx.author, role):
            await ctx.send(f'{role.mention} needs to be lower in the hierarchy than your top role',
                           allowed_mentions=AllowedMentions.none())
            return

        user_id = user if isinstance(user, int) else user.id
        retval = await self.bot.dbutil.delete_user_role(ctx.guild.id, user_id, role.id)
        if retval == 0:
            await ctx.send('No saved roles deleted because the user did not have that role saved')
            return

        try:
            member: discord.Member = await ctx.guild.fetch_member(user_id)
            if role in member.roles:
                await member.remove_roles(role, reason=f'{ctx.author} removed saved role')
        except discord.NotFound:
            pass
        except discord.Forbidden as e:
            await ctx.send(f'Failed to remove role from user\n{e}')
        except discord.HTTPException:
            pass

        await ctx.send(f'Deleted saved role {role.mention} from <@{user_id}>', allowed_mentions=AllowedMentions.none())

    @cooldown(2, 3, type=BucketType.guild)
    @keeproles.command(name='add', no_pm=True, aliases=['give'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    async def keeproles_add(self, ctx: Context, user: PossibleUser, *, role: discord.Role):
        """
        Gives the role to the user even if they are not in the server
        """
        if not self.role_check(ctx.author, role):
            await ctx.send(f'{role.mention} needs to be lower in the hierarchy than your top role',
                           allowed_mentions=AllowedMentions.none())
            return

        user_id = user if isinstance(user, int) else user.id
        retval = await self.bot.dbutil.add_user_role(ctx.guild.id, user_id, role.id)
        if not retval:
            await ctx.send('Failed to add the role to the user')
            return

        try:
            member: discord.Member = await ctx.guild.fetch_member(user_id)
            if role not in member.roles:
                await member.add_roles(role, reason=f'{ctx.author} added saved role')
        except discord.NotFound:
            pass
        except discord.Forbidden as e:
            await ctx.send(f'Failed to add role to user\n{e}')
        except discord.HTTPException:
            pass

        await ctx.send(f'Added saved role {role.mention} to <@{user_id}>', allowed_mentions=AllowedMentions.none())

    @cooldown(2, 3, type=BucketType.guild)
    @keeproles.command(name='copy', no_pm=True)
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def keeproles_copy(self, ctx: Context, base_user: PossibleUser, *, target_user: PossibleUser):
        """
        Copies the roles of one user to another use replacing their existing roles
        """
        guild_id = ctx.guild.id
        target_id = target_user if isinstance(target_user, int) else target_user.id
        base_id = base_user if isinstance(base_user, int) else base_user.id

        roles = await self.bot.dbutil.get_user_keeproles(
            guild_id,
            base_id
        )

        if not roles:
            await ctx.send('No roles found to be copied')
            return

        target_mention = f'<@{target_id}>'
        base_mention = f'<@{base_id}>'
        await ctx.send(f'Copying {len(roles)} roles from {base_mention} to {target_mention}. Do you want to continue?', allowed_mentions=AllowedMentions.none())
        if not (await wait_for_yes(ctx, timeout=20)):
            return

        await self.bot.dbutil.replace_user_keeproles(guild_id, target_id, roles)

        member: Optional[discord.Member] = None
        try:
            member = await ctx.guild.fetch_member(target_id)
        except discord.HTTPException:
            pass

        if member is not None:
            try:
                await member.add_roles([discord.Object(id=r) for r in roles], reason=f'Roles copied by {base_user}', atomic=False)
            except discord.Forbidden as e:
                await ctx.send(f'Did not have permissions to add all of the roles.\n{e}')
                return

            await ctx.send(f'Replaced the roles of {target_mention}', allowed_mentions=AllowedMentions.none())

        else:
            await ctx.send(f'Replaced the keeproles of {target_mention}', allowed_mentions=AllowedMentions.none())

    @settings.command(no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_roles=True, manage_guild=True)
    @bot_has_permissions(manage_roles=True)
    async def random_color(self, ctx, value: bool=None):
        """Check if random color is on or change the current value of it.
        Random color will make the bot give a random color role to all new users who join
        if color roles exist on the server"""
        guild = ctx.guild
        if value is None:
            value = self.cache.random_color(guild.id)
            value = 'on' if value else 'off'
            return await ctx.send('Random color on join is currently ' + value)

        success = await self.cache.set_random_color(guild.id, value)
        if not success:
            return await ctx.send('Failed to change value because of an error')
        value = 'on' if value else 'off'
        await ctx.send('Changed the value to ' + value)

    @settings.command(name='automute')
    async def automute_(self, ctx):
        # No need for checks. The automute command does that for you
        await self.automute.invoke(ctx)

    @group(invoke_without_command=True, no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_roles=True, manage_guild=True)
    @bot_has_permissions(manage_roles=True)
    async def automute(self, ctx, value: bool=None):
        """Check or set the status of automatic muting
        set value to a boolean to change the state between on and off
        Automute only counts role pings that are actual pings and user mentions
        To blacklist a channel from this (makes it so anyone can mention as many things as they like without automute doing anything)
        use `{prefix}automute_blacklist add <channel>`

        To whitelist a role (makes it so anyone who has the role gets ignored by automute)
        use `{prefix}automute_blacklist add <role>`

        Use subcommands to control other settings"""
        guild = ctx.guild
        if value is None:
            guild = ctx.guild
            embed = discord.Embed(title='Current automute settings for %s' % guild.name,
                                  description=
                                  f'To change these values use {ctx.prefix}automute <name> <value>\n'
                                  'The name for each setting is specified in brackets\n'
                                  'Value depends on the setting.')
            fields = OrderedDict([('limit', 'How many mentions needed for an automute to happen'),
                                  ('time', 'How long the mute will last. Infinite if not set')])
            type_conversions = {True: 'On', False: 'Off', None: 'Not set'}

            embed.add_field(name='Automute state', value=type_conversions.get(self.cache.automute(guild.id)))
            for k, v in fields.items():
                value = getattr(self.cache, 'automute_' + k, None)(guild.id)
                if k == 'time' and value:
                    if isinstance(value, str):
                        value = sql2timedelta(value)
                    value = seconds2str(value.total_seconds(), long_def=False)
                else:
                    value = type_conversions.get(value, str(value))

                embed.add_field(name='%s (%s)' % (v, k),
                                value=value,
                                inline=True)

            return await ctx.send(embed=embed)

        success = await self.cache.set_automute(guild.id, value)
        if not success:
            return await ctx.send('Failed to set automute value')

        value = 'on' if value else 'off'
        await ctx.send('Set automute value to ' + value)

    @automute.command()
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_roles=True, manage_guild=True)
    @bot_has_permissions(manage_roles=True)
    async def limit(self, ctx, limit: int=None):
        """Check or set the limit of mentions in a message for the bot to mute a user
        It only counts role mentions that actually ping and user mentions
        """
        guild = ctx.guild
        if limit is None:
            return await ctx.send('Current limit is {}'.format(self.cache.automute_limit(guild.id)))

        if limit <= 4:
            return await ctx.send('Value must be higher than 4')
        if limit > 30:
            return await ctx.send('Value must be equal to or lower than 30')

        success = await self.cache.set_automute_limit(guild.id, limit)

        if not success:
            return ctx.send('Failed to set automute limit')

        await ctx.send('Set automute limit to ' + str(limit))

    @automute.command(no_pnm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_roles=True, manage_guild=True)
    @bot_has_permissions(manage_roles=True)
    async def time(self, ctx, *, mute_time: TimeDelta=None):
        """How long automute timeouts for
        If mute_time is not specified this will set it to perma mute"""

        if mute_time and mute_time.days > 29:
            return await ctx.send('Time must be under 30 days')

        format = timedelta2sql(mute_time) if mute_time else None
        success = await self.cache.set_automute_time(ctx.guild.id, format)
        if not success:
            return await ctx.send('Failed to set time')

        await ctx.send(f'Set mute time to {mute_time if mute_time else "perma mute"}')

    @group(invoke_without_command=True, no_dm=True, aliases=['message_deleted'])
    @cooldown(2, 10, BucketType.guild)
    async def on_delete(self, ctx):
        """
        Gives the current message format that is used when a message is deleted if logging is enabled for deleted messages
        If a format isn't set the default format is used.
        Use subcommands to control options such as message format, channel and whether to use embeds
        To see formatting help use {prefix}formatting
        """
        guild = ctx.guild
        message = self.cache.on_delete_message(guild.id)
        channel = self.cache.on_delete_channel(guild.id)
        embed = self.cache.on_delete_embed(guild.id)
        if message is None:
            message = self.cache.on_delete_message(guild.id, default_message=True)

        if channel is None:
            return await ctx.send("On message delete channel hasn't been set\n"
                                  f"Use `{ctx.prefix}{ctx.invoked_with} channel <channel>` to set one")

        msg = f'Current format in channel <#{channel}>{" using embed" if embed else ""}\n{message}'
        await ctx.send(msg)

    @on_delete.command(name='embed', no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def on_delete_embed(self, ctx, boolean: bool):
        """Make message deletion log use embeds instead of normal messages
        Embeds will always have a local timestamp and user pfp in the appropriate slots
        unlike in a normal message.
        Embeds don't ping either when a message with a ping is deleted"""
        success = await self.cache.set_on_delete_embed(ctx.guild.id, boolean)
        if not success:
            return await ctx.send('Failed to set value')
        await ctx.send(f'Set embeds to {boolean}')

    @on_delete.command(no_dm=True, name='remove', aliases=['del', 'delete'])
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def remove_on_delete(self, ctx):
        """
        Remove message logging from this server.
        The message format will be saved if you decide to use this feature again
        """
        success = await self.cache.set_on_delete_channel(ctx.guild.id, None)
        if not success:
            return await ctx.send('Failed to remove message deletion logging')

        await ctx.send('Remove deleted message logging')

    @on_delete.command(aliases=['message'], no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def set(self, ctx, *, message_format):
        """
        Set the message format for deleted message logging.
        A default format is used if this is not specified
        See {prefix}formatting for more info on how to format messages.
        """
        message = ctx.message
        try:
            formatted = format_on_delete(message, message_format)
        except (AttributeError, KeyError) as e:
            return await ctx.send('Failed to use format because it returned an error.```py\n{}```'.format(e))

        if len(formatted) > 250:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = await self.cache.set_on_delete_message(message.guild.id, message_format)
        if not success:
            await ctx.send('Failed to set message format because of an error')
        else:
            await ctx.send('Successfully set the message format')

    @on_delete.command(no_pm=True)
    @has_permissions(manage_guild=True, manage_channels=True)
    @cooldown(2, 10, BucketType.guild)
    async def channel(self, ctx, *, channel: discord.TextChannel=None):
        """Check or set the channel deleted messages are logged in to"""
        guild = ctx.guild
        if channel is None:
            channel = self.cache.on_delete_channel(guild.id)
            if channel is None:
                await ctx.send('Currently not logging deleted messages')
            else:
                await ctx.send('Currently logging deleted messages to <#{}>'.format(channel))
            return

        success = await self.cache.set_on_delete_channel(guild.id, channel.id)
        if not success:
            await ctx.send('Failed to set channel because of an error')
        else:
            await ctx.send('channel set to {0.name} {0.mention}'.format(channel))

    @group(invoke_without_command=True, no_dm=True, aliases=['message_edited'], no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    async def on_edit(self, ctx):
        """
        Gives the current message format that is used when a message is edited if logging is enabled for edited messages
        Use subcommands to control options such as message format, channel and whether to use embeds

        If a format isn't set the default format is used.
        To see formatting help use {prefix}formatting
        """
        guild = ctx.guild
        message = self.cache.on_edit_message(guild.id)
        channel = self.cache.on_edit_channel(guild.id)
        embed = self.cache.on_edit_embed(guild.id)
        if channel is None:
            return await ctx.send("On message edit channel hasn't been set\n"
                                  f"Use `{ctx.prefix}{ctx.invoked_with} channel <channel>` to set one")
        if message is None:
            message = self.cache.on_edit_message(guild.id, default_message=True)

        msg = f'Current format in channel <#{channel}>{" using embed" if embed else ""}\n{message}'
        await ctx.send(msg)

    @on_edit.command(name='embed', no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def on_edit_embed(self, ctx, boolean: bool):
        """Make message edit log use embeds instead of normal messages
        Embeds will always have a local timestamp and user pfp in the appropriate slots
        unlike in a normal message
        Embeds don't ping either when a message with a ping is deleted"""
        success = await self.cache.set_on_edit_embed(ctx.guild.id, boolean)
        if not success:
            return await ctx.send('Failed to set value')
        await ctx.send(f'Set embeds to {boolean}')

    @on_edit.command(no_dm=True, name='remove', aliases=['del', 'delete'])
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def remove_on_edit(self, ctx):
        """
        Remove edited message logging from this server.
        The message format will be saved if you decide to use this feature again
        """
        success = await self.cache.set_on_edit_channel(ctx.guild.id, None)
        if not success:
            return await ctx.send('Failed to remove message edit logging')

        await ctx.send('Remove edited message logging')

    @on_edit.command(name='set', aliases=['message'], no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def set_(self, ctx, *, message_format):
        """
        Set the message format for edited message logging.
        See {prefix}formatting for more info on how to format messages.
        A default format is used if this is not specified
        """
        message = ctx.message
        try:
            formatted = format_on_edit(message, message, message_format, check_equal=False)
        except (AttributeError, KeyError) as e:
            return await ctx.send('Failed to use format because it returned an error.```py\n{}```'.format(e))

        if len(formatted) > 250:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = await self.cache.set_on_edit_message(message.guild.id, message_format)
        if not success:
            await ctx.send('Failed to set message format because of an error')
        else:
            await ctx.send('Successfully set the message format')

    @on_edit.command(name='channel', no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def channel_(self, ctx, *, channel: discord.TextChannel=None):
        """Check or set the channel message edits are logged to"""
        guild = ctx.guild
        if channel is None:
            channel = self.cache.on_edit_channel(guild.id)
            if channel is None:
                await ctx.send('Currently not logging edited messages')
            else:
                await ctx.send(f'Currently logging edited messages to <#{channel}>')
            return

        success = await self.cache.set_on_edit_channel(guild.id, channel.id)
        if not success:
            await ctx.send('Failed to set channel because of an error')
        else:
            await ctx.send('channel set to {0.name} {0.mention}'.format(channel))

    @command()
    @cooldown(1, 10, BucketType.guild)
    async def delete_format(self, ctx):
        s = test_message(ctx.message)
        await ctx.send(s, allowed_mentions=AllowedMentions.none())

    @command(aliases=['test_delete'])
    @cooldown(1, 10, BucketType.guild)
    async def test_delete_format(self, ctx, *, delete_message):
        s = format_on_delete(ctx.message, delete_message)
        await ctx.send(s, allowed_mentions=AllowedMentions.none())

    @command()
    @cooldown(1, 10, BucketType.guild)
    async def edit_format(self, ctx):
        s = test_message(ctx.message, True)
        await ctx.send(s, allowed_mentions=AllowedMentions.none())

    @command(aliases=['test_edit'])
    @cooldown(1, 10, BucketType.guild)
    async def test_edit_format(self, ctx, *, edit_message):
        s = format_on_edit(ctx.message, ctx.message, edit_message, check_equal=False)
        await ctx.send(s, allowed_mentions=AllowedMentions.none())

    @command()
    @cooldown(1, 10, BucketType.guild)
    async def join_format(self, ctx):
        s = test_member(ctx.author)
        await ctx.send(s, allowed_mentions=AllowedMentions.none())

    @command(aliases=['test_join'])
    @cooldown(2, 5, BucketType.guild)
    async def test_join_format(self, ctx, *, join_message):
        formatted = format_join_leave(ctx.author, join_message)
        if len(formatted) > 1000:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        await ctx.send(formatted, allowed_mentions=AllowedMentions.none())

    @group(invoke_without_command=True, aliases=['on_join', 'welcome_message'])
    @cooldown(2, 10, BucketType.guild)
    async def join_message(self, ctx):
        """Get the welcome/join message on this server
        Use subcommands to set values for welcome message options"""
        guild = ctx.guild
        message = self.cache.join_message(guild.id)
        channel = self.cache.join_channel(guild.id)
        if message is None and channel is None:
            return await ctx.send("Member join channel hasn't been set\n"
                                  f"Use `{ctx.prefix}{ctx.invoked_with} channel <channel>` to set one")
        elif message is None:
            message = self.cache.join_message(guild.id, default_message=True)

        msg = 'Current format in channel <#{}>\n{}'.format(channel, message)
        await ctx.send(msg, allowed_mentions=AllowedMentions.none())

    @cooldown(1, 10, BucketType.guild)
    @join_message.command(name='remove', aliases=['del', 'delete'], no_pm=True)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def remove_join(self, ctx):
        """
        Remove welcome message from this server
        The message format will be saved if you decide to use this feature again
        """
        success = await self.cache.set_join_channel(ctx.guild.id, None)
        if not success:
            return await ctx.send('Failed to remove welcome message')

        await ctx.send('Remove welcome message')

    @join_message.command(name='set', aliases=['message'], no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def join_set(self, ctx, *, message):
        """Set the welcome message on this server
        See {prefix}join_format for help on formatting the message"""
        guild = ctx.guild
        try:
            formatted = format_join_leave(ctx.author, message)
        except (AttributeError, KeyError) as e:
            return await ctx.send('Failed to use format because it returned an error.```py\n{}```'.format(e))

        if len(formatted) > 1000:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = await self.cache.set_join_message(guild.id, message)
        if not success:
            await ctx.send('Failed to set message format because of an error')
        else:
            await ctx.send('Successfully set the message format')

    @join_message.command(name='channel', no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def join_channel(self, ctx, *, channel: discord.TextChannel=None):
        """Check or set the join/welcome message channel"""
        guild = ctx.guild
        if channel is None:
            channel = self.cache.join_channel(guild.id)
            if channel is None:
                await ctx.send('Currently not logging members who join')
            else:
                await ctx.send('Currently logging members who join in <#{}>'.format(channel))
            return

        success = await self.cache.set_join_channel(guild.id, channel.id)
        if not success:
            await ctx.send('Failed to set channel because of an error')
        else:
            await ctx.send('channel set to {0.name} {0.mention}'.format(channel))

    @group(invoke_without_command=True, aliases=['on_leave'], no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    async def leave_message(self, ctx):
        """Get the current message that is sent when a user leaves the server"""
        guild = ctx.guild
        message = self.cache.leave_message(guild.id)
        channel = self.cache.leave_channel(guild.id)
        if message is None and channel is None:
            return await ctx.send("Member leave channel hasn't been set\n"
                                  f"Use `{ctx.prefix}{ctx.invoked_with} channel <channel>` to set one")
        elif message is None:
            message = self.cache.leave_message(guild.id, default_message=True)

        await ctx.send(f'Current format in channel <#{channel}>\n{message}')

    @leave_message.command(name='remove', no_pm=True, aliases=['del', 'delete'])
    @cooldown(1, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def remove_leave(self, ctx):
        """
        Remove leave message from this server
        The message format will be saved if you decide to use this feature again
        """
        success = await self.cache.set_leave_channel(ctx.guild.id, None)
        if not success:
            return await ctx.send('Failed to remove leave message')

        await ctx.send('Remove leave message')

    @leave_message.command(name='set', aliases=['message'], no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def leave_set(self, ctx, *, message):
        """Set the leave message on this server
        See {prefix}join_format for help on formatting the message"""
        guild = ctx.guild
        try:
            formatted = format_join_leave(ctx.author, message)
        except (AttributeError, KeyError) as e:
            return await ctx.send('Failed to use format because it returned an error.```py\n{}```'.format(e))

        splitted = split_string(formatted, splitter='\n')
        if len(splitted) > 1:
            return await ctx.send('The message generated using this format is too long. Please reduce the amount of text/variables')

        success = await self.cache.set_leave_message(guild.id, message)
        if not success:
            await ctx.send('Failed to set message format because of an error')
        else:
            await ctx.send('Successfully set the message format')

    @leave_message.command(name='channel', no_pm=True)
    @cooldown(2, 10, BucketType.guild)
    @has_permissions(manage_guild=True, manage_channels=True)
    async def leave_channel(self, ctx, *, channel: discord.TextChannel=None):
        """Set the channel that user leave messages are sent to"""
        guild = ctx.guild
        if channel is None:
            channel = self.cache.leave_channel(guild.id)
            if channel is None:
                await ctx.send('Currently not logging members who leave')
            else:
                await ctx.send('Currently logging members who leave in <#{}>'.format(channel))
            return

        success = await self.cache.set_leave_channel(guild.id, channel.id)
        if not success:
            await ctx.send('Failed to set channel because of an error')
        else:
            await ctx.send('channel set to {0.name} {0.mention}'.format(channel))


def setup(bot):
    bot.add_cog(Settings(bot))
