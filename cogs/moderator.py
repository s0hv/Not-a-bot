import asyncio
import logging
import os
from datetime import datetime, timedelta
from random import randint, random

import discord
from discord.ext.commands import cooldown, BucketType
from sqlalchemy.exc import SQLAlchemyError

from bot.bot import command, group
from bot.converters import MentionedMember, MentionedUser
from bot.globals import Perms, DATA
from cogs.cog import Cog
from utils.utilities import (call_later, parse_timeout,
                             datetime2sql, get_avatar, get_user_id, find_user,
                             seconds2str, get_role, get_channel, Snowflake,
                             basic_check, sql2timedelta)

logger = logging.getLogger('debug')
manage_roles = discord.Permissions(268435456)
lock_perms = discord.Permissions(268435472)


class Moderator(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.timeouts = self.bot.timeouts
        self.automute_blacklist = {}
        self.automute_whitelist = {}
        self._current_rolls = {}  # Users currently active in a mute roll
        self._load_timeouts()
        self._load_automute()

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

    def _load_timeouts(self):
        session = self.bot.get_session
        sql = 'SELECT * FROM `timeouts`'
        rows = session.execute(sql)
        for row in rows:
            try:
                time = row['expires_on'] - datetime.utcnow()
                guild = row['guild']
                user = row['user']

                task = call_later(self.untimeout, self.bot.loop, time.total_seconds(),
                                  user, guild)

                if guild not in self.timeouts:
                    guild_timeouts = {}
                    self.timeouts[guild] = guild_timeouts
                else:
                    guild_timeouts = self.timeouts.get(guild)

                t = guild_timeouts.get(user)
                if t:
                    t.cancel()

                guild_timeouts[user] = task
                task.add_done_callback(lambda f: guild_timeouts.pop(user, None))

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

        await channel.send(*args, **kwargs)

    async def on_message(self, message):
        guild = message.guild
        if guild and self.bot.guild_cache.automute(guild.id):
            mute_role = self.bot.guild_cache.mute_role(guild.id)
            mute_role = discord.utils.find(lambda r: r.id == mute_role, message.guild.roles)
            user = message.author

            if mute_role in user.roles:
                return
            limit = self.bot.guild_cache.automute_limit(guild.id)
            if mute_role and len(message.mentions) + len(message.role_mentions) > limit:
                blacklist = self.automute_blacklist.get(guild.id, ())

                if message.channel.id not in blacklist:
                    whitelist = self.automute_whitelist.get(guild.id, ())
                    invulnerable = discord.utils.find(lambda r: r.id in whitelist,
                                                      message.guild.roles)

                    if invulnerable is None or invulnerable not in user.roles:
                        time = self.bot.guild_cache.automute_time(guild.id)

                        if time is not None:
                            if isinstance(time, str):
                                time = sql2timedelta(time)
                            await self.add_timeout(message.channel, guild.id, user.id, datetime.utcnow() + time, time.total_seconds())
                            d = 'Automuted user {0} `{0.id}` for {1}'.format(message.author, time)
                        else:
                            d = 'Automuted user {0} `{0.id}`'.format(message.author)

                        await message.author.add_roles(mute_role, reason='[Automute] too many mentions in message')
                        embed = discord.Embed(title='Moderation action [AUTOMUTE]', description=d, timestamp=datetime.utcnow())
                        embed.add_field(name='Reason', value='Too many mentions in a message')
                        embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                        embed.set_footer(text=str(self.bot.user), icon_url=self.bot.user.avatar_url or self.bot.user.default_avatar_url)
                        await self.send_to_modlog(guild, embed=embed)
                        return

    @group(invoke_without_command=True)
    @cooldown(2, 5, BucketType.guild)
    async def automute_whitelist(self, ctx):
        """Show roles whitelisted from automutes"""
        guild = ctx.guild
        roles = self.automute_whitelist.get(guild.id, ())
        roles = map(lambda r: self.bot.get_role(r, guild), roles)
        roles = [r for r in roles if r]
        if not roles:
            return await ctx.send('No roles whitelisted from automutes')

        msg = 'Roles whitelisted from automutes'
        for r in roles:
            msg += '\n{0.name} `{0.id}`'.format(r)

        await ctx.send(msg)

    @automute_whitelist.command(required_perms=Perms.MANAGE_GUILD | Perms.MANAGE_ROLES)
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

        success = await self.bot.dbutils.add_automute_whitelist(guild.id, role_.id)
        if not success:
            return await ctx.send('Failed to add role because of an error')

        roles.add(role_.id)
        await ctx.send('Added role {0.name} `{0.id}`'.format(role_))

    @automute_whitelist.command(required_perms=Perms.MANAGE_GUILD | Perms.MANAGE_ROLES, aliases=['del', 'delete'])
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

        success = await self.bot.dbutils.remove_automute_whitelist(guild.id, role.id)
        if not success:
            return await ctx.send('Failed to remove role because of an error')

        roles.discard(role_.id)
        await ctx.send('Role {0.name} `{0.id}` removed from automute whitelist'.format(role_))

    @group(invoke_without_command=True, name='automute_blacklist')
    @cooldown(2, 5, BucketType.guild)
    async def automute_blacklist_(self, ctx):
        """Show channels that are blacklisted from automutes.
        That means automutes won't triggered from messages sent in those channels"""
        guild = ctx.guild
        channels = self.automute_blacklist.get(guild.id, ())
        channels = map(lambda c: guild.get_channel(c), channels)
        channels = [c for c in channels if c]
        if not channels:
            return await ctx.send('No channels blacklisted from automutes')

        msg = 'Channels blacklisted from automutes'
        for c in channels:
            msg += '\n{0.name} `{0.id}`'.format(c)

        await ctx.send(msg)

    @automute_blacklist_.command(required_perms=Perms.MANAGE_GUILD | Perms.MANAGE_ROLES, name='add')
    @cooldown(2, 5, BucketType.guild)
    async def add_(self, ctx, *, channel):
        """Add a channel to the automute blacklist"""
        guild = ctx.guild
        channels = self.automute_blacklist.get(guild.id)
        if channels is None:
            channels = set()
            self.automute_whitelist[guild.id] = channels

        channel_ = get_channel(guild.channels, channel, name_matching=True)
        if not channel_:
            return await ctx.send('Channel {} not found'.format(channel))

        success = await self.bot.dbutils.add_automute_blacklist(guild.id, channel_.id)
        if not success:
            return await ctx.send('Failed to add channel because of an error')

        channels.add(channel_.id)
        await ctx.send('Added channel {0.name} `{0.id}`'.format(channel_))

    @automute_blacklist_.command(required_perms=Perms.MANAGE_GUILD | Perms.MANAGE_ROLES, name='remove', aliases=['del', 'delete'])
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
    @command(required_perms=manage_roles)
    @cooldown(2, 5, BucketType.guild)
    async def add_role(self, ctx, name, random_color=True, mentionable=True, hoist=False):
        """Add a role to the server.
        random_color makes the bot choose a random color for the role and
        hoist will make the role show up in the member list"""
        guild = ctx.guild
        if guild is None:
            return await ctx.send('Cannot create roles in DM')

        default_perms = guild.default_role.permissions
        color = None
        if random_color:
            color = discord.Color(randint(0, 16777215))
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
            await ctx.send('No mute role set')
            return False

        mute_role = self.bot.get_role(mute_role, guild)
        if mute_role is None:
            await ctx.send('Could not find the mute role')
            return False

        return mute_role

    @command(required_perms=manage_roles)
    async def mute(self, ctx, user: MentionedMember, *reason):
        """Mute a user. Only works if the server has set the mute role"""
        mute_role = await self._mute_check(ctx)
        if not mute_role:
            return

        guild = ctx.guild
        if guild.id == 217677285442977792 and user.id == 123050803752730624:
            return await ctx.send("Not today kiddo. I'm too powerful for you")

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
            self.remove_timeout(user.id, guild.id)

        try:
            await ctx.send('Muted user {} `{}`'.format(user.name, user.id))
            chn = self.get_modlog(guild)
            if chn:
                author = ctx.author
                description = '{} muted {} {}'.format(author.mention, user, user.id)
                embed = discord.Embed(title='🤐 Moderation action [MUTE]',
                                      timestamp=datetime.utcnow(),
                                      description=description)
                embed.add_field(name='Reason', value=reason)
                embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                embed.set_footer(text=str(author), icon_url=author.avatar_url or author.default_avatar_url)
                await self.send_to_modlog(guild, embed=embed)
        except discord.HTTPException:
            pass

    @command(required_perms=manage_roles)
    async def mute_roll(self, ctx, user: discord.Member, hours: int):
        if not 0 < hours < 11:
            return ctx.send('Mute length should be between 1 and 10 (hours)')

        if ctx.author == user:
            return await ctx.send("Can't play yourself")

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
            await ctx.send(f'{user.mention} type accept to join this mute roll of {hours} hours')

            def check(msg):
                return basic_check(user, ctx.channel) and msg.content.lower() == 'accept'

            try:
                await self.bot.wait_for('message', check=check, timeout=120)
            except asyncio.TimeoutError:
                return ctx.send('Took too long.')

            td = timedelta(hours=hours)
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
            if counter:
                p = os.path.join(DATA, 'templates', 'reverse.png')
                await asyncio.sleep(2)
                await ctx.send(f'{choices[loser]} counters', file=discord.File(p))

                loser = abs(loser - 1)
                await msg.edit(content=f'{user} vs {ctx.author}\nLoser: {choices[loser]}')

            if counter_counter:
                p = os.path.join(DATA, 'templates', 'counter_counter.png')
                await asyncio.sleep(2)
                await ctx.send(f'{choices[loser]} counters the counter', file=discord.File(p))

                loser = abs(loser - 1)
                await msg.edit(content=f'{user} vs {ctx.author}\nLoser: {choices[loser]}')

            loser = choices[loser]
            await asyncio.sleep(3)
            await self.add_timeout(ctx, ctx.guild.id, loser.id, expires_on, td.total_seconds())
            await loser.add_roles(mute_role, reason=f'Lost mute roll to {ctx.author}')
        finally:
            state.discard(user.id)
            state.discard(ctx.author.id)

    def remove_timeout(self, user_id, guild_id):
        session = self.bot.get_session
        try:
            sql = 'DELETE FROM `timeouts` WHERE `guild`=:guild AND `user`=:user'
            session.execute(sql, params={'guild': guild_id, 'user': user_id})
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Could not delete untimeout')

    async def add_timeout(self, ctx, guild_id, user_id, expires_on, as_seconds):
        try:
            sql = 'INSERT INTO `timeouts` (`guild`, `user`, `expires_on`) VALUES ' \
                  '(:guild, :user, :expires_on) ON DUPLICATE KEY UPDATE expires_on=VALUES(expires_on)'

            d = {'guild': guild_id, 'user': user_id, 'expires_on': expires_on}
            await self.bot.dbutils.execute(sql, params=d, commit=True)
        except SQLAlchemyError:
            logger.exception('Could not save timeout')
            await ctx.send('Could not save timeout. Canceling action')
            return False

        task = call_later(self.untimeout, self.bot.loop,
                          as_seconds, user_id, guild_id)

        if guild_id not in self.timeouts:
            guild_timeouts = {}
            self.timeouts[guild_id] = guild_timeouts
        else:
            guild_timeouts = self.timeouts.get(guild_id)

        t = guild_timeouts.get(user_id)
        if t:
            t.cancel()

        guild_timeouts[user_id] = task
        task.add_done_callback(lambda f: guild_timeouts.pop(user_id, None))

        return True

    async def untimeout(self, user_id, guild_id):
        mute_role = self.bot.guild_cache.mute_role(guild_id)
        if mute_role is None:
            return

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            self.remove_timeout(user_id, guild_id)
            return

        user = guild.get_member(user_id)
        if not user:
            self.remove_timeout(user_id, guild_id)
            return

        if self.bot.get_role(mute_role, guild):
            try:
                await user.remove_roles(Snowflake(mute_role), reason='Unmuted')
            except discord.HTTPException:
                logger.exception('Could not autounmute user %s' % user.id)
        self.remove_timeout(user.id, guild.id)

    @command(aliases=['temp_mute'], required_perms=manage_roles)
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

        time, reason = parse_timeout(timeout)
        guild = ctx.guild
        if not time:
            return await ctx.send('Invalid time string')

        if user.id == ctx.author.id and time.total_seconds() < 21600:
            return await ctx.send('If you gonna timeout yourself at least make it a longer timeout')

        # Abuse protection for my server
        nigu_nerea = (287664210152783873, 208185517412581376)
        if user.id in nigu_nerea and ctx.author.id in nigu_nerea:
            return await ctx.send("It's time to stop")

        if guild.id == 217677285442977792 and user.id == 123050803752730624:
            return await ctx.send("Not today kiddo. I'm too powerful for you")

        r = self.bot.get_role(339841138393612288, guild)
        if self.bot.anti_abuse_switch and r in user.roles and r in ctx.author.roles:
            return await ctx.send('All hail our leader <@!222399701390065674>')

        if time.days > 30:
            return await ctx.send("Timeout can't be longer than 30 days")
        if guild.id == 217677285442977792 and time.total_seconds() < 500:
            return await ctx.send('This server is retarded so I have to hardcode timeout limits and the given time is too small')
        if time.total_seconds() < 59:
            return await ctx.send('Minimum timeout is 1 minute')

        now = datetime.utcnow()
        expires_on = datetime2sql(now + time)
        await self.add_timeout(ctx, guild.id, user.id, expires_on, time.total_seconds())

        reason = reason if reason else 'No reason <:HYPERKINGCRIMSONANGRY:356798314752245762>'

        try:
            await user.add_roles(mute_role, reason=f'[{ctx.author}] {reason}')
            try:
                sql = 'INSERT INTO `timeout_logs` (`guild`, `user`, `time`, `reason`) VALUES ' \
                      '(:guild, :user, :time, :reason)'
                d = {'guild': guild.id, 'user': ctx.author.id,
                     'time': time.total_seconds(), 'reason': reason}
                await self.bot.dbutils.execute(sql, params=d, commit=True)
            except SQLAlchemyError:
                logger.exception('Fail to log timeout')

            await ctx.send('Muted user {} for {}'.format(user, time))
            chn = self.get_modlog(guild)
            if chn:
                author = ctx.message.author
                description = '{} muted {} `{}` for {}'.format(author.mention,
                                                               user, user.id, time)

                embed = discord.Embed(title='🕓 Moderation action [TIMEOUT]',
                                      timestamp=datetime.utcnow() + time,
                                      description=description)
                embed.add_field(name='Reason', value=reason)
                embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                embed.set_footer(text='Expires at', icon_url=author.avatar_url or author.default_avatar_url)

                await self.send_to_modlog(guild, embed=embed)
        except discord.HTTPException:
            await ctx.send('Could not mute user {}'.format(user))

    @group(required_perms=manage_roles, invoke_without_command=True, no_pm=True)
    async def unmute(self, ctx, user: MentionedMember):
        """Unmute a user"""
        guild = ctx.guild
        mute_role = self.bot.guild_cache.mute_role(guild.id)
        if mute_role is None:
            return await ctx.send('No mute role set')

        if guild.id == 217677285442977792 and user.id == 123050803752730624:
            return await ctx.send("Not today kiddo. I'm too powerful for you")

        mute_role = self.bot.get_role(mute_role, guild)
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

    async def _unmute_when(self, ctx, user):
        guild = ctx.guild
        if user:
            member = find_user(' '.join(user), guild.members, case_sensitive=True, ctx=ctx)
        else:
            member = ctx.author

        if not member:
            return await ctx.send('User %s not found' % ' '.join(user))
        muted_role = self.bot.guild_cache.mute_role(guild.id)
        if not muted_role:
            return await ctx.send('No mute role set on this server')

        if not list(filter(lambda r: r.id == muted_role, member.roles)):
            return await ctx.send('%s is not muted' % member)

        sql = 'SELECT expires_on FROM `timeouts` WHERE guild=%s AND user=%s' % (guild.id, member.id)
        session = self.bot.get_session

        row = session.execute(sql).first()
        if not row:
            return await ctx.send('User %s is permamuted' % str(member))

        delta = row['expires_on'] - datetime.utcnow()
        await ctx.send('Timeout for %s expires in %s' % (member, seconds2str(delta.total_seconds())))

    @unmute.command(no_pm=True, required_perms=discord.Permissions(0))
    @cooldown(1, 3, BucketType.user)
    async def when(self, ctx, *user):
        """Shows how long you are still muted for"""
        await self._unmute_when(ctx, user)

    @command(no_pm=True)
    @cooldown(1, 3, BucketType.user)
    async def unmute_when(self, ctx, *user):
        """Shows how long you are still muted for"""
        await self._unmute_when(ctx, user)

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

    @group(required_perms=Perms.MANAGE_MESSAGES, invoke_without_command=True, no_pm=True)
    @cooldown(2, 4, BucketType.guild)
    async def purge(self, ctx, max_messages: int=10):
        """Purges n amount of messages from a channel.
        maximum value of max_messages is 500 and the default is 10"""
        channel = ctx.channel
        if max_messages > 1000000:
            return await ctx.send("Either you tried to delete over 1 million messages or just put it there as an accident. "
                                  "Either way that's way too much for me to handle")

        max_messages = min(500, max_messages)

        # purge doesn't support reasons yet
        messages = await channel.purge(limit=max_messages)  # , reason=f'{ctx.author} purged messages')

        modlog = self.get_modlog(channel.guild)
        if not modlog:
            return

        embed = self.purge_embed(ctx, messages)
        await self.send_to_modlog(channel.guild, embed=embed)

    @purge.command(name='from', required_perms=Perms.MANAGE_MESSAGES, no_pm=True, ignore_extra=True)
    @cooldown(2, 4, BucketType.guild)
    async def from_(self, ctx, user: MentionedUser, max_messages: int=10, channel: discord.TextChannel=None):
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

        if channel is not None:
            messages = await channel.purge(limit=max_messages, check=lambda m: m.author.id == user.id)

            if modlog and messages:
                embed = self.purge_embed(ctx, messages, users={'<@!%s>' % user.id})
                await self.send_to_modlog(guild, embed=embed)

            return

        t = datetime.utcnow() - timedelta(days=14)
        t = datetime2sql(t)
        sql = 'SELECT `message_id`, `channel` FROM `messages` WHERE guild=%s AND user_id=%s AND DATE(`time`) > "%s" ' % (guild.id, user, t)

        if channel is not None:
            sql += 'AND channel=%s ' % channel.id

        sql += 'ORDER BY `message_id` DESC LIMIT %s' % max_messages
        session = self.bot.get_session

        rows = session.execute(sql).fetchall()

        channel_messages = {}
        for r in rows:
            if r['channel'] not in channel_messages:
                message_ids = []
                channel_messages[r['channel']] = message_ids
            else:
                message_ids = channel_messages[r['channel']]

            message_ids.append(Snowflake(r['message_id']))

        ids = []
        for k in channel_messages:
            channel = self.bot.get_channel(k)
            try:
                await self.delete_messages(channel, channel_messages[k])
            except discord.HTTPException:
                logger.exception('Could not delete messages')
            else:
                ids.extend(channel_messages[k])

        if ids:
            sql = 'DELETE FROM `messages` WHERE `message_id` IN (%s)' % ', '.join([i.id for i in ids])
            try:
                session.execute(sql)
                session.commit()
            except SQLAlchemyError:
                session.rollback()
                logger.exception('Could not delete messages from database')

            if modlog:
                embed = self.purge_embed(ctx, ids, users={'<@!%s>' % user}, multiple_channels=len(channel_messages.keys()) > 1)
                await self.send_to_modlog(guild, embed=embed)

    @command(no_pm=True, ignore_extra=True, required_perms=discord.Permissions(4), aliases=['softbab'])
    async def softban(self, ctx, user: MentionedMember, message_days=1):
        """Ban and unban a user from the server deleting that users messages from
        n amount of days in the process"""
        user_ = get_user_id(user)
        guild = ctx.guild
        if user_ is None:
            return await ctx.send('User %s could not be found' % user)

        if not (1 <= message_days <= 7):
            return await ctx.send('Message days must be between 1 and 7')

        try:
            await guild.ban(Snowflake(user_), reason=f'{ctx.author} softbanned', delete_message_days=message_days)
        except discord.Forbidden:
            return await ctx.send("The bot doesn't have ban perms")
        except discord.HTTPException:
            return await ctx.send('Something went wrong while trying to ban. Try again')

        try:
            await guild.unban(Snowflake(user_), reason=f'{ctx.author} softbanned')
        except discord.HTTPException:
            return await ctx.send('Failed to unban after ban')

        member = guild.get_member(user_)
        s = 'Softbanned user '
        if not member:
            s += '<@!{0}> `{0}`'.format(user_)
        else:
            s += '{} `{}`'.format(str(member), member.id)

        await ctx.send(s)

    @command(ignore_extra=True, required_perms=lock_perms, aliases=['zawarudo'])
    @cooldown(2, 5, BucketType.guild)
    async def lock(self, ctx):
        """Set send_messages permission override of everyone to false on current channel"""
        await self._set_channel_lock(ctx, True, zawarudo=ctx.invoked_with == 'zawarudo')

    @command(ignore_extra=True, required_perms=lock_perms, aliases=['tokiwougokidasu'])
    @cooldown(2, 5, BucketType.guild)
    async def unlock(self, ctx):
        """Set send_messages permission override on current channel to default position"""
        await self._set_channel_lock(ctx, False, zawarudo=ctx.invoked_with == 'tokiwougokidasu')

    @staticmethod
    async def delete_messages(channel, message_ids):
        """Delete messages in bulk and take the message limit into account"""
        step = 100
        for idx in range(0, len(message_ids), step):
            await channel.delete_messages(message_ids)

    def get_modlog(self, guild):
        return guild.get_channel(self.bot.guild_cache.modlog(guild.id))


def setup(bot):
    bot.add_cog(Moderator(bot))
