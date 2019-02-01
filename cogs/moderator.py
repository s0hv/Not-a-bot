import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from random import randint, random
from typing import Union

import discord
from discord.ext.commands import (BucketType, bot_has_permissions)
from sqlalchemy.exc import SQLAlchemyError

from bot.bot import command, group, has_permissions, cooldown
from bot.converters import MentionedMember, PossibleUser, TimeDelta
from bot.formatter import Paginator
from bot.globals import DATA
from cogs.cog import Cog
from utils.utilities import (call_later, parse_timeout,
                             datetime2sql, get_avatar, is_image_url,
                             seconds2str, get_role, get_channel, Snowflake,
                             basic_check, sql2timedelta, check_botperm,
                             format_timedelta, DateAccuracy, send_paged_message)

logger = logging.getLogger('debug')
manage_roles = discord.Permissions(268435456)
lock_perms = discord.Permissions(268435472)


class Moderator(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.timeouts = self.bot.timeouts
        self.temproles = self.bot.temproles
        self.automute_blacklist = {}
        self.automute_whitelist = {}
        self._current_rolls = {}  # Users currently active in a mute roll
        self._load_timeouts()
        self._load_automute()
        self._load_temproles()

    def __unload(self):
        for timeouts in list(self.timeouts.values()):
            for timeout in list(timeouts.values()):
                timeout.cancel()

        for temproles in list(self.temproles.values()):
            for temprole in list(temproles.values()):
                temprole.cancel()

    def _load_automute(self):
        sql = 'SELECT * FROM `automute_blacklist`'
        session = self.bot.get_session
        rows = session.execute(sql)
        for row in rows:
            id_ = row['guild']
            if id_ not in self.automute_blacklist:
                s = set()
                self.automute_blacklist[id_] = s

            else:
                s = self.automute_blacklist[id_]

            s.add(row['channel'])

        sql = 'SELECT * FROM `automute_whitelist`'
        rows = session.execute(sql)
        for row in rows:
            id_ = row['guild']
            if id_ not in self.automute_whitelist:
                s = set()
                self.automute_whitelist[id_] = s

            else:
                s = self.automute_whitelist[id_]

            s.add(row['role'])

    def _load_temproles(self):
        session = self.bot.get_session
        sql = 'SELECT * FROM `temproles`'
        rows = session.execute(sql)

        for row in rows:
            time = row['expires_at'] - datetime.utcnow()
            guild = row['guild']
            user = row['user']
            role = row['role']

            self.register_temprole(user, role, guild, time.total_seconds())

    def _load_timeouts(self):
        session = self.bot.get_session
        sql = 'SELECT * FROM `timeouts`'
        rows = session.execute(sql)
        for row in rows:
            try:
                time = row['expires_on'] - datetime.utcnow()
                guild = row['guild']
                user = row['user']

                if guild not in self.timeouts:
                    guild_timeouts = {}
                    self.timeouts[guild] = guild_timeouts
                else:
                    guild_timeouts = self.timeouts.get(guild)

                t = guild_timeouts.pop(user, None)
                if t:
                    t.cancel()

                seconds = time.total_seconds()
                if seconds <= 1:
                    seconds = 1
                task = call_later(self.untimeout, self.bot.loop, seconds,
                                  user, guild, after=lambda f: guild_timeouts.pop(user, None))
                guild_timeouts[user] = task

            except:
                logger.exception('Could not untimeout %s' % row)

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

            if mute_role in user.roles:
                return

            if not check_botperm('manage_roles', guild=message.guild, channel=message.channel):
                return

            s = '.img penile hemorrhage'
            if guild.id == 217677285442977792 and message.content.strip().lower() == s:
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

                time = timedelta(days=3)
                await message.author.add_roles(mute_role, reason=f'[Automute] {message.content}')
                d = f'Automuted user {user} `{user.id}` for {time}'
                url = f'https://discordapp.com/channels/{guild.id}/{message.channel.id}/{message.id}'
                embed = discord.Embed(title='Moderation action [AUTOMUTE]', description=d,
                                      timestamp=datetime.utcnow())
                embed.add_field(name='Reason', value=message.content)
                embed.add_field(name='link', value=url)
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

            limit = self.bot.guild_cache.automute_limit(guild.id)
            if len(message.mentions) + len(message.role_mentions) > limit:
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

                        url = f'https://discordapp.com/channels/{guild.id}/{message.channel.id}/{message.id}'
                        reason = 'Too many mentions in a message'
                        await message.author.add_roles(mute_role, reason='[Automute] too many mentions in message')
                        embed = discord.Embed(title='Moderation action [AUTOMUTE]', description=d, timestamp=datetime.utcnow())
                        embed.add_field(name='Reason', value=reason)
                        embed.add_field(name='link', value=url)
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
        roles = map(lambda r: guild.get_role(r), roles)
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
    async def add(self, ctx, *, role):
        """Add a role to the automute whitelist"""
        guild = ctx.guild
        roles = self.automute_whitelist.get(guild.id)
        if roles is None:
            roles = set()
            self.automute_whitelist[guild.id] = roles

        if len(roles) >= 10:
            return await ctx.send('Maximum of 10 roles can be added to automute whitelist.')

        role_ = get_role(role, guild.roles, name_matching=True)
        if not role_:
            return await ctx.send('Role {} not found'.format(role))

        if ctx.author.top_role <= role:
            return await ctx.send('The role you are trying to add is higher than your top role in the hierarchy')

        success = await self.bot.dbutils.add_automute_whitelist(guild.id, role_.id)
        if not success:
            return await ctx.send('Failed to add role because of an error')

        roles.add(role_.id)
        await ctx.send('Added role {0.name} `{0.id}`'.format(role_))

    @automute_whitelist_.command(aliases=['del', 'delete'], no_pm=True)
    @has_permissions(manage_guild=True, manage_roles=True)
    @cooldown(2, 5, BucketType.guild)
    async def remove(self, ctx, *, role):
        """Remove a role from the automute whitelist"""
        guild = ctx.guild
        roles = self.automute_whitelist.get(guild.id, ())
        role_ = get_role(role, guild.roles, name_matching=True)
        if not role_:
            return await ctx.send('Role {} not found'.format(role))

        if role_.id not in roles:
            return await ctx.send('Role {0.name} not found in whitelist'.format(role_))

        if ctx.author.top_role <= role:
            return await ctx.send('The role you are trying to remove is higher than your top role in the hierarchy')

        success = await self.bot.dbutils.remove_automute_whitelist(guild.id, role.id)
        if not success:
            return await ctx.send('Failed to remove role because of an error')

        roles.discard(role_.id)
        await ctx.send('Role {0.name} `{0.id}` removed from automute whitelist'.format(role_))

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
    async def add_role(self, ctx, name, random_color=True, mentionable=True, hoist=False):
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
    async def mute(self, ctx, user: MentionedMember, *reason):
        """Mute a user. Only works if the server has set the mute role"""
        mute_role = await self._mute_check(ctx)
        if not mute_role:
            return

        guild = ctx.guild
        if guild.id == 217677285442977792 and user.id == 123050803752730624:
            return await ctx.send("Not today kiddo. I'm too powerful for you")

        if guild.id == 217677285442977792 and ctx.author.id == 117256618617339905 and user.id == 189458911886049281:
            return await ctx.send('No <:peepoWeird:423445885180051467>')

        if ctx.author != guild.owner and ctx.author.top_role <= user.top_role:
            return await ctx.send('The one you are trying to mute is higher or same as you in the role hierarchy')

        reason = ' '.join(reason) if reason else 'No reason <:HYPERKINGCRIMSONANGRY:356798314752245762>'
        try:
            await user.add_roles(mute_role, reason=f'[{ctx.author}] {reason}')
        except discord.HTTPException:
            await ctx.send('Could not mute user {}'.format(user))
            return

        guild_timeouts = self.timeouts.get(guild.id, {})
        task = guild_timeouts.get(user.id)
        if task:
            task.cancel()
            await self.remove_timeout(user.id, guild.id)

        try:
            await ctx.send('Muted user {} `{}`'.format(user.name, user.id))
        except discord.HTTPException:
            pass

        author = ctx.author
        description = '{} muted {} {}'.format(author.mention, user, user.id)
        url = f'https://discordapp.com/channels/{guild.id}/{ctx.channel.id}/{ctx.message.id}'
        embed = discord.Embed(title='🤐 Moderation action [MUTE]',
                              timestamp=datetime.utcnow(),
                              description=description)
        embed.add_field(name='Reason', value=reason)
        embed.add_field(name='link', value=url)
        embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
        embed.set_footer(text=str(author), icon_url=author.avatar_url or author.default_avatar_url)
        msg = await self.send_to_modlog(guild, embed=embed)
        await self.add_mute_reason(ctx, user.id, reason,
                                   modlog_message_id=msg.id if msg else None)

    @command(ignore_extra=True, no_dm=True)
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

            _check = basic_check(user, ctx.channel)

            def check(msg):
                return _check(msg) and msg.content.lower() in ('accept', 'reject', 'no', 'deny', 'decline', 'i refuse')

            try:
                msg = await self.bot.wait_for('message', check=check, timeout=120)
            except asyncio.TimeoutError:
                return await ctx.send('Took too long.')

            if msg.content.lower() != 'accept':
                return await ctx.send(f'{user} declined')

            td = timedelta(minutes=minutes)

            expires_on = datetime2sql(datetime.utcnow() + td)
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
                                   author=ctx.guild.me)
            try:
                await loser.add_roles(mute_role, reason=f'Lost mute roll to {ctx.author}')
            except discord.DiscordException:
                return await ctx.send('Failed to mute loser')

            await self.bot.dbutil.increment_mute_roll(ctx.guild.id, ctx.author.id, loser != ctx.author)
            await self.bot.dbutil.increment_mute_roll(ctx.guild.id, user.id, loser != user)
        finally:
            state.discard(user.id)
            state.discard(ctx.author.id)

    async def remove_timeout(self, user_id, guild_id):
        try:
            sql = 'DELETE FROM `timeouts` WHERE `guild`=:guild AND `user`=:user'
            await self.bot.dbutil.execute(sql, params={'guild': guild_id, 'user': user_id}, commit=True)
        except SQLAlchemyError:
            logger.exception('Could not delete untimeout')

    async def add_timeout(self, ctx, guild_id, user_id, expires_on, as_seconds,
                          reason='No reason', author=None, modlog_msg=None):

        await self.add_mute_reason(ctx, user_id, reason, author=author,
                                   modlog_message_id=modlog_msg,
                                   duration=as_seconds)
        try:
            await self.bot.dbutil.add_timeout(guild_id, user_id, expires_on)
        except SQLAlchemyError:
            logger.exception('Could not save timeout')
            await ctx.send('Could not save timeout. Canceling action')
            return False

        if guild_id not in self.timeouts:
            guild_timeouts = {}
            self.timeouts[guild_id] = guild_timeouts
        else:
            guild_timeouts = self.timeouts.get(guild_id)

        t = guild_timeouts.get(user_id)
        if t:
            t.cancel()

        task = call_later(self.untimeout, self.bot.loop,
                          as_seconds, user_id, guild_id,
                          after=lambda f: guild_timeouts.pop(user_id, None))

        guild_timeouts[user_id] = task
        return True

    async def untimeout(self, user_id, guild_id):
        mute_role = self.bot.guild_cache.mute_role(guild_id)
        if mute_role is None:
            return

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            await self.remove_timeout(user_id, guild_id)
            return

        user = guild.get_member(user_id)
        if not user:
            await self.remove_timeout(user_id, guild_id)
            return

        if guild.get_role(mute_role):
            try:
                await user.remove_roles(Snowflake(mute_role), reason='Unmuted')
            except discord.HTTPException:
                logger.exception('Could not autounmute user %s' % user.id)
        await self.remove_timeout(user.id, guild.id)

    @command(no_pm=True)
    @bot_has_permissions(manage_channels=True)
    @has_permissions(manage_channels=True)
    async def slowmode(self, ctx, time: int):
        try:
            await ctx.channel.edit(slowmode_delay=time)
        except discord.HTTPException as e:
            await ctx.send('Failed to set slowmode because of an error\n%s' % e)
        except:
            logger.exception('Failed to set slowmode')
            await ctx.send('Failed to set slowmode because of an unknown error')

        else:
            await ctx.send('Slowmode set to %ss' % time)

    def _reason_url(self, ctx, reason):
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

    async def add_mute_reason(self, ctx, user_id, reason, author=None, modlog_message_id=None, duration=None):
        embed = self._reason_url(ctx, reason)
        await self.bot.dbutil.add_timeout_log(ctx.guild.id, user_id,
                                              author.id if author else ctx.author.id,
                                              reason, embed, ctx.message.created_at,
                                              modlog_message_id,
                                              duration)

    async def edit_mute_reason(self, ctx, user_id, reason):
        embed = self._reason_url(ctx, reason)
        await self.bot.dbutil.edit_timeout_log(ctx.guild.id, user_id, ctx.author.id,
                                               reason, embed)

    @command(aliases=['tlogs'])
    @bot_has_permissions(embed_links=True)
    @cooldown(1, 6, BucketType.user)
    async def timeout_logs(self, ctx, *, user: discord.User=None):
        user = user or ctx.author
        rows = await self.bot.dbutil.get_timeout_logs(ctx.guild.id, user.id)
        if rows is False:
            return await ctx.send(f'Failed to get timeout logs for user {user}')

        if not rows:
            return await ctx.send(f'No timeouts for {user}')

        paginator = Paginator(title=f'Timeouts for {user}', init_page=False)

        description = ''
        s_format = '{time} ago {duration} by {author} for the reason "{reason}"\n'
        for row in rows:
            time = format_timedelta(datetime.utcnow() - row['time'], DateAccuracy.Day)
            if row['duration']:
                duration = 'for '
                duration += format_timedelta(timedelta(seconds=row['duration']), DateAccuracy.Day-DateAccuracy.Hour)
            else:
                duration = 'permanently'
            author = self.bot.get_user(row['author'])
            description += s_format.format(time=time, author=author or row['author'],
                                           reason=row['reason'], duration=duration)

        paginator.add_page(description=description, paginate_description=True)
        paginator.finalize()
        pages = paginator.pages

        await send_paged_message(ctx, pages, embed=True)

    @command(aliases=['temp_mute'], no_pm=True)
    @bot_has_permissions(manage_roles=True)
    @has_permissions(manage_roles=True)
    @cooldown(1, 3, BucketType.user)
    async def timeout(self, ctx, user: MentionedMember, *, timeout):
        """Mute user for a specified amount of time
         `timeout` is the duration of the mute.
         The format is `n d|days` `n h|hours` `n m|min|minutes` `n s|sec|seconds` `reason`
         where at least one of them must be provided.
         Maximum length for a timeout is 30 days
         e.g. `{prefix}{name} <@!12345678> 10d 10h 10m 10s This is the reason for the timeout`
        """
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

        if user.id == ctx.author.id and time.total_seconds() < 21600:
            return await ctx.send('If you gonna timeout yourself at least make it a longer timeout')

        if guild.id == 217677285442977792 and user.id == 123050803752730624:
            return await ctx.send("Not today kiddo. I'm too powerful for you")

        r = guild.get_role(339841138393612288)
        if not ctx.author.id == 123050803752730624 and self.bot.anti_abuse_switch and r in user.roles and r in ctx.author.roles:
            return await ctx.send('All hail our leader <@!222399701390065674>')

        abusers = (189458911886049281, 117699419951988737)
        if user.id in abusers and ctx.author.id in abusers:
            return await ctx.send("Abuse this 🖕")

        if ctx.author.id in abusers and mute_role in ctx.author.roles:
            return await ctx.send("Abuse this 🖕")

        if guild.id == 217677285442977792 and ctx.author.id == 117256618617339905 and user.id == 189458911886049281:
            return await ctx.send('No <:peepoWeird:423445885180051467>')

        if ctx.author != guild.owner and ctx.author.top_role <= user.top_role:
            return await ctx.send('The one you are trying to timeout is higher or same as you in the role hierarchy')

        if time.days > 30:
            return await ctx.send("Timeout can't be longer than 30 days")
        if guild.id == 217677285442977792 and time.total_seconds() < 500:
            return await ctx.send('This server is retarded so I have to hardcode timeout limits and the given time is too small')
        if time.total_seconds() < 59:
            return await ctx.send('Minimum timeout is 1 minute')

        now = datetime.utcnow()

        if guild.id == 217677285442977792:
            words = ('game', 'phil', 'ligma', 'christianserver', 'sugondese', 'deeznuts', 'haha', 'mute', 'lost')
            rs = '' if not reason else reason.lower().replace(' ', '')
            gay = not reason or any([word in rs for word in words])

            if ctx.author.id in abusers and gay:
                if mute_role not in ctx.author.roles:
                    very_gay = timedelta(seconds=time.total_seconds()*2)
                    await ctx.send('Abuse this <:christianServer:336568327939948546>')
                    await ctx.author.add_roles(mute_role, reason='Abuse this')
                    await self.add_timeout(ctx, guild.id, ctx.author.id, datetime2sql(now + very_gay), very_gay.total_seconds(),
                                           reason='Abuse this <:christianServer:336568327939948546>')

        reason = reason if reason else 'No reason <:HYPERKINGCRIMSONANGRY:356798314752245762>'
        expires_on = datetime2sql(now + time)

        try:
            await user.add_roles(mute_role, reason=f'[{ctx.author}] {reason}')
            await ctx.send('Muted user {} for {}'.format(user, time))
        except discord.HTTPException:
            await ctx.send('Could not mute user {}'.format(user))
            return

        author = ctx.message.author
        description = '{} muted {} `{}` for {}'.format(author.mention,
                                                       user, user.id, time)

        url = f'https://discordapp.com/channels/{guild.id}/{ctx.channel.id}/{ctx.message.id}'
        embed = discord.Embed(title='🕓 Moderation action [TIMEOUT]',
                              timestamp=datetime.utcnow() + time,
                              description=description)
        embed.add_field(name='Reason', value=reason)
        embed.add_field(name='link', value=url)
        embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
        embed.set_footer(text='Expires at', icon_url=author.avatar_url or author.default_avatar_url)

        msg = await self.send_to_modlog(guild, embed=embed)
        await self.add_timeout(ctx, guild.id, user.id, expires_on,
                               time.total_seconds(),
                               reason=reason,
                               modlog_msg=msg.id if msg else None)

    @group(invoke_without_command=True, no_pm=True)
    @bot_has_permissions(manage_roles=True)
    @has_permissions(manage_roles=True)
    async def unmute(self, ctx, user: MentionedMember):
        """Unmute a user"""
        guild = ctx.guild
        mute_role = self.bot.guild_cache.mute_role(guild.id)
        if mute_role is None:
            return await ctx.send(f'No mute role set. You can set it with {ctx.prefix}settings mute_role role name')

        if guild.id == 217677285442977792 and user.id == 123050803752730624:
            return await ctx.send("Not today kiddo. I'm too powerful for you")

        mute_role = guild.get_role(mute_role)
        if mute_role is None:
            return await ctx.send('Could not find the muted role')

        try:
            await user.remove_roles(mute_role, reason=f'Responsible user {ctx.author}')
        except discord.HTTPException:
            await ctx.send('Could not unmute user {}'.format(user))
        else:
            await ctx.send('Unmuted user {}'.format(user))
            t = self.timeouts.get(guild.id, {}).get(user.id)
            if t:
                t.cancel()

    async def _unmute_when(self, ctx, user, embed=True):
        guild = ctx.guild
        member = user if user else ctx.author

        muted_role = self.bot.guild_cache.mute_role(guild.id)
        if not muted_role:
            return await ctx.send(f'No mute role set on this server. You can set it with {ctx.prefix}settings mute_role role name')

        if not list(filter(lambda r: r.id == muted_role, member.roles)):
            return await ctx.send('%s is not muted' % member)

        row = await self.bot.dbutil.get_latest_timeout_log(guild.id, member.id)
        if row is False:
            return await ctx.send('Failed to check mute status')

        if not row:
            return await ctx.send(f'User {member} is permamuted without a reason')

        td = f'User {member} is permamuted\n'
        if row['expires_on']:
            delta = row['expires_on'] - datetime.utcnow()
            td = seconds2str(delta.total_seconds(), False)
            td = f'Timeout for {member} expires in {td}\n'

        reason = row['reason']
        author = row['author']
        author_user = self.bot.get_user(author)

        if not author_user:
            author = f'User responsible for timeout: `uid {author}`\n'
        else:
            author = f'User responsible for timeout: {author_user} `{author_user.id}`\n'

        muted_at = row['time']
        td_at = datetime.utcnow() - muted_at
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
    def purge_embed(ctx, messages, users: set=None, multiple_channels=False):
        author = ctx.author
        if not multiple_channels:
            d = '%s removed %s messages in %s' % (author.mention, len(messages), ctx.channel.mention)
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
            return await ctx.send(f'Failed to purge messages\n{e}')

        modlog = self.get_modlog(channel.guild)
        if not modlog:
            return

        embed = self.purge_embed(ctx, messages)
        await self.send_to_modlog(channel.guild, embed=embed)

    @purge.command(name='from', no_pm=True, ignore_extra=True)
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

        max_messages = min(300, max_messages)
        modlog = self.get_modlog(guild)

        if isinstance(user, discord.User):
            user = user.id

        if channel is not None:
            messages = await channel.purge(limit=max_messages, check=lambda m: m.author.id == user)

            if modlog and messages:
                embed = self.purge_embed(ctx, messages, users={'<@!%s>' % user})
                await self.send_to_modlog(guild, embed=embed)

            return

        t = datetime.utcnow() - timedelta(days=14)
        t = datetime2sql(t)
        sql = 'SELECT `message_id`, `channel` FROM `messages` WHERE guild=%s AND user_id=%s AND DATE(`time`) > "%s" ' % (guild.id, user, t)

        if channel is not None:
            sql += 'AND channel=%s ' % channel.id

        sql += 'ORDER BY `message_id` DESC LIMIT %s' % max_messages

        rows = (await self.bot.dbutil.execute(sql)).fetchall()

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
            sql = 'DELETE FROM `messages` WHERE `message_id` IN (%s)' % ', '.join([str(i.id) for i in ids])
            try:
                await self.bot.dbutil.execute(sql, commit=True)
            except SQLAlchemyError:
                logger.exception('Could not delete messages from database')

            if modlog:
                embed = self.purge_embed(ctx, ids, users={'<@!%s>' % user}, multiple_channels=len(channel_messages.keys()) > 1)
                await self.send_to_modlog(guild, embed=embed)

    @purge.command(name='until', no_pm=True, ignore_extra=True)
    @cooldown(2, 4, BucketType.guild)
    @bot_has_permissions(manage_messages=True)
    @has_permissions(manage_messages=True)
    async def purge_until(self, ctx, message_id: int, limit: int=100):
        """Purges messages until the specified message is reached or the limit is exceeded
        limit the max limit is 500 is the specified message is under 2 weeks old
        otherwise the limit is 100"""
        channel = ctx.channel
        try:
            message = await channel.get_message(message_id)
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
            deleted = await channel.purge(limit=limit, check=check, before=ctx.message)
        except discord.HTTPException as e:
            await ctx.send(f'Failed to delete messages because of an error\n{e}')
        else:
            await ctx.send(f'Deleted {len(deleted)} messages')

    @command(no_pm=True, ignore_extra=True, aliases=['softbab'])
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

    @command(ignore_extra=True, aliases=['zawarudo'], no_pm=True)
    @cooldown(1, 5, BucketType.guild)
    @bot_has_permissions(manage_channels=True, manage_roles=True)
    @has_permissions(manage_channels=True, manage_roles=True)
    async def lock(self, ctx):
        """Set send_messages permission override of everyone to false on current channel"""
        await self._set_channel_lock(ctx, True, zawarudo=ctx.invoked_with == 'zawarudo')

    @command(ignore_extra=True, aliases=['tokiwougokidasu'], no_pm=True)
    @cooldown(1, 5, BucketType.guild)
    @bot_has_permissions(manage_channels=True, manage_roles=True)
    @has_permissions(manage_channels=True, manage_roles=True)
    async def unlock(self, ctx):
        """Set send_messages permission override on current channel to default position"""
        await self._set_channel_lock(ctx, False, zawarudo=ctx.invoked_with == 'tokiwougokidasu')

    def get_temproles(self, guild: int):
        temproles = self.temproles.get(guild, None)
        if temproles is None:
            temproles = {}
            self.temproles[guild] = temproles

        return temproles

    async def remove_role(self, user, role, guild):
        guild = self.bot.get_guild(guild)
        if not guild:
            await self.bot.dbutil.remove_temprole(user, role)
            return

        user = guild.get_member(user)

        if not user:
            await self.bot.dbutil.remove_temprole(user, role)
            return

        try:
            await user.remove_roles(Snowflake(role), reason='Removed temprole')
        except discord.HTTPException:
            pass

        await self.bot.dbutil.remove_temprole(user, role)

    def register_temprole(self, user: int, role: int, guild: int, time):
        temproles = self.get_temproles(guild)
        old = temproles.get(user)
        if old:
            old.cancel()

        if time <= 1:
            time = 1

        task = call_later(self.remove_role, self.bot.loop, time,
                          user, role, guild, after=lambda _: temproles.pop(user))

        temproles[user] = task

    @command(ignore_extra=True, no_pm=True)
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 5, BucketType.guild)
    async def temprole(self, ctx, time: TimeDelta, user: discord.Member, *, role: discord.Role):
        if time.days > 7:
            return await ctx.send('Max days is 7')

        total_seconds = time.total_seconds()

        if total_seconds < 60:
            return await ctx.send('Must be over minute')

        bot = ctx.guild.me
        if role > bot.top_role:
            return await ctx.send('Role is higher than my top role')

        if role > ctx.author.top_role:
            return await ctx.send('Role is higher than your top role')

        expires_at = datetime.utcnow() + time

        self.register_temprole(user.id, role.id, user.guild.id, total_seconds)
        expires_at = datetime2sql(expires_at)
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
        modlog = self.get_modlog(ctx.guild)
        if not modlog:
            return await ctx.send('Modlog not found')

        is_msg = isinstance(user_or_message, int)
        s = ''
        row = None

        if is_msg:
            message_id = user_or_message
            try:
                msg = await modlog.get_message(message_id)
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
                user_id = int(user_id[-1])

        else:
            user = user_or_message
            user_id = user.id
            row = await self.bot.dbutil.get_latest_timeout_log_for(ctx.guild.id, user.id, ctx.author.id)
            if row is False:
                return await ctx.send('Failed to get timeout from database')

            if not row:
                return await ctx.send(f"You have never muted {user}")

            msg = None
            embed = None
            if row['message']:
                try:
                    msg = await modlog.get_message(row['message'])
                except discord.HTTPException:
                    s += f'Failed to get modlog entry\n'
                else:
                    if msg.embeds:
                        embed = msg.embeds[0]

        if embed:
            idx = -1
            for idx, field in enumerate(embed.fields):
                if field.name == 'Reason':
                    break

            if idx < 0:
                if is_msg:
                    return await ctx.send('No reason found')

                s += 'No modlog reason found\n'

            embed.set_field_at(idx, name='Reason', value=reason)

            if msg:
                try:
                    await msg.edit(embed=embed)
                except discord.HTTPException as e:
                    s += f'Failed to edit modlog reason because of an error.\n{e}\n'

        if user_id:
            await self.edit_mute_reason(ctx, user_id, reason)

        if row:
            td = datetime.utcnow() - row['time']
            # td formatted from day to hour
            td = format_timedelta(td, DateAccuracy.Day-DateAccuracy.Hour)
            s += f'Reason for the mute of {user_or_message} from {td} ago was edited'
        else:
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
