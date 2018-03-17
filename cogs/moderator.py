from cogs.cog import Cog
from bot.bot import command, group
from random import randint
import discord
from discord.ext.commands import cooldown, BucketType
from utils.utilities import (get_users_from_ids, call_later, parse_timeout,
                             datetime2sql, get_avatar, get_user_id, get_channel_id,
                             find_user, seconds2str, get_role, get_channel)
from datetime import datetime, timedelta
import logging
from bot.globals import Perms
from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger('debug')
manage_roles = discord.Permissions(268435456)
lock_perms = discord.Permissions(268435472)


class Moderator(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.timeouts = self.bot.timeouts
        self.automute_blacklist = {}
        self.automute_whitelist = {}
        self._load_timeouts()
        self._load_automute()

    def _load_automute(self):
        sql = 'SELECT * FROM `automute_blacklist`'
        session = self.bot.get_session
        rows = session.execute(sql)
        for row in rows:
            id_ = str(row['server_id'])
            if id_ not in self.automute_blacklist:
                s = set()
                self.automute_blacklist[id_] = s

            else:
                s = self.automute_blacklist[id_]

            s.add(str(row['channel_id']))

        sql = 'SELECT * FROM `automute_whitelist`'
        rows = session.execute(sql)
        for row in rows:
            id_ = str(row['server'])
            if id_ not in self.automute_whitelist:
                s = set()
                self.automute_whitelist[id_] = s

            else:
                s = self.automute_whitelist[id_]

            s.add(str(row['role']))

    def _load_timeouts(self):
        session = self.bot.get_session
        sql = 'SELECT * FROM `timeouts`'
        rows = session.execute(sql)
        for row in rows:
            try:
                time = row['expires_on'] - datetime.utcnow()
                server = str(row['server'])
                user = str(row['user'])

                task = call_later(self.untimeout, self.bot.loop, time.total_seconds(),
                                  user, server)

                if server not in self.timeouts:
                    server_timeouts = {}
                    self.timeouts[server] = server_timeouts
                else:
                    server_timeouts = self.timeouts.get(server)

                t = server_timeouts.get(user)
                if t:
                    t.cancel()

                server_timeouts[user] = task
                task.add_done_callback(lambda f: server_timeouts.pop(user, None))

            except:
                logger.exception('Could not untimeout %s' % row)

    async def send_to_modlog(self, server, *args, **kwargs):
        if isinstance(server, str):
            server = self.bot.get_server(server)
            if not server:
                return

        channel = self.get_modlog(server)
        if channel is None:
            return

        perms = channel.permissions_for(channel.server.get_member(self.bot.user.id))
        is_embed = 'embed' in kwargs
        if not perms.send_messages:
            return

        if is_embed and not perms.embed_links:
            return

        await self.bot.send_message(channel, *args, **kwargs)

    async def on_message(self, message):
        server = message.server
        if server and self.bot.guild_cache.automute(server.id):
            mute_role = self.bot.guild_cache.mute_role(server.id)
            mute_role = discord.utils.find(lambda r: r.id == mute_role,
                                           message.server.roles)
            limit = self.bot.guild_cache.automute_limit(server.id)
            if mute_role and len(message.mentions) + len(message.role_mentions) > limit:
                blacklist = self.automute_blacklist.get(server.id, ())
                if message.channel.id not in blacklist:
                    whitelist = self.automute_whitelist.get(server.id, ())
                    invulnerable = discord.utils.find(lambda r: r.id in whitelist,
                                                      message.server.roles)
                    user = message.author
                    if (invulnerable is None or invulnerable not in user.roles) and mute_role not in user.roles:
                        await self.bot.add_role(message.author, mute_role)
                        d = 'Automuted user {0} `{0.id}`'.format(message.author)
                        embed = discord.Embed(title='Moderation action [AUTOMUTE]', description=d, timestamp=datetime.utcnow())
                        embed.add_field(name='Reason', value='Too many mentions in a message')
                        embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                        embed.set_footer(text=str(self.bot.user), icon_url=self.bot.user.avatar_url or self.bot.user.default_avatar_url)
                        await self.send_to_modlog(server, embed=embed)
                        return

    @group(pass_context=True, invoke_without_command=True)
    @cooldown(2, 5, BucketType.server)
    async def mute_whitelist(self, ctx):
        """Show roles whitelisted from automutes"""
        server = ctx.message.server
        roles = self.automute_whitelist.get(server.id, ())
        roles = map(lambda r: self.bot.get_role(server, r), roles)
        roles = [r for r in roles if r]
        if not roles:
            return await self.bot.say('No roles whitelisted from automutes')

        msg = 'Roles whitelisted from automutes'
        for r in roles:
            msg += '\n{0.name} `{0.id}`'.format(r)

        await self.bot.say(msg)

    @mute_whitelist.command(pass_context=True, required_perms=Perms.MANAGE_SERVER | Perms.MANAGE_ROLES)
    @cooldown(2, 5, BucketType.server)
    async def add(self, ctx, *, role):
        """Add a role to the automute whitelist"""
        server = ctx.message.server
        roles = self.automute_whitelist.get(server.id)
        if roles is None:
            roles = set()
            self.automute_whitelist[server.id] = roles

        if len(roles) >= 10:
            return await self.bot.say('Maximum of 10 roles can be added to automute whitelist.')

        role_ = get_role(role, server.roles, name_matching=True)
        if not role_:
            return await self.bot.say('Role {} not found'.format(role))

        success = self.bot.dbutils.add_automute_whitelist(server.id, role_.id)
        if not success:
            return await self.bot.say('Failed to add role because of an error')

        roles.add(role_.id)
        await self.bot.say('Added role {0.name} `{0.id}`'.format(role_))

    @mute_whitelist.command(pass_context=True, required_perms=Perms.MANAGE_SERVER | Perms.MANAGE_ROLES, aliases=['del', 'delete'])
    @cooldown(2, 5, BucketType.server)
    async def remove(self, ctx, *, role):
        """Remove a role from the automute whitelist"""
        server = ctx.message.server
        roles = self.automute_whitelist.get(server.id, ())
        role_ = get_role(role, server.roles, name_matching=True)
        if not role_:
            return await self.bot.say('Role {} not found'.format(role))

        if role_.id not in roles:
            return await self.bot.say('Role {0.name} not found in whitelist'.format(role_))

        success = self.bot.dbutils.remove_automute_whitelist(server.id, role.id)
        if not success:
            return await self.bot.say('Failed to remove role because of an error')

        roles.discard(role_.id)
        await self.bot.say('Role {0.name} `{0.id}` removed from automute whitelist'.format(role_))

    @group(pass_context=True, invoke_without_command=True, name='automute_blacklist')
    @cooldown(2, 5, BucketType.server)
    async def automute_blacklist_(self, ctx):
        """Show channels that are blacklisted from automutes.
        That means automutes won't triggered from messages sent in those channels"""
        server = ctx.message.server
        channels = self.automute_blacklist.get(server.id, ())
        channels = map(lambda c: server.get_channel(c), channels)
        channels = [c for c in channels if c]
        if not channels:
            return await self.bot.say('No channels blacklisted from automutes')

        msg = 'Channels blacklisted from automutes'
        for c in channels:
            msg += '\n{0.name} `{0.id}`'.format(c)

        await self.bot.say(msg)

    @automute_blacklist_.command(pass_context=True, required_perms=Perms.MANAGE_SERVER | Perms.MANAGE_ROLES, name='add')
    @cooldown(2, 5, BucketType.server)
    async def add_(self, ctx, *, channel):
        """Add a channel to the automute blacklist"""
        server = ctx.message.server
        channels = self.automute_blacklist.get(server.id)
        if channels is None:
            channels = set()
            self.automute_whitelist[server.id] = channels

        channel_ = get_channel(server.channels, channel, name_matching=True)
        if not channel_:
            return await self.bot.say('Channel {} not found'.format(channel))

        success = self.bot.dbutils.add_automute_blacklist(server.id, channel_.id)
        if not success:
            return await self.bot.say('Failed to add channel because of an error')

        channels.add(channel_.id)
        await self.bot.say('Added channel {0.name} `{0.id}`'.format(channel_))

    @automute_blacklist_.command(pass_context=True, required_perms=Perms.MANAGE_SERVER | Perms.MANAGE_ROLES, name='remove', aliases=['del', 'delete'])
    @cooldown(2, 5, BucketType.server)
    async def remove_(self, ctx, *, channel):
        """Remove a channel from the automute blacklist"""
        server = ctx.message.server
        channels = self.automute_blacklist.get(server.id, ())
        channel_ = get_channel(server.channels, channel, name_matching=True)
        if not channel_:
            return await self.bot.say('Channel {} not found'.format(channel))

        if channel_.id not in channels:
            return await self.bot.say('Channel {0.name} not found in blacklist'.format(channel_))

        success = self.bot.dbutils.remove_automute_blacklist(server.id, channel.id)
        if not success:
            return await self.bot.say('Failed to remove channel because of an error')

        channels.discard(channel.id)
        await self.bot.say('Channel {0.name} `{0.id}` removed from automute blacklist'.format(channel_))

    # Required perms: manage roles
    @command(pass_context=True, required_perms=manage_roles)
    @cooldown(2, 5, BucketType.server)
    async def add_role(self, ctx, name, random_color=True, mentionable=True, hoist=False):
        """Add a role to the server.
        random_color makes the bot choose a random color for the role and
        hoist will make the role show up in the member list"""
        server = ctx.message.server
        if server is None:
            return await self.bot.say('Cannot create roles in DM')

        default_perms = server.default_role.permissions
        color = None
        if random_color:
            color = discord.Color(randint(0, 16777215))
        try:
            r = await self.bot.create_role(server, name=name, permissions=default_perms,
                                           colour=color, mentionable=mentionable, hoist=hoist)
        except discord.HTTPException as e:
            return await self.bot.say('Could not create role because of an error\n```%s```' % e)

        await self.bot.say('Successfully created role %s `%s`' % (name, r.id))

    async def _mute_check(self, ctx, *user):
        server = ctx.message.server
        mute_role = self.bot.guild_cache.mute_role(server.id)
        if mute_role is None:
            await self.bot.say('No mute role set')
            return False

        users = ctx.message.mentions.copy()
        users.extend(get_users_from_ids(server, *user))

        if not users:
            await self.bot.say('No user ids or mentions')
            return False

        mute_role = self.bot.get_role(server, mute_role)
        if mute_role is None:
            await self.bot.say('Could not find the muted role')
            return False

        return users, mute_role

    @command(pass_context=True, required_perms=manage_roles)
    async def mute(self, ctx, user, *reason):
        """Mute a user. Only works if the server has set the mute role"""
        retval = await self._mute_check(ctx, user)
        if isinstance(retval, tuple):
            users, mute_role = retval
        else:
            return

        server = ctx.message.server

        if server.id == '217677285442977792' and user.id == '123050803752730624':
            return await self.bot.say("Not today kiddo. I'm too powerful for you")

        try:
            user = users[0]
            await self.bot.add_role(user, mute_role)
        except:
            await self.bot.say('Could not mute user {}'.format(str(users[0])))

        server_timeouts = self.timeouts.get(server.id, {})
        task = server_timeouts.get(user.id)
        if task:
            task.cancel()
            self.remove_timeout(user.id, server.id)

        try:
            await self.bot.say('Muted user {} `{}`'.format(user.name, user.id))
            chn = self.get_modlog(server)
            if chn:
                author = ctx.message.author
                description = '{} muted {} {}'.format(author.mention, user, user.id)
                embed = discord.Embed(title='🤐 Moderation action [MUTE]',
                                      timestamp=datetime.utcnow(),
                                      description=description)
                reason = ' '.join(reason) if reason else 'No reason <:HYPERKINGCRIMSONANGRY:356798314752245762>'
                embed.add_field(name='Reason', value=reason)
                embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                embed.set_footer(text=str(author), icon_url=author.avatar_url or author.default_avatar_url)
                await self.send_to_modlog(server, embed=embed)
        except:
            pass

    def remove_timeout(self, user_id, server_id):
        session = self.bot.get_session
        try:
            sql = 'DELETE FROM `timeouts` WHERE `server`=:server AND `user`=:user'
            session.execute(sql, params={'server': server_id, 'user': user_id})
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Could not delete untimeout')

    async def untimeout(self, user_id, server_id):
        mute_role = self.bot.guild_cache.mute_role(server_id)
        if mute_role is None:
            return

        server = self.bot.get_server(server_id)
        if server is None:
            self.remove_timeout(user_id, server_id)
            return

        user = server.get_member(user_id)
        if not user:
            self.remove_timeout(user_id, server_id)
            return

        if self.bot.get_role(server, mute_role):
            try:
                await self.bot.remove_role(user, mute_role)
            except:
                logger.exception('Could not autounmute user %s' % user.id)
        self.remove_timeout(user.id, server.id)

    @command(pass_context=True, aliases=['temp_mute'], required_perms=manage_roles)
    async def timeout(self, ctx, user, *, timeout):
        """Mute user for a specified amount of time
         `timeout` is the duration of the mute.
         The format is `n d|days` `n h|hours` `n m|min|minutes` `n s|sec|seconds` `reason`
         where at least one of them must be provided.
         Maximum length for a timeout is 30 days
         e.g. `{prefix}{name} <@!12345678> 10d 10h 10m 10s This is the reason for the timeout`
        """
        retval = await self._mute_check(ctx, user)
        if isinstance(retval, tuple):
            users, mute_role = retval
        else:
            return

        user = users[0]
        time, reason = parse_timeout(timeout)
        server = ctx.message.server
        if not time:
            return await self.bot.say('Invalid time string')

        if user.id == ctx.message.author.id and time.total_seconds() < 21600:
            return await self.bot.say('If you gonna timeout yourself at least make it a longer timeout')

        # Abuse protection for my server
        nigu_nerea = ('287664210152783873', '208185517412581376')
        if user.id in nigu_nerea and ctx.message.author.id in nigu_nerea:
            return await self.bot.say("It's time to stop")

        if server.id == '217677285442977792' and user.id == '123050803752730624':
            return await self.bot.say("Not today kiddo. I'm too powerful for you")

        if time.days > 30:
            return await self.bot.say("Timeout can't be longer than 30 days")
        if server.id == '217677285442977792' and time.total_seconds() < 500:
            return await self.bot.say('This server is retarded so I have to hardcode timeout limits and the given time is too small')
        if time.total_seconds() < 59:
            return await self.bot.say('Minimum timeout is 1 minute')

        now = datetime.utcnow()
        expires_on = datetime2sql(now + time)
        session = self.bot.get_session
        try:
            sql = 'INSERT INTO `timeouts` (`server`, `user`, `expires_on`) VALUES ' \
                  '(:server, :user, :expires_on) ON DUPLICATE KEY UPDATE expires_on=VALUES(expires_on)'

            d = {'server': ctx.message.server.id, 'user': user.id, 'expires_on': expires_on}
            session.execute(sql, params=d)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Could not save timeout')
            return await self.bot.say('Could not save timeout. Canceling action')

        t = self.timeouts.get(server.id, {}).get(user.id)
        if t:
            t.cancel()

        try:
            await self.bot.add_role(user, mute_role)
            await self.bot.say('Muted user {} for {}'.format(str(user), time))
            chn = self.get_modlog(server)
            if chn:
                author = ctx.message.author
                description = '{} muted {} `{}` for {}'.format(author.mention,
                                                               user, user.id, time)

                embed = discord.Embed(title='🕓 Moderation action [TIMEOUT]',
                                      timestamp=datetime.utcnow() + time,
                                      description=description)
                reason = reason if reason else 'No reason <:HYPERKINGCRIMSONANGRY:356798314752245762>'
                embed.add_field(name='Reason', value=reason)
                embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                embed.set_footer(text='Expires at', icon_url=author.avatar_url or author.default_avatar_url)

                await self.send_to_modlog(server, embed=embed)
        except:
            await self.bot.say('Could not mute user {}'.format(str(users[0])))

        task = call_later(self.untimeout, self.bot.loop,
                          time.total_seconds(), user.id, ctx.message.server.id)

        if server not in self.timeouts:
            server_timeouts = {}
            self.timeouts[server] = server_timeouts
        else:
            server_timeouts = self.timeouts.get(server)

        server_timeouts[user.id] = task
        task.add_done_callback(lambda f: server_timeouts.pop(user.id, None))

    @group(pass_context=True, required_perms=manage_roles, invoke_without_command=True, no_pm=True)
    async def unmute(self, ctx, *user):
        """Unmute a user"""
        server = ctx.message.server
        mute_role = self.bot.guild_cache.mute_role(server.id)
        if mute_role is None:
            return await self.bot.say('No mute role set')

        users = ctx.message.mentions.copy()
        users.extend(get_users_from_ids(server, *user))

        if not users:
            return await self.bot.say('No user ids or mentions')

        if server.id == '217677285442977792' and users[0].id == '123050803752730624':
            return await self.bot.say("Not today kiddo. I'm too powerful for you")

        mute_role = self.bot.get_role(server, mute_role)
        if mute_role is None:
            return await self.bot.say('Could not find the muted role')

        try:
            await self.bot.remove_role(users[0], mute_role)
        except:
            await self.bot.say('Could not unmute user {}'.format(users[0]))
        else:
            await self.bot.say('Unmuted user {}'.format(users[0]))
            t = self.timeouts.get(server.id, {}).get(users[0].id)
            if t:
                t.cancel()

    async def _unmute_when(self, ctx, user):
        server = ctx.message.server
        if user:
            member = find_user(' '.join(user), server.members, case_sensitive=True, ctx=ctx)
        else:
            member = ctx.message.author

        if not member:
            return await self.bot.say('User %s not found' % ' '.join(user))
        muted_role = self.bot.guild_cache.mute_role(server.id)
        if not muted_role:
            return await self.bot.say('No mute role set on this server')

        muted_role = int(muted_role)
        if not list(filter(lambda r: int(r.id) == muted_role, member.roles)):
            return await self.bot.say('%s is not muted' % member)

        sql = 'SELECT expires_on FROM `timeouts` WHERE server=%s AND user=%s' % (server.id, member.id)
        session = self.bot.get_session

        row = session.execute(sql).first()
        if not row:
            return await self.bot.say('User %s is permamuted' % str(member))

        delta = row['expires_on'] - datetime.utcnow()
        await self.bot.say('Timeout for %s expires in %s' % (member, seconds2str(delta.total_seconds())))

    @unmute.command(pass_context=True, no_pm=True, required_perms=discord.Permissions(0))
    @cooldown(1, 3, BucketType.user)
    async def when(self, ctx, *user):
        """Shows how long you are still muted for"""
        await self._unmute_when(ctx, user)

    @command(pass_context=True, no_pm=True)
    @cooldown(1, 3, BucketType.user)
    async def unmute_when(self, ctx, *user):
        """Shows how long you are still muted for"""
        await self._unmute_when(ctx, user)

    # Only use this inside commands
    async def _set_channel_lock(self, ctx, locked: bool):
        channel = ctx.message.channel
        everyone = ctx.message.server.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False if locked else None
        try:
            await self.bot.edit_channel_permissions(channel, everyone, overwrite)
        except discord.HTTPException as e:
            return await self.bot.say('Failed to lock channel because of an error: %s. '
                                      'Bot might lack the permissions to do so' % e)

        try:
            if locked:
                await self.bot.say('Locked channel %s' % channel.name)
            else:
                await self.bot.say('Unlocked channel %s' % channel.name)
        except:
            pass

    @staticmethod
    def purge_embed(ctx, messages, users: set=None, multiple_channels=False):
        author = ctx.message.author
        if not multiple_channels:
            d = '%s removed %s messages in %s' % (author.mention, len(messages), ctx.message.channel.mention)
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

    @group(pass_context=True, required_perms=Perms.MANAGE_MESSAGES, invoke_without_command=True, no_pm=True)
    @cooldown(2, 4, BucketType.server)
    async def purge(self, ctx, max_messages: str=10):
        """Purges n amount of messages from a channel.
        maximum value of max_messages is 500 and the default is 10"""
        channel = ctx.message.channel

        try:
            max_messages = int(max_messages)
        except ValueError:
            return await self.bot.say('%s is not a valid integer' % max_messages)

        if max_messages > 1000000:
            return await self.bot.say("Either you tried to delete over 1 million messages or just put it there as an accident. "
                                      "Either way that's way too much for me to handle")

        max_messages = min(500, max_messages)

        messages = await self.bot.purge_from(channel, limit=max_messages)

        modlog = self.get_modlog(channel.server)
        if not modlog:
            return

        embed = self.purge_embed(ctx, messages)
        await self.send_to_modlog(channel.server, embed=embed)

    @purge.command(name='from', pass_context=True, required_perms=Perms.MANAGE_MESSAGES,
                   no_pm=True, ignore_extra=True)
    @cooldown(2, 4, BucketType.server)
    async def from_(self, ctx, mention, max_messages: str=10, channel=None):
        """
        Delete messages from a user
        `mention` The user mention or id of the user we want to purge messages from

        [OPTIONAL]
        `max_messages` Maximum amount of messages that can be deleted. Defaults to 10 and max value is 300.
        `channel` Channel if or mention where you want the messages to be purged from. If not set will delete messages from any channel the bot has access to.
        """
        user = get_user_id(mention)
        server = ctx.message.server
        # We have checked the members channel perms but we need to be sure the
        # perms are global when no channel is specified
        if channel is None and not ctx.message.author.server_permissions.manage_messages and not ctx.override_perms:
            return await self.bot.say("You don't have the permission to purge from all channels")

        try:
            max_messages = int(max_messages)
        except ValueError:
            return await self.bot.say('%s is not a valid integer' % max_messages)

        max_messages = min(300, max_messages)

        if channel is not None:
            channel = get_channel_id(channel)
            channel = server.get_channel(channel)

        t = datetime.utcnow() - timedelta(days=14)
        t = datetime2sql(t)
        sql = 'SELECT `message_id`, `channel` FROM `messages` WHERE server=%s AND user_id=%s AND DATE(`time`) > "%s" ' % (server.id, user, t)

        if channel is not None:
            sql += 'AND channel=%s ' % channel.id

        sql += 'ORDER BY `message_id` DESC LIMIT %s' % max_messages
        session = self.bot.get_session

        modlog = self.get_modlog(server)
        rows = session.execute(sql).fetchall()
        if not rows:
            if channel is None:
                return await self.bot.say("Could not find any messages by `%s`. Alternative method will only delete messages from a channel which wasn't specified" % mention)

            messages = await self.bot.purge_from(channel, limit=min(max_messages, 100),
                                                 check=lambda m: m.author.id == user)

            if modlog and messages:
                embed = self.purge_embed(ctx, messages, users={'<@!%s>' % user})
                await self.send_to_modlog(server, embed=embed)

            return

        channel_messages = {}
        for r in rows:
            if r['channel'] not in channel_messages:
                message_ids = []
                channel_messages[r['channel']] = message_ids
            else:
                message_ids = channel_messages[r['channel']]

            message_ids.append(str(r['message_id']))

        ids = []
        for k in channel_messages:
            try:
                if len(channel_messages[k]) == 1:
                    await self.bot.delete_message(channel_messages[k][0], str(k))
                else:
                    await self.delete_messages(k, channel_messages[k])
            except:
                logger.exception('Could not delete messages')
            else:
                ids.extend(channel_messages[k])

        if ids:
            sql = 'DELETE FROM `messages` WHERE `message_id` IN (%s)' % ', '.join(ids)
            try:
                session.execute(sql)
                session.commit()
            except SQLAlchemyError:
                session.rollback()
                logger.exception('Could not delete messages from database')

            if modlog:
                embed = self.purge_embed(ctx, ids, users={'<@!%s>' % user}, multiple_channels=len(channel_messages.keys()) > 1)
                await self.send_to_modlog(server, embed=embed)

    @command(pass_context=True, no_pm=True, ignore_extra=True, required_perms=discord.Permissions(4), aliases=['softbab'])
    async def softban(self, ctx, user, message_days=1):
        """Ban and unban a user from the server deleting that users messages from
        n amount of days in the process"""
        user_ = get_user_id(user)
        server = ctx.message.server
        if user_ is None:
            return await self.bot.say('User %s could not be found' % user)

        if not (1 <= message_days <= 7):
            return await self.bot.say('Message days must be between 1 and 7')

        try:
            await self.bot.http.ban(user_, server.id, message_days)
        except discord.Forbidden:
            return await self.bot.say("The bot doesn't have ban perms")
        except:
            return await self.bot.say('Something went wrong while trying to ban. Try again')

        try:
            await self.bot.http.unban(user_, server.id)
        except:
            return await self.bot.say('Failed to unban after ban')

        member = server.get_member(user_)
        s = 'Softbanned user '
        if not member:
            s += '<@!{0}> `{0}`'.format(user_)
        else:
            s += '{} `{}`'.format(str(member), member.id)

        await self.bot.say(s)

    @command(pass_context=True, ignore_extra=True, required_perms=lock_perms)
    @cooldown(2, 5, BucketType.server)
    async def lock(self, ctx):
        """Set send_messages permission override of everyone to false on current channel"""
        await self._set_channel_lock(ctx, True)

    @command(pass_context=True, ignore_extra=True, required_perms=lock_perms)
    @cooldown(2, 5, BucketType.server)
    async def unlock(self, ctx):
        """Set send_messages permission override on current channel to default position"""
        await self._set_channel_lock(ctx, False)

    async def delete_messages(self, channel_id, message_ids):
        """Delete messages in bulk and take the message limit into account"""
        step = 100
        for idx in range(0, len(message_ids), step):
            await self.bot.bulk_delete(channel_id, message_ids[idx:idx+step])

    def get_modlog(self, server):
        return server.get_channel(self.bot.guild_cache.modlog(server.id))


def setup(bot):
    bot.add_cog(Moderator(bot))

