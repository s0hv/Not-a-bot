import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from random import randint, random
from typing import Union, List, Optional

import discord
from asyncpg.exceptions import PostgresError
from discord.ext.commands import BucketType, Greedy

from bot.bot import (command, group, has_permissions, cooldown,
                     bot_has_permissions, Context)
from bot.converters import MentionedMember, PossibleUser, TimeDelta
from bot.formatter import Paginator, EmbedLimits
from bot.globals import DATA
from cogs.cog import Cog
from utils.utilities import (call_later, parse_timeout,
                             get_avatar, is_image_url,
                             seconds2str, get_channel, Snowflake, basic_check,
                             sql2timedelta, check_botperm, format_timedelta,
                             DateAccuracy, send_paged_message, split_string)

logger = logging.getLogger('terminal')
manage_roles = discord.Permissions(268435456)
lock_perms = discord.Permissions(268435472)
penile_regex = re.compile(r'(\.(image|im|photo|img)) +penile hemorrhage', re.I)


class Moderator(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.timeouts = self.bot.timeouts
        self.temproles = self.bot.temproles
        self.automute_blacklist = {}
        self.automute_whitelist = {}
        self._current_rolls = {}  # Users currently active in a mute roll
        # Delay used to update expiring events. 30min
        self._pause = 1800

        asyncio.run_coroutine_threadsafe(self._load_automute(), loop=bot.loop).result()
        self._event_loop = asyncio.run_coroutine_threadsafe(self.load_expiring_events(), loop=bot.loop)

    def cog_unload(self):
        self._event_loop.cancel()

        for timeouts in list(self.timeouts.values()):
            for timeout in list(timeouts.values()):
                timeout.cancel()

        for guild_temproles in list(self.temproles.values()):
            for user_temproles in list(guild_temproles.values()):
                for temprole in list(user_temproles.values()):
                    temprole.cancel()

    async def _load_automute(self):
        sql = 'SELECT * FROM automute_blacklist'

        rows = await self.bot.dbutil.fetch(sql)
        for row in rows:
            id_ = row['guild']
            if id_ not in self.automute_blacklist:
                s = set()
                self.automute_blacklist[id_] = s

            else:
                s = self.automute_blacklist[id_]

            s.add(row['channel'])

        sql = 'SELECT * FROM automute_whitelist'
        rows = await self.bot.dbutil.fetch(sql)
        for row in rows:
            id_ = row['guild']
            if id_ not in self.automute_whitelist:
                s = set()
                self.automute_whitelist[id_] = s

            else:
                s = self.automute_whitelist[id_]

            s.add(row['role'])

    async def load_expiring_events(self):
        # Load events that expire in an hour
        expiry = timedelta(hours=1)
        self._pause = expiry.total_seconds()//2

        while True:
            await self._load_timeouts(expiry)
            await self._load_temproles(expiry)

            await asyncio.sleep(self._pause)

    async def _load_temproles(self, expires_in: timedelta):
        date = datetime.utcnow() + expires_in
        sql = 'SELECT * FROM temproles WHERE expires_at < $1'
        rows = await self.bot.dbutil.fetch(sql, (date,))

        for row in rows:
            time = row['expires_at'] - datetime.utcnow()
            guild = row['guild']
            user = row['uid']
            role = row['role']

            self.register_temprole(user, role, guild, time.total_seconds(), ignore_dupe=True)

    async def _load_timeouts(self, expires_in: timedelta):
        date = datetime.utcnow() + expires_in
        sql = 'SELECT * FROM timeouts WHERE expires_on < $1'
        rows = await self.bot.dbutil.fetch(sql, (date,))
        for row in rows:
            time = row['expires_on'] - datetime.utcnow()
            guild = row['guild']
            user = row['uid']

            self.register_timeout(user, guild, time.total_seconds(), ignore_dupe=True)

    async def send_to_modlog(self, guild, *args, **kwargs):
        if isinstance(guild, int):
            guild = self.bot.get_guild(guild)
            if not guild:
                return

        channel = self.get_modlog(guild)
        if channel is None:
            return

        perms = channel.permissions_for(channel.guild.get_member(self.bot.user.id))
        is_embed = 'embed' in kwargs
        if not perms.send_messages:
            return

        if is_embed and not perms.embed_links:
            return

        try:
            return await channel.send(*args, **kwargs)
        except discord.HTTPException:
            pass

    @Cog.listener()
    async def on_message(self, message):
        guild = message.guild
        if guild and self.bot.guild_cache.automute(guild.id):
            if message.webhook_id:
                return

            mute_role = self.bot.guild_cache.mute_role(guild.id)
            mute_role = discord.utils.find(lambda r: r.id == mute_role, message.guild.roles)
            if not mute_role:
                return

            user = message.author
            if not isinstance(user, discord.Member):
                logger.debug(f'User found when expected member guild {guild.name} user {user} in channel {message.channel.name}')
                user = guild.get_member(user.id)
                if not user:
                    return

            if not check_botperm('manage_roles', guild=message.guild, channel=message.channel):
                return

            is_muted = mute_role in user.roles

            # check for search of that
            if guild.id == 217677285442977792 and penile_regex.match(message.content):
                def check(msg):
                    if msg.author.id != 439205512425504771 or msg.channel != message.channel:
                        return False

                    if not msg.embeds or not msg.embeds[0].author:
                        return False

                    embed = msg.embeds[0]
                    if embed.title != 'Image Search Results' or (isinstance(embed.author.icon_url, str) and str(user.id) not in embed.author.icon_url):
                        return False

                    return True

                try:
                    msg = await self.bot.wait_for('message', check=check, timeout=20)
                except asyncio.TimeoutError:
                    return

                await msg.delete()

                if is_muted:
                    return

                time = timedelta(days=3)
                await message.author.add_roles(mute_role, reason=f'[Automute] {message.content}')
                d = f'Automuted user {user} `{user.id}` for {time}'
                url = f'[Jump to](https://discordapp.com/channels/{guild.id}/{message.channel.id}/{message.id})'
                embed = discord.Embed(title='Moderation action [AUTOMUTE]', description=d,
                                      timestamp=datetime.utcnow())
                embed.add_field(name='Reason', value=message.content)
                embed.add_field(name='Link', value=url)
                embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                embed.set_footer(text=str(self.bot.user),
                                 icon_url=self.bot.user.avatar_url or self.bot.user.default_avatar_url)
                msg = await self.send_to_modlog(guild, embed=embed)
                await self.add_timeout(await self.bot.get_context(message), guild.id, user.id,
                                       datetime.utcnow() + time, time.total_seconds(),
                                       reason=f'Automuted for {message.content}',
                                       author=guild.me,
                                       modlog_msg=msg.id if msg else None)
                return

            if is_muted:
                return

            limit = self.bot.guild_cache.automute_limit(guild.id)
            if len(message.mentions) + len(message.role_mentions) >= limit:
                blacklist = self.automute_blacklist.get(guild.id, ())

                if message.channel.id not in blacklist:
                    whitelist = self.automute_whitelist.get(guild.id, ())
                    invulnerable = discord.utils.find(lambda r: r.id in whitelist,
                                                      user.roles)

                    if invulnerable is None:
                        time = self.bot.guild_cache.automute_time(guild.id)

                        if time is not None:
                            if isinstance(time, str):
                                time = sql2timedelta(time)
                            d = 'Automuted user {0} `{0.id}` for {1}'.format(message.author, time)
                        else:
                            d = 'Automuted user {0} `{0.id}`'.format(message.author)

                        url = f'[Jump to](https://discordapp.com/channels/{guild.id}/{message.channel.id}/{message.id})'
                        reason = 'Too many mentions in a message'
                        await message.author.add_roles(mute_role, reason='[Automute] too many mentions in message')
                        embed = discord.Embed(title='Moderation action [AUTOMUTE]', description=d, timestamp=datetime.utcnow())
                        embed.add_field(name='Reason', value=reason)
                        embed.add_field(name='Link', value=url)
                        embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                        embed.set_footer(text=str(self.bot.user), icon_url=self.bot.user.avatar_url or self.bot.user.default_avatar_url)
                        msg = await self.send_to_modlog(guild, embed=embed)
                        if time:
                            await self.add_timeout(await self.bot.get_context(message),
                                                   guild.id, user.id,
                                                   datetime.utcnow() + time,
                                                   time.total_seconds(),
                                                   reason=reason,
                                                   author=guild.me,
                                                   modlog_msg=msg.id if msg else None)
                        else:
                            await self.add_mute_reason(await self.bot.get_context(message),
                                                       user.id,
                                                       reason=reason,
                                                       author=guild.me,
                                                       modlog_message_id=msg.id if msg else None)
                        return

    @group(invoke_without_command=True, name='automute_whitelist', aliases=['mute_whitelist'], no_pm=True)
    @cooldown(2, 5, BucketType.guild)
    async def automute_whitelist_(self, ctx):
        """Show roles whitelisted from automutes"""
        guild = ctx.guild
        roles = self.automute_whitelist.get(guild.id, ())
        roles = map(guild.get_role, roles)
        roles = [r for r in roles if r]
        if not roles:
            return await ctx.send('No roles whitelisted from automutes')

        msg = 'Roles whitelisted from automutes'
        for r in roles:
            msg += '\n{0.name} `{0.id}`'.format(r)

        await ctx.send(msg)

    @automute_whitelist_.command(no_pm=True)
    @has_permissions(manage_guild=True, manage_roles=True)
    @cooldown(2, 5, BucketType.guild)
    async def add(self, ctx, *, role: discord.Role):
        """Add a role to the automute whitelist"""
        guild = ctx.guild
        roles = self.automute_whitelist.get(guild.id)
        if roles is None:
            roles = set()
            self.automute_whitelist[guild.id] = roles

        if len(roles) >= 10:
            return await ctx.send('Maximum of 10 roles can be added to automute whitelist.')

        if ctx.author != guild.owner and ctx.author.top_role <= role:
            return await ctx.send('The role you are trying to add is higher than your top role in the hierarchy')

        success = await self.bot.dbutils.add_automute_whitelist(guild.id, role.id)
        if not success:
            return await ctx.send('Failed to add role because of an error')

        roles.add(role.id)
        await ctx.send('Added role {0.name} `{0.id}`'.format(role))

    @automute_whitelist_.command(aliases=['del', 'delete'], no_pm=True)
    @has_permissions(manage_guild=True, manage_roles=True)
    @cooldown(2, 5, BucketType.guild)
    async def remove(self, ctx, *, role: discord.Role):
        """Remove a role from the automute whitelist"""
        guild = ctx.guild
        roles = self.automute_whitelist.get(guild.id, ())

        if role.id not in roles:
            return await ctx.send('Role {0.name} not found in whitelist'.format(role))

        if ctx.author.top_role <= role:
            return await ctx.send('The role you are trying to remove is higher than your top role in the hierarchy')

        success = await self.bot.dbutils.remove_automute_whitelist(guild.id, role.id)
        if not success:
            return await ctx.send('Failed to remove role because of an error')

        roles.discard(role.id)
        await ctx.send('Role {0.name} `{0.id}` removed from automute whitelist'.format(role))

    @group(invoke_without_command=True, name='automute_blacklist', aliases=['mute_blacklist'], no_pm=True)
    @cooldown(2, 5, BucketType.guild)
    async def automute_blacklist_(self, ctx):
        """Show channels that are blacklisted from automutes.
        That means automutes won't triggered from messages sent in those channels"""
        guild = ctx.guild
        channels = self.automute_blacklist.get(guild.id, ())
        channels = map(guild.get_channel, channels)
        channels = [c for c in channels if c]
        if not channels:
            return await ctx.send('No channels blacklisted from automutes')

        msg = 'Channels blacklisted from automutes'
        for c in channels:
            msg += '\n{0.name} `{0.id}`'.format(c)

        await ctx.send(msg)

    @automute_blacklist_.command(name='add', no_pm=True)
    @has_permissions(manage_guild=True, manage_roles=True)
    @cooldown(2, 5, BucketType.guild)
    async def add_(self, ctx, *, channel: discord.TextChannel):
        """Add a channel to the automute blacklist"""
        guild = ctx.guild
        channels = self.automute_blacklist.get(guild.id)
        if channels is None:
            channels = set()
            self.automute_whitelist[guild.id] = channels

        success = await self.bot.dbutils.add_automute_blacklist(guild.id, channel.id)
        if not success:
            return await ctx.send('Failed to add channel because of an error')

        channels.add(channel.id)
        await ctx.send('Added channel {0.name} `{0.id}`'.format(channel))

    @automute_blacklist_.command(name='remove', aliases=['del', 'delete'], no_pm=True)
    @has_permissions(manage_guild=True, manage_roles=True)
    @cooldown(2, 5, BucketType.guild)
    async def remove_(self, ctx, *, channel):
        """Remove a channel from the automute blacklist"""
        guild = ctx.guild
        channels = self.automute_blacklist.get(guild.id, ())
        channel_ = get_channel(guild.channels, channel, name_matching=True)
        if not channel_:
            return await ctx.send('Channel {} not found'.format(channel))

        if channel_.id not in channels:
            return await ctx.send('Channel {0.name} not found in blacklist'.format(channel_))

        success = await self.bot.dbutils.remove_automute_blacklist(guild.id, channel.id)
        if not success:
            return await ctx.send('Failed to remove channel because of an error')

        channels.discard(channel.id)
        await ctx.send('Channel {0.name} `{0.id}` removed from automute blacklist'.format(channel_))

    # Required perms: manage roles
    @command(no_pm=True)
    @cooldown(2, 5, BucketType.guild)
    @bot_has_permissions(manage_roles=True)
    @has_permissions(manage_roles=True)
    async def add_role(self, ctx, name, random_color=True, mentionable=False, hoist=False):
        """Add a role to the server.
        random_color makes the bot choose a random color for the role and
        hoist will make the role show up in the member list"""
        guild = ctx.guild
        if guild is None:
            return await ctx.send('Cannot create roles in DM')

        default_perms = guild.default_role.permissions
        if random_color:
            color = discord.Color(randint(1, 16777215))
        else:
            color = discord.Color.default()

        try:
            r = await guild.create_role(name=name, permissions=default_perms, colour=color,
                                        mentionable=mentionable, hoist=hoist,
                                        reason=f'responsible user {ctx.author} {ctx.author.id}')
        except discord.HTTPException as e:
            return await ctx.send('Could not create role because of an error\n```%s```' % e)

        await ctx.send('Successfully created role %s `%s`' % (name, r.id))

    async def _mute_check(self, ctx):
        guild = ctx.guild
        mute_role = self.bot.guild_cache.mute_role(guild.id)
        if mute_role is None:
            await ctx.send(f'No mute role set. You can set it with {ctx.prefix}settings mute_role role name')
            return False

        mute_role = guild.get_role(mute_role)
        if mute_role is None:
            await ctx.send('Could not find the mute role')
            return False

        return mute_role

    @command(no_pm=True)
    @bot_has_permissions(manage_roles=True)
    @has_permissions(manage_roles=True)
    async def mute(self, ctx, users: Greedy[MentionedMember], *, reason):
        """
        Mute a user(s). Only works if the server has set the mute role.
        Maximum amount of users muted at once is 10
        """
        if not users:
            ctx.command.reset_cooldown(ctx)
            await ctx.send('No users given to mute')
            return

        if len(users) > 10:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f'Tried to mute {len(users)} users while maximum amount is 10')
            return

        mute_role = await self._mute_check(ctx)
        if not mute_role:
            return

        guild = ctx.guild
        reason = reason if reason else 'No reason <:HYPERKINGCRIMSONANGRY:356798314752245762>'
        guild_timeouts = self.timeouts.get(guild.id, {})
        muted_users = []
        failed = []

        for user in users:
            if guild.id == 217677285442977792 and user.id == 123050803752730624:
                failed.append(f"Couldn't mute {user}. Not today kiddo. I'm too powerful for you")
                continue

            if guild.id == 217677285442977792 and ctx.author.id == 117256618617339905 and user.id == 189458911886049281:
                failed.append(f"Couldn't mute {user}. No <:peepoWeird:423445885180051467>")
                continue

            if ctx.author != guild.owner and ctx.author.top_role <= user.top_role:
                failed.append(f'{user} is higher or same as you in the role hierarchy')
                continue

            try:
                await user.add_roles(mute_role, reason=f'[{ctx.author}] {reason}')
                muted_users.append(user)
            except discord.HTTPException:
                failed.append(f'Could not mute user {user}')
                continue

            task = guild_timeouts.get(user.id)
            if task:
                task.cancel()
            await self.remove_timeout(user.id, guild.id)

        author = ctx.author

        if muted_users:
            user_string = '\n'.join(map(lambda u: f'{u} `{u.id}`', muted_users))
            description = f'{author.mention} muted {user_string}'
            url = f'[Jump to](https://discordapp.com/channels/{guild.id}/{ctx.channel.id}/{ctx.message.id})'
            embed = discord.Embed(title='🤐 Moderation action [MUTE]',
                                  timestamp=datetime.utcnow(),
                                  description=description)
            embed.add_field(name='Reason', value=reason)
            embed.add_field(name='Link', value=url)

            if len(muted_users) == 1:
                usr = muted_users[0]
                embed.set_thumbnail(url=usr.avatar_url or usr.default_avatar_url)

            embed.set_footer(text=str(author), icon_url=author.avatar_url or author.default_avatar_url)
            msg = await self.send_to_modlog(guild, embed=embed)

            for user in muted_users:
                await self.add_mute_reason(ctx, user.id, reason,
                                           modlog_message_id=msg.id if msg else None)

        s = ""
        if muted_users:
            s += "Muted user" + ("s " if len(muted_users) > 1 else " ")
            s += ', '.join(map(str, muted_users)) + '\n'

        if failed:
            s += "\n".join(failed)

        await ctx.send(s)

    @command(no_dm=True)
    @cooldown(2, 3, BucketType.guild)
    @bot_has_permissions(manage_roles=True)
    async def mute_roll(self, ctx, user: discord.Member, minutes: int):
        """Challenge another user to a game where the loser gets muted for the specified amount of time
        ranging from 10 to 60 minutes"""
        if not 9 < minutes < 61:
            return await ctx.send('Mute length should be between 10 and 60 minutes')

        if ctx.author == user:
            return await ctx.send("Can't play yourself")

        if user.bot:
            return await ctx.send("Can't play against a bot since most don't have a free will")

        mute_role = await self._mute_check(ctx)
        if not mute_role:
            return

        if mute_role in user.roles or mute_role in ctx.author.roles:
            return await ctx.send('One of the participants is already muted')

        if ctx.guild.id not in self._current_rolls:
            state = set()
            self._current_rolls[ctx.guild.id] = state
        else:
            state = self._current_rolls[ctx.guild.id]

        if user.id in state or ctx.author.id in state:
            return await ctx.send('One of the users is already participating in a roll')

        state.add(user.id)
        state.add(ctx.author.id)

        try:
            await ctx.send(f'{user.mention} type accept to join this mute roll of {minutes} minutes')

            _check_recipient = basic_check(user, ctx.channel)
            _check_author = basic_check(ctx.author, ctx.channel)

            # Will return true only when a valid message is given
            # This means message author can't accept mute roll in behalf of the other
            def check(msg):
                is_author = False
                # Check who is the author
                if not _check_recipient(msg):
                    if _check_author(msg):
                        is_author = True
                    else:
                        return

                content = msg.content.lower()
                deny = content in ('reject', 'no', 'deny', 'decline', 'i refuse')
                accept = content == 'accept'

                # Only accept initiating the mute_roll from the recipient
                return (not is_author and accept) or deny

            try:
                msg = await self.bot.wait_for('message', check=check, timeout=120)
            except asyncio.TimeoutError:
                return await ctx.send('Took too long.')

            if msg.content.lower() != 'accept':
                return await ctx.send(f'{msg.author} declined')

            td = timedelta(minutes=minutes)

            expires_on = datetime.utcnow() + td
            msg = await ctx.send(f'{user} vs {ctx.author}\nLoser: <a:loading:449907001569312779>')
            await asyncio.sleep(2)
            counter = True
            counter_counter = random() < 0.01
            if not counter_counter:
                counter = random() < 0.05

            choices = [user, ctx.author]

            if random() < 0.5:
                loser = 0
            else:
                loser = 1

            await msg.edit(content=f'{user} vs {ctx.author}\nLoser: {choices[loser]}')

            perms = ctx.channel.permissions_for(ctx.guild.me)

            if counter:
                p = os.path.join(DATA, 'templates', 'reverse.png')
                await asyncio.sleep(2)

                if perms.attach_files:
                    await ctx.send(f'{choices[loser]} counters', file=discord.File(p))
                else:
                    await ctx.send(f'{choices[loser]} counters. (No image perms so text only counter)')

                loser = abs(loser - 1)
                await msg.edit(content=f'{user} vs {ctx.author}\nLoser: {choices[loser]}')

            if counter_counter:
                p = os.path.join(DATA, 'templates', 'counter_counter.png')
                await asyncio.sleep(2)

                if perms.attach_files:
                    await ctx.send(f'{choices[loser]} counters the counter', file=discord.File(p))
                else:
                    await ctx.send(f'{choices[loser]} counters the counter. (No image perms so text only counter)')

                loser = abs(loser - 1)
                await msg.edit(content=f'{user} vs {ctx.author}\nLoser: {choices[loser]}')

            loser = choices[loser]
            await asyncio.sleep(3)
            if mute_role in user.roles or mute_role in ctx.author.roles:
                return await ctx.send('One of the participants is already muted')

            choices.remove(loser)
            await self.add_timeout(ctx, ctx.guild.id, loser.id, expires_on, td.total_seconds(),
                                   reason=f'Lost mute roll to {choices[0]}',
                                   author=ctx.guild.me,
                                   show_in_logs=False)
            try:
                await loser.add_roles(mute_role, reason=f'Lost mute roll to {ctx.author}')
            except discord.DiscordException:
                return await ctx.send('Failed to mute loser')

            await self.bot.dbutil.increment_mute_roll(ctx.guild.id, ctx.author.id, loser != ctx.author)
            await self.bot.dbutil.increment_mute_roll(ctx.guild.id, user.id, loser != user)
        finally:
            state.discard(user.id)
            state.discard(ctx.author.id)

    async def remove_timeout(self, user_id, guild_id, return_info=False):
        """

        Args:
            user_id: id of user
            guild_id: id of guild
            return_info: If set to true will return info related on the timeout.
                Returned fields are expires_on, reason, author, embed and time.
                Do note that this makes the underlying sql query a lot more complex

        Returns:

        """

        logger.debug(f'Removing timeout of {user_id} in guild {guild_id}')
        try:
            if return_info:
                sql = 'DELETE FROM timeouts t USING timeout_logs tl ' \
                      'WHERE tl.id=(SELECT MAX(id) FROM timeout_logs WHERE guild=$1 AND uid=$2) ' \
                      'AND tl.guild=t.guild AND tl.uid=t.uid ' \
                      'RETURNING t.expires_on, tl.reason, tl.author, tl.embed, tl.time'
                return await self.bot.dbutil.fetch(sql, (guild_id, user_id), fetchmany=False)
            else:
                sql = 'DELETE FROM timeouts WHERE guild=$1 AND uid=$2'
                await self.bot.dbutil.execute(sql, (guild_id, user_id))
        except PostgresError:
            logger.exception('Could not delete untimeout')

    async def add_timeout(self, ctx, guild_id, user_ids, expires_on, as_seconds,
                          reason='No reason', author=None, modlog_msg=None, show_in_logs=True):
        """
        Args:
            user_ids (int or list[int]): User id(s) to be muted
        """

        try:
            await self.add_mute_reason(ctx, user_ids, reason, author=author,
                                       modlog_message_id=modlog_msg,
                                       duration=as_seconds,
                                       show_in_logs=show_in_logs)

            await self.bot.dbutil.add_timeout(guild_id, user_ids, expires_on)
        except PostgresError:
            logger.exception('Could not save timeout')
            await ctx.send('Could not save timeout. Canceling action')
            return False

        if isinstance(user_ids, int):
            user_ids = (user_ids, )

        for user_id in user_ids:
            self.register_timeout(user_id, guild_id, as_seconds)

        return True

    async def untimeout(self, user_id, guild_id):
        mute_role = self.bot.guild_cache.mute_role(guild_id)
        if mute_role is None:
            await self.remove_timeout(user_id, guild_id)
            return

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            logger.warning(f'Guild {guild_id} not found. Only removing timeout from database')
            await self.remove_timeout(user_id, guild_id)
            return

        if guild.get_role(mute_role):
            try:
                guild_id = guild.id
                # use a raw request as cache isn't always up to date
                await self.bot.http.remove_role(guild_id, user_id, mute_role, reason='Unmuted')
                # await user.remove_roles(Snowflake(mute_role), reason='Unmuted')
            except (discord.Forbidden, discord.NotFound):
                pass
            except discord.HTTPException:
                logger.exception(f'Could not autounmute user {user_id}')
        await self.remove_timeout(user_id, guild.id)

    @command(no_pm=True)
    @bot_has_permissions(manage_channels=True)
    @has_permissions(manage_channels=True)
    async def slowmode(self, ctx, time: int):
        try:
            await ctx.channel.edit(slowmode_delay=time)
        except discord.HTTPException as e:
            await ctx.send(f'Failed to set slowmode because of an error\n{e}')
        else:
            await ctx.send(f'Slowmode set to {time}s')

    @staticmethod
    def _reason_url(ctx, reason):
        embed = None

        if ctx.message.attachments:
            for a in ctx.message.attachments:
                if a.width:
                    embed = a.url
                    break

        else:
            for s in reason.split(' '):
                url = s.strip('\n')
                if is_image_url(url):
                    embed = url
                    break

        return embed

    async def add_mute_reason(self, ctx, user_id, reason, author=None, modlog_message_id=None,
                              duration=None, show_in_logs=True):
        embed = self._reason_url(ctx, reason)
        await self.bot.dbutil.add_timeout_log(ctx.guild.id, user_id,
                                              author.id if author else ctx.author.id,
                                              reason, embed, ctx.message.created_at,
                                              modlog_message_id,
                                              duration, show_in_logs)

    async def edit_mute_reason(self, ctx, user_id, reason):
        embed = self._reason_url(ctx, reason)
        return await self.bot.dbutil.edit_timeout_log(ctx.guild.id, user_id, ctx.author.id,
                                                      reason, embed)

    def format_tlog_message(self, rows, title, fmt):
        paginator = Paginator(title=title, init_page=False)

        description = ''
        for row in rows:
            time = format_timedelta(datetime.utcnow() - row['time'], DateAccuracy.Day)
            if row['duration']:
                duration = 'for '
                duration += format_timedelta(timedelta(seconds=row['duration']), DateAccuracy.Day-DateAccuracy.Hour)
            else:
                duration = 'permanently'
            author = self.bot.get_user(row['author'])
            description += fmt.format(time=time, author=author or row['author'],
                                           reason=row['reason'], duration=duration,
                                           id=row['id'], uid=row['uid'])

        paginator.add_page(description=description, paginate_description=True)
        paginator.finalize()
        return paginator.pages

    @group(aliases=['tlogs'], invoke_without_command=True)
    @bot_has_permissions(embed_links=True)
    @cooldown(1, 6, BucketType.user)
    async def timeout_logs(self, ctx, *, user: PossibleUser=None):
        """
        Show timeouts for the specified user
        Use `{prefix}{name} by` to see timeouts done by a specific user
        """
        user = user or ctx.author
        user_id = user if isinstance(user, int) else user.id
        rows = await self.bot.dbutil.get_timeout_logs(ctx.guild.id, user_id, self.bot.user.id)
        if rows is False:
            return await ctx.send(f'Failed to get timeout logs for user {user}')

        if not rows:
            return await ctx.send(f'No timeouts for {user}')

        pages = self.format_tlog_message(rows, f'Timeouts for {user}',
                                         '`{id}` {time} ago {duration} by {author} for the reason "{reason}"\n')

        await send_paged_message(ctx, pages, embed=True)

    @timeout_logs.command(name='remove', aliases=['r', 'delete'])
    @cooldown(1, 5, BucketType.user)
    async def remove_tlog(self, ctx, *ids: int):
        """
        Delete timeouts made by you with the given ids
        You can find the ids by using tlogs command. They're the numbers on
        the left side before all the other info.
        If you're a server admin you can delete logs from any user in your guild
        """
        if not ids:
            await ctx.send('No ids given')
            return

        author = ctx.author
        is_admin = author.guild_permissions.administrator
        ids = ', '.join(map(str, ids))

        if is_admin:
            where = f'guild={ctx.guild.id} AND '
        else:
            where = f'author={author.id} AND '

        where += f' id IN ({ids})'

        rows = await self.bot.dbutil.remove_tlogs(where)

        if rows is False:
            await ctx.send('Failed to delete records because of an error')
            return

        await ctx.send(f'Successfully deleted {rows} tlog entries')

    @timeout_logs.command(name='by', aliases=['from'])
    @cooldown(1, 5, BucketType.user)
    async def tlogs_by(self, ctx, *, user: PossibleUser=None):
        """Shows timeouts done by the specified user"""
        user = user or ctx.author
        rows = await self.bot.dbutil.get_timeout_logs_by(ctx.guild.id, user.id)
        if rows is False:
            return await ctx.send(f'Failed to get timeout logs by user {user}')

        if not rows:
            return await ctx.send(f'No timeouts by {user}')

        pages = self.format_tlog_message(rows, f'Timeouts by {user}',
                                         '`{id}` <@{uid}> {time} ago {duration} for the reason "{reason}"\n')

        await send_paged_message(ctx, pages, embed=True)

    @command(aliases=['temp_mute'], no_pm=True)
    @bot_has_permissions(manage_roles=True)
    @has_permissions(manage_roles=True)
    @cooldown(1, 5, BucketType.user)
    async def timeout(self, ctx, users: Greedy[MentionedMember], *, timeout):
        """
        Mute user/users for a specified amount of time
        Users must be pinged or their id used for them to be timeouted.
        Max amount of users muted at one time is 10
        `timeout` is the duration of the mute.
        The format is `n d|days` `n h|hours` `n m|min|minutes` `n s|sec|seconds` `reason`
        where at least one of them must be provided.
        Maximum length for a timeout is 30 days
        e.g. `{prefix}{name} <@!12345678> 10d 10h 10m 10s This is the reason for the timeout`
        """
        if not users:
            ctx.command.reset_cooldown(ctx)
            await ctx.send('No users given to timeout')
            return

        if len(users) > 10:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f'Tried to timeout {len(users)} users while maximum amount is 10')
            return

        mute_role = await self._mute_check(ctx)
        if not mute_role:
            return

        try:
            time, reason = parse_timeout(timeout)
        except OverflowError:
            return await ctx.send('Duration too long')

        guild = ctx.guild
        if not time:
            return await ctx.send('Invalid time string')

        if time.days > 30:
            await ctx.send("Timeout can't be longer than 30 days")
            return

        if guild.id == 217677285442977792:
            if time.total_seconds() < 500:
                await ctx.send('This server is retarded so I have to hardcode timeout limits and the given time is too small')
                return

        if time.total_seconds() < 59:
            await ctx.send('Minimum timeout is 1 minute')
            return

        author = ctx.author
        muted_users = []
        failed = []

        now = datetime.utcnow()
        reason = reason if reason else 'No reason <:HYPERKINGCRIMSONANGRY:356798314752245762>'
        expires_on = now + time

        e = (305763341069189120, 326524736521633792)

        for user in users:
            # Ignore checks if in test mode
            if not self.bot.test_mode:
                if user.id == author.id and time.total_seconds() < 21600:
                    failed.append('If you gonna timeout yourself at least make it a longer timeout')
                    continue

                if guild.id == 217677285442977792 and user.id == 123050803752730624:
                    failed.append(f"Couldn't mute {user}. Not today kiddo. I'm too powerful for you")
                    continue

                if guild.id == 217677285442977792 and user.id in e and author.id in e:
                    failed.append('e')
                    continue

                r = guild.get_role(339841138393612288)
                if not author.id == 123050803752730624 and self.bot.anti_abuse_switch and r in user.roles and r in author.roles:
                    failed.append('All hail our leader <@!222399701390065674>')
                    continue

                if author != guild.owner and author.top_role <= user.top_role:
                    failed.append(f'{user} is higher or same as you in the role hierarchy')
                    continue

                if guild.id == 217677285442977792:
                    rtm = guild.get_role(339841138393612288)
                    if rtm in author.roles and rtm in user.roles:
                        if ctx.channel.id == 361830510646788098:
                            continue

            try:
                await user.add_roles(mute_role, reason=f'[{author}] {reason}')
                muted_users.append(user)
            except discord.HTTPException:
                failed.append('Could not mute user {}'.format(user))
                continue

        msg = None
        if muted_users:
            user_string = '\n'.join(map(lambda u: f'{u} `{u.id}`', muted_users))
            description = f'{author.mention} muted {user_string} for {time}'

            url = f'[Jump to](https://discordapp.com/channels/{guild.id}/{ctx.channel.id}/{ctx.message.id})'
            embed = discord.Embed(title='🕓 Moderation action [TIMEOUT]',
                                  timestamp=datetime.utcnow() + time,
                                  description=description)
            embed.add_field(name='Reason', value=reason)
            embed.add_field(name='Link', value=url)

            if len(muted_users) == 1:
                u = muted_users[0]
                embed.set_thumbnail(url=u.avatar_url or u.default_avatar_url)

            embed.set_footer(text='Expires at',
                             icon_url=author.avatar_url or author.default_avatar_url)

            msg = await self.send_to_modlog(guild, embed=embed)

        for user in muted_users:
            await self.add_timeout(ctx, guild.id, user.id, expires_on,
                                   time.total_seconds(),
                                   reason=reason,
                                   modlog_msg=msg.id if msg else None)

        s = ""
        if muted_users:
            s += "Muted user" + ("s " if len(muted_users) > 1 else " ")
            s += ', '.join(map(str, muted_users))
            s += f' for {time}\n'

        if failed:
            s += "\n".join(failed)

        if not s:
            s = 'Muted no one'

        await ctx.send(s)

    @group(invoke_without_command=True, no_pm=True)
    @bot_has_permissions(manage_roles=True)
    @has_permissions(manage_roles=True)
    async def unmute(self, ctx, user: MentionedMember, *, reason='idk kev'):
        """Unmute a user"""
        guild = ctx.guild
        mute_role = self.bot.guild_cache.mute_role(guild.id)
        if mute_role is None:
            await ctx.send(f'No mute role set. You can set it with {ctx.prefix}settings mute_role role name')
            return

        if guild.id == 217677285442977792 and user.id == 123050803752730624:
            await ctx.send("Not today kiddo. I'm too powerful for you")
            return

        mute_role = guild.get_role(mute_role)
        if mute_role is None:
            await ctx.send('Could not find the muted role')
            return

        if mute_role not in user.roles:
            await ctx.send('User not muted')
            return

        try:
            await user.remove_roles(mute_role, reason=f'Responsible user {ctx.author}')
        except discord.HTTPException:
            await ctx.send('Could not unmute user {}'.format(user))
        else:
            row = await self.remove_timeout(user.id, guild.id, return_info=True)
            if not row:
                row = (await self.bot.dbutil.get_latest_timeout_log(guild.id, user.id)) or {}

            if self.bot.guild_cache.log_unmutes(guild.id):
                author = ctx.author
                description = f'{author.mention} unmuted {user} {user.id}'
                url = f'[Jump to](https://discordapp.com/channels/{guild.id}/{ctx.channel.id}/{ctx.message.id})'
                embed = discord.Embed(title='🔊 Moderation action [UNMUTE]',
                                      timestamp=datetime.utcnow(),
                                      description=description)
                embed.add_field(name='Reason for unmute', value=reason)
                embed.add_field(name='Link', value=url)
                embed.add_field(name='Mute reason', value=row.get('reason', 'Mute reason not logged'))
                expires_on = row.get('expires_on')
                if expires_on:
                    sentence_left = format_timedelta(expires_on - datetime.utcnow(), DateAccuracy.Day-DateAccuracy.Hour)
                else:
                    sentence_left = 'indefinite'

                embed.add_field(name='Sentence left', value=sentence_left)

                if row.get('time'):
                    at = format_timedelta(datetime.utcnow() - row['time'], DateAccuracy.Day-DateAccuracy.Hour)
                    embed.add_field(name='Got muted', value=at + ' ago')

                # Set field for the person who muted if they exist
                old_author = guild.get_member(row.get('author'))
                if not old_author and row.get('author'):
                    old_author = f'<@{row.get("author")}>'

                if old_author:
                    embed.add_field(name='Muted by', value=old_author)

                embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                embed.set_footer(text=str(author), icon_url=author.avatar_url or author.default_avatar_url)
                await self.send_to_modlog(guild, embed=embed)

            t = self.timeouts.get(guild.id, {}).get(user.id)
            if t:
                t.cancel()

            await ctx.send('Unmuted user {}'.format(user))

    async def _unmute_when(self, ctx, user, embed=True):
        guild = ctx.guild
        member = user if user else ctx.author

        muted_role = self.bot.guild_cache.mute_role(guild.id)
        if not muted_role:
            return await ctx.send(f'No mute role set on this server. You can set it with {ctx.prefix}settings mute_role role name')

        if not list(filter(lambda r: r.id == muted_role, member.roles)):
            return await ctx.send('%s is not muted' % member)

        row = await self.bot.dbutil.get_latest_timeout_log(guild.id, member.id)
        utcnow = datetime.utcnow()

        if row is False:
            return await ctx.send('Failed to check mute status')

        if not row:
            return await ctx.send(f'User {member} is permamuted without a reason')

        td = f'User {member} is permamuted\n'
        if row['expires_on']:
            delta = row['expires_on'] - utcnow
            td = seconds2str(delta.total_seconds(), False)
            # Most likely happens when unmute when called after unmute has happened
            if td.startswith('-'):
                logger.warning(f'Negative time in unmute when.\nValue of row: {row["expires_on"]}\nValue of utcnow: {utcnow}\nTimedelta: {delta}')
                td = 'soon'
            else:
                td = 'in ' + td
            td = f'Timeout for {member} expires {td}\n'

        reason = row['reason']
        author = row['author']
        author_user = self.bot.get_user(author)

        if not author_user:
            author = f'User responsible for timeout: `uid {author}`\n'
        else:
            author = f'User responsible for timeout: {author_user} `{author_user.id}`\n'

        muted_at = row['time']
        td_at = utcnow - muted_at
        author += f'Muted on `{muted_at.strftime("%Y-%m-%d %H:%M")}` UTC which was {format_timedelta(td_at, DateAccuracy.Day)} ago\n'

        if embed:
            embed = discord.Embed(title='Unmute when', description=td, timestamp=row['expires_on'] or discord.Embed.Empty)
            embed.add_field(name='Who muted', value=author, inline=False)
            embed.add_field(name='Reason', value=reason, inline=False)
            embed.set_footer(text='Expires at')

            if row['embed']:
                embed.set_image(url=row['embed'])

            await ctx.send(embed=embed)
        else:
            reason = f'Timeout reason: {reason}'
            s = td + author + reason
            await ctx.send(s)

    @unmute.command(no_pm=True)
    @cooldown(1, 3, BucketType.user)
    async def when(self, ctx, *, user: discord.Member=None):
        """Shows how long you are still muted for"""
        await self._unmute_when(ctx, user, embed=check_botperm('embed_links', ctx=ctx))

    @command(no_pm=True)
    @cooldown(1, 3, BucketType.user)
    async def unmute_when(self, ctx, *, user: discord.Member=None):
        """Shows how long you are still muted for"""
        await self._unmute_when(ctx, user, embed=check_botperm('embed_links', ctx=ctx))

    # Only use this inside commands
    @staticmethod
    async def _set_channel_lock(ctx, locked: bool, zawarudo=False):
        channel = ctx.channel
        everyone = ctx.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False if locked else None
        try:
            await channel.set_permissions(everyone, overwrite=overwrite, reason=f'Responsible user {ctx.author}')
        except discord.HTTPException as e:
            return await ctx.send('Failed to lock channel because of an error: %s. '
                                  'Bot might lack the permissions to do so' % e)

        try:
            if locked:
                if not zawarudo:
                    await ctx.send('Locked channel %s' % channel.name)
                else:
                    await ctx.send(f'Time has stopped in {channel.mention}')
            else:
                if not zawarudo:
                    await ctx.send('Unlocked channel %s' % channel.name)
                else:
                    await ctx.send('Soshite toki wo ugokidasu')
        except discord.HTTPException:
            pass

    @staticmethod
    def hackban_embed(ctx: Context, users: List[int], reason: str):
        author: discord.Member = ctx.author
        description = f'{author.mention} banned **{len(users)}** users'
        embed = discord.Embed(title=f'🔨 Moderation action [BAN]',
                              description=description,
                              timestamp=datetime.utcnow())

        embed.add_field(name='Reason', value=reason)

        for field in split_string(map(str, users), '\n', maxlen=EmbedLimits.Field):
            user_count = field.strip().count('\n') + 1
            embed.add_field(name=f'Banned users [{user_count}]', value=field)
        embed.set_footer(text=str(author), icon_url=get_avatar(author))

        return embed

    @staticmethod
    def purge_embed(ctx, messages, users: set=None, multiple_channels=False, channel=None):
        author = ctx.author
        if not multiple_channels:
            d = '%s removed %s messages in %s' % (author.mention, len(messages),
                                                  channel.mention if channel else ctx.channel.mention)
        else:
            d = '%s removed %s messages' % (author.mention, len(messages))

        if users is None:
            users = set()
            for m in messages:
                if isinstance(m, discord.Message):
                    users.add(m.author.mention)
                elif isinstance(m, dict):
                    try:
                        users.add('<@!{}>'.format(m['user_id']))
                    except KeyError:
                        pass

        value = ''
        last_index = len(users) - 1
        for idx, u in enumerate(list(users)):
            if idx == 0:
                value += u
                continue

            if idx == last_index:
                user = ' and ' + u
            else:
                user = ', ' + u

            if len(user) + len(value) > 1000:
                value += 'and %s more users' % len(users)
                break
            else:
                value += user
            users.remove(u)

        embed = discord.Embed(title='🗑 Moderation action [PURGE]', timestamp=datetime.utcnow(), description=d)
        embed.add_field(name='Deleted messages from', value=value)
        embed.set_thumbnail(url=get_avatar(author))
        embed.set_footer(text=str(author), icon_url=get_avatar(author))
        return embed

    @group(invoke_without_command=True, no_pm=True)
    @cooldown(1, 5, BucketType.guild)
    @bot_has_permissions(manage_messages=True)
    @has_permissions(manage_messages=True)
    async def purge(self, ctx, max_messages: int):
        """Purges n amount of messages from a channel.
        maximum value of max_messages is 300 and the default is 10"""
        channel = ctx.channel
        if max_messages > 1000000:
            return await ctx.send("Either you tried to delete over 1 million messages or just put it there as an accident. "
                                  "Either way that's way too much for me to handle")

        max_messages = min(300, max_messages)

        # purge doesn't support reasons yet
        try:
            messages = await channel.purge(limit=max_messages, bulk=True)  # , reason=f'{ctx.author} purged messages')
        except discord.HTTPException as e:
            try:
                await ctx.send(f'Failed to purge messages\n{e}')
            except discord.HTTPException:
                pass

            return

        modlog = self.get_modlog(channel.guild)
        if not modlog:
            return

        embed = self.purge_embed(ctx, messages)
        await self.send_to_modlog(channel.guild, embed=embed)

    @purge.command(name='from', no_pm=True)
    @cooldown(2, 4, BucketType.guild)
    @bot_has_permissions(manage_messages=True)
    @has_permissions(manage_messages=True)
    async def from_(self, ctx, user: PossibleUser, max_messages: int=10, channel: discord.TextChannel=None):
        """
        Delete messages from a user
        `user` The user mention or id of the user we want to purge messages from

        [OPTIONAL]
        `max_messages` Maximum amount of messages that can be deleted. Defaults to 10 and max value is 300.
        `channel` Channel if or mention where you want the messages to be purged from. If not set will delete messages from any channel the bot has access to.
        """
        guild = ctx.guild
        # We have checked the members channel perms but we need to be sure the
        # perms are global when no channel is specified
        if channel is None and not ctx.author.guild_permissions.manage_messages and not ctx.override_perms:
            return await ctx.send("You don't have the permission to purge from all channels")

        elif channel and not channel.permissions_for(ctx.author).manage_messages:
            await ctx.send(f"You don't have manage messages in {channel}")
            return

        max_messages = min(300, max_messages)
        modlog = self.get_modlog(guild)

        if not isinstance(user, int):
            user = user.id

        async def purge_channel():
            messages = await channel.purge(limit=max_messages, check=lambda m: m.author.id == user)

            if modlog and messages:
                embed = self.purge_embed(ctx, messages, users={'<@!%s>' % user})
                await self.send_to_modlog(guild, embed=embed)

                await ctx.send(f'Checked the last {max_messages} of the channel {channel} and deleted {len(messages)} messages', delete_after=20)
                return

        if channel is not None:
            return await purge_channel()

        t = datetime.utcnow() - timedelta(days=14)

        # Create a snowflake from date because that way we dont need a date column
        # https://discordapp.com/developers/docs/reference#snowflakes-snowflake-id-format-structure-left-to-right
        # snowflake reference
        t = ((int(t.timestamp()*1000)-1420070400000) << 22) | (11111 << 18) | (11111 << 12) | 111111111111

        sql = "SELECT message_id, channel FROM messages WHERE guild=%s AND user_id=%s AND message_id > %s " % (guild.id, user, t)

        if channel is not None:
            sql += 'AND channel=%s ' % channel.id

        sql += 'ORDER BY message_id DESC LIMIT %s' % max_messages

        rows = await self.bot.dbutil.fetch(sql)

        if not rows:
            channel = ctx.channel
            await purge_channel()
            return

        channel_messages = {}
        for r in rows:
            if r['channel'] not in channel_messages:
                message_ids = []
                channel_messages[r['channel']] = message_ids
            else:
                message_ids = channel_messages[r['channel']]

            message_ids.append(Snowflake(r['message_id']))

        ids = []
        bot_member = guild.get_member(self.bot.user.id)
        for k in channel_messages:
            channel = self.bot.get_channel(k)
            if not (channel and channel.permissions_for(bot_member).manage_messages):
                continue

            try:
                await self.delete_messages(channel, channel_messages[k])
            except discord.HTTPException:
                logger.exception('Could not delete messages')
            else:
                ids.extend(channel_messages[k])

        if ids:
            sql = 'DELETE FROM messages WHERE message_id IN (%s)' % ', '.join(str(i.id) for i in ids)
            try:
                await self.bot.dbutil.execute(sql)
            except PostgresError:
                logger.exception('Could not delete messages from database')

            if modlog:
                embed = self.purge_embed(ctx, ids, users={'<@!%s>' % user}, multiple_channels=len(channel_messages.keys()) > 1)
                await self.send_to_modlog(guild, embed=embed)

    @purge.command(name='until', no_pm=True)
    @cooldown(2, 4, BucketType.guild)
    @bot_has_permissions(manage_messages=True)
    @has_permissions(manage_messages=True)
    async def purge_until(self, ctx, message_id: int, limit: int=100):
        """Purges messages until the specified message is reached or the limit is exceeded
        limit the max limit is 500 is the specified message is under 2 weeks old
        otherwise the limit is 100"""
        channel = ctx.channel
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return await ctx.send(f'Message {message_id} not found in this channel')

        days = (datetime.utcnow() - message.created_at).days

        max_limit = 100 if days >= 14 else 500

        if limit >= max_limit:
            return await ctx.send(f'Maximum limit is {max_limit}')

        def check(msg):
            if msg.id <= message_id:
                return False

            return True

        try:
            deleted = await channel.purge(limit=limit, check=check)
        except discord.HTTPException as e:
            await ctx.send(f'Failed to delete messages because of an error\n{e}')
        else:
            await ctx.send(f'Deleted {len(deleted)} messages', delete_after=10)
            embed = self.purge_embed(ctx, deleted)
            await self.send_to_modlog(channel.guild, embed=embed)

    @command(no_pm=True, aliases=['hb', 'massban'], cooldown_after_parsing=True)
    @bot_has_permissions(ban_members=True)
    @has_permissions(ban_members=True)
    @cooldown(2, 5)
    async def hackban(self, ctx: Context, user_ids: Greedy[int], *, reason: str = 'No reason'):
        """
        Ban multiple users by user id.
        """
        failed = []
        success = []
        guild: discord.Guild = ctx.guild
        user_ids = set(user_ids)
        user_ids.discard(ctx.author.id)  # Can't ban yourself

        if not user_ids:
            await ctx.send('No users given to ban')
            ctx.command.undo_use(ctx)
            return

        await ctx.send('Starting to massban. This might take a while.')

        if not guild.chunked:
            await guild.chunk()

        for user_id in user_ids:
            # Permission check
            member = guild.get_member(user_id)
            if member and member.top_role >= ctx.author.top_role:
                failed.append(user_id)
                continue

            try:
                await guild.ban(Snowflake(id=user_id), reason=f'Hackban by {ctx.author}: {reason[:400]}')
                success.append(user_id)
            except discord.HTTPException:
                failed.append(user_id)
            except:
                failed.append(user_id)
                logger.exception('Failed to hackban.')

        fail_msg = None
        if failed:
            s_failed = "\n".join(map(str, failed))
            fail_msg = f'❌ Failed to ban {len(failed)} users.\n{s_failed}'[:2000]

        if fail_msg:
            await ctx.send(fail_msg)
            if not success:
                return

        embed = self.hackban_embed(ctx, success, reason)
        await self.send_to_modlog(guild, embed=embed)
        await ctx.send(f'✅ Banned **{len(success)}** users')

    @command(no_pm=True, cooldown_after_parsing=True)
    @bot_has_permissions(ban_members=True)
    @has_permissions(ban_members=True)
    @cooldown(2, 5)
    async def ban(self, ctx: Context, user: discord.User, delete_days: Optional[int] = 0, *, reason: str = 'No reason'):
        """
        Bans the specified user from the server.
        Cannot ban yourself or someone with a higher or equal top role
        """
        author = ctx.author
        if user == author:
            await ctx.send('Cannot ban yourself...')
            return

        guild: discord.Guild = ctx.guild
        if guild.chunked:
            member: Optional[discord.Member] = guild.get_member(user.id)
        else:
            try:
                member = await guild.fetch_member(user.id)
            except discord.HTTPException:
                member = None

        if member and member.top_role >= author.top_role:
            await ctx.send('Cannot ban someone with a role higher or equal to your top role')
            return

        try:
            await ctx.guild.ban(user, delete_message_days=delete_days, reason=f'Banned by {author}: {reason[:400]}')
            pass
        except discord.HTTPException as e:
            await ctx.send(f'Failed to ban user {user}\n{e}')
            return
        except:
            logger.exception('Failed to ban user')
            await ctx.send(f'Failed to ban user {user}')
            return

        embed = discord.Embed(
            title='🔨 Moderation action [BAN]',
            description=f'{ctx.author.mention} banned {user} {user.mention}',
            timestamp=datetime.utcnow()
        )
        embed.add_field(name='Reason', value=reason or 'No reason')
        embed.add_field(name='Link', value=f'[Jump to]({ctx.message.jump_url})')
        embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
        embed.set_footer(text=str(author), icon_url=get_avatar(author))

        await self.send_to_modlog(ctx.guild, embed=embed)
        await ctx.send(f'✅ Successfully banned {user}')

    @command(no_pm=True, cooldown_after_parsing=True)
    @bot_has_permissions(ban_members=True)
    @has_permissions(ban_members=True)
    @cooldown(2, 5)
    async def bab(self, ctx: Context, user: discord.User):
        """
        Babs the specified user from the server
        """
        await ctx.send(f'✅ Successfully babbed **{user}**')

    @command(no_pm=True, aliases=['softbab'])
    @bot_has_permissions(ban_members=True)
    @has_permissions(ban_members=True)
    async def softban(self, ctx, user: PossibleUser, message_days: int=1):
        """Ban and unban a user from the server deleting that users messages from
        n amount of days in the process"""
        guild = ctx.guild
        if not (1 <= message_days <= 7):
            return await ctx.send('Message days must be between 1 and 7')

        user_name = str(user)
        if isinstance(user, discord.User):
            user = user.id
            user_name += f' `{user}`'
        try:
            await guild.ban(Snowflake(user), reason=f'{ctx.author} softbanned', delete_message_days=message_days)
        except discord.Forbidden:
            return await ctx.send("The bot doesn't have ban perms")
        except discord.HTTPException:
            return await ctx.send('Something went wrong while trying to ban. Try again')

        try:
            await guild.unban(Snowflake(user), reason=f'{ctx.author} softbanned')
        except discord.HTTPException:
            return await ctx.send('Failed to unban after ban')

        s = f'Softbanned user {user_name}'

        await ctx.send(s)

    @command(aliases=['zawarudo'], no_pm=True)
    @cooldown(1, 5, BucketType.guild)
    @bot_has_permissions(manage_channels=True, manage_roles=True)
    @has_permissions(manage_channels=True, manage_roles=True)
    async def lock(self, ctx):
        """Set send_messages permission override of everyone to false on current channel"""
        await self._set_channel_lock(ctx, True, zawarudo=ctx.invoked_with == 'zawarudo')

    @command(aliases=['tokiwougokidasu'], no_pm=True)
    @cooldown(1, 5, BucketType.guild)
    @bot_has_permissions(manage_channels=True, manage_roles=True)
    @has_permissions(manage_channels=True, manage_roles=True)
    async def unlock(self, ctx):
        """Set send_messages permission override on current channel to default position"""
        await self._set_channel_lock(ctx, False, zawarudo=ctx.invoked_with == 'tokiwougokidasu')

    def get_temproles(self, guild: int, uid: int = None):
        temproles = self.temproles.get(guild, None)
        if temproles is None:
            temproles = {}
            self.temproles[guild] = temproles

        if uid is None:
            return temproles

        user_temp = temproles.get(uid)
        if not user_temp:
            user_temp = {}
            temproles[uid] = user_temp

        return user_temp

    def get_timeouts(self, guild: int):
        timeouts = self.timeouts.get(guild, None)
        if timeouts is None:
            timeouts = {}
            self.timeouts[guild] = timeouts

        return timeouts

    async def remove_role(self, user: int, role: int, guild: int):
        guild = self.bot.get_guild(guild)
        if not guild:
            await self.bot.dbutil.remove_temprole(user, role)
            return

        member = None
        try:
            member = await guild.fetch_member(user)
        except discord.NotFound:
            pass
        except discord.HTTPException:
            logger.exception('Failed to fetch member in remove_role')

        if not member:
            await self.bot.dbutil.remove_temprole(user, role)
            return

        try:
            await member.remove_roles(Snowflake(role), reason='Removed temprole')
        except discord.HTTPException:
            pass

        await self.bot.dbutil.remove_temprole(user, role)

    def register_timeout(self, user: int, guild: int, time, ignore_dupe=False):
        timeouts = self.get_timeouts(guild)
        if ignore_dupe and user in timeouts:
            return

        t = timeouts.pop(user, None)
        if t:
            t.cancel()

        # If we modify an existing timeout to a longer one this will trigger
        if not ignore_dupe and time > self._pause*2:
            return

        if time <= 1:
            time = 1

        task = call_later(self.untimeout, self.bot.loop, time,
                          user, guild, after=lambda f: timeouts.pop(user, None))
        timeouts[user] = task

    def register_temprole(self, user: int, role: int, guild: int, time, ignore_dupe=False, force_save=False):
        temproles = self.get_temproles(guild, user)
        if role in temproles and ignore_dupe:
            return

        old = temproles.pop(role, None)
        if old:
            old.cancel()

        if not force_save and not ignore_dupe and time > self._pause * 2:
            return

        if time <= 1:
            time = 1

        task = call_later(self.remove_role, self.bot.loop, time,
                          user, role, guild, after=lambda _: temproles.pop(role, None))

        temproles[role] = task

    @command(no_pm=True, cooldown_after_parsing=True)
    @cooldown(1, 5, BucketType.user)
    async def temproles(self, ctx, *, user: discord.Member = None):
        """
        Get the temproles for yourself or a specified user
        """
        user = user or ctx.author

        temproles = await self.bot.dbutil.get_temproles(ctx.guild.id, user.id)
        if not temproles:
            await ctx.send(f'No temproles found for user {user}')
            return

        msg = f'Temproles of {user.mention}\n\n'
        now = datetime.utcnow()

        for temprole in temproles:
            expires_in = format_timedelta(temprole['expires_at'] - now, DateAccuracy.Day-DateAccuracy.Minute)
            msg += f'<@&{temprole["role"]}> expires in {expires_in}\n'

        await ctx.send(msg, allowed_mentions=discord.AllowedMentions.none())

    @command(no_pm=True)
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 5, BucketType.guild)
    async def temprole(self, ctx, time: TimeDelta, user: discord.Member, *, role: discord.Role):
        """
        Temporarily give a user a role
        """
        if time.days > 7:
            return await ctx.send('Max days is 7')

        total_seconds = time.total_seconds()

        if not self.bot.test_mode and total_seconds < 60:
            return await ctx.send('Must be over minute')

        bot = ctx.guild.me
        if role > bot.top_role:
            return await ctx.send('Role is higher than my top role')

        if role > ctx.author.top_role:
            return await ctx.send('Role is higher than your top role')

        expires_at = datetime.utcnow() + time

        self.register_temprole(user.id, role.id, user.guild.id, total_seconds)
        await self.bot.dbutil.add_temprole(user.id, role.id, user.guild.id,
                                           expires_at)

        try:
            await user.add_roles(role, reason=f'{ctx.author} temprole {seconds2str(total_seconds, long_def=False)}')
        except discord.HTTPException as e:
            await ctx.send('Failed to add role because of an error\n%s' % e)
            return
        except:
            logger.exception('Failed to add role')
            await ctx.send('Failed to add role. An exception has been logged')
            return

        await ctx.send(f'Added {role} to {user} for {seconds2str(total_seconds, long_def=False)}')

    @command(no_pm=True)
    @cooldown(1, 4, BucketType.user)
    async def reason(self, ctx, user_or_message: Union[discord.User, int], *, reason):
        """
        Changes the reason on a mute or unmute
        If message id is given, it will try to edit a message with that id in the modlog.
        This works for both mutes and unmutes and will edit reason for everyone
        involved in that action

        If a user is mentioned this will fetch the latest mute that you've done to that user
        and edit that. This method does not work for unmutes. Also in the case of
        muting/timeouting multiple users this will update the reason only for the user
        given

        """
        modlog = self.get_modlog(ctx.guild)
        if not modlog:
            return await ctx.send('Modlog not found')

        is_msg = isinstance(user_or_message, int)
        s = ''
        row = None
        embed = None
        msg = None

        if is_msg:
            message_id = user_or_message
            try:
                msg = await modlog.fetch_message(message_id)
            except discord.HTTPException as e:
                return await ctx.send('Failed to get message\n%s' % e)

            if msg.author.id != self.bot.user.id:
                return await ctx.send('Modlog entry not by this bot')

            if not msg.embeds:
                return await ctx.send('Embed not found')

            embed = msg.embeds[0]
            if not embed.footer or str(ctx.author.id) not in embed.footer.icon_url:
                return await ctx.send("You aren't responsible for this mod action")

            user_id = re.findall(r'(\d+)', msg.embeds[0].description)
            if user_id:
                user_id = user_id[-1]

        else:
            user = user_or_message
            user_id = user.id
            row = await self.bot.dbutil.get_latest_timeout_log_for(ctx.guild.id, user.id, ctx.author.id)
            if row is False:
                return await ctx.send('Failed to get timeout from database')

            if not row:
                return await ctx.send(f"You have never muted {user}")

            if row['message']:
                try:
                    msg = await modlog.fetch_message(row['message'])
                except discord.HTTPException:
                    s += f'Failed to get modlog entry\n'
                else:
                    if msg.embeds:
                        embed = msg.embeds[0]

        unmute = False
        if embed:
            idx = -1
            # Check if embed is for unmutes or not
            unmute = 'UNMUTE' in embed.title
            field_name = "Reason for unmute" if unmute else 'Reason'
            for index, field in enumerate(embed.fields):
                if field.name == field_name:
                    idx = index
                    break

            if idx < 0:
                if is_msg:
                    return await ctx.send('No reason found')

                s += 'No modlog reason found\n'

            embed.set_field_at(idx, name=field_name, value=reason)

            if msg:
                try:
                    await msg.edit(embed=embed)
                except discord.HTTPException as e:
                    s += f'Failed to edit modlog reason because of an error.\n{e}\n'

        if unmute:
            s += 'Edited unmute reason'

        elif row:
            td = datetime.utcnow() - row['time']
            # td formatted from day to hour
            td = format_timedelta(td, DateAccuracy.Day-DateAccuracy.Hour)
            s += f'Reason for the mute of {user_or_message} from {td} ago was edited'

            sql = "UPDATE timeout_logs SET reason=$1 WHERE id=$2"
            try:
                await self.bot.dbutil.execute(sql, (reason, row['id']))
            except PostgresError:
                pass

        else:
            if msg:
                sql = "UPDATE timeout_logs SET reason=$1 WHERE message=$2 and guild=$3"

                try:
                    await self.bot.dbutil.execute(sql, (reason, msg.id, ctx.guild.id))
                except PostgresError:
                    pass

            elif not await self.edit_mute_reason(ctx, user_id, reason):
                return await ctx.send('Failed to edit reason because of an error')

            s += 'Reason edited'

        await ctx.send(s)

    @staticmethod
    async def delete_messages(channel, message_ids):
        """Delete messages in bulk and take the message limit into account"""
        step = 100
        for i in range(0, len(message_ids), step):
            try:
                await channel.delete_messages(message_ids[i:i+step])
            except discord.NotFound:
                pass

    def get_modlog(self, guild):
        return guild.get_channel(self.bot.guild_cache.modlog(guild.id))


def setup(bot):
    bot.add_cog(Moderator(bot))
