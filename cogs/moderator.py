from cogs.cog import Cog
from bot.bot import command, group
from random import randint
import discord
from utils.utilities import (get_users_from_ids, call_later, parse_timeout,
                             datetime2sql, get_avatar, get_user_id, get_channel_id,
                             find_user, seconds2str)
from datetime import datetime, timedelta
import logging
from bot.globals import Perms


logger = logging.getLogger('debug')
manage_roles = discord.Permissions(268435456)
lock_perms = discord.Permissions(268435472)


class Moderator(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.timeouts = self.bot.timeouts
        self._load_timeouts()

    def _load_timeouts(self):
        session = self.bot.get_session
        sql = 'SELECT * FROM `timeouts`'
        rows = session.execute(sql)
        for row in rows:
            try:
                print(datetime.utcnow(), row['expires_on'])
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

    # Required perms: manage roles
    @command(pass_context=True, required_perms=manage_roles)
    async def add_role(self, ctx, name, random_color=True, mentionable=True, hoist=False):
        if ctx.message.server is None:
            return await self.bot.say('Cannot create roles in DM')

        default_perms = ctx.message.server.default_role.permissions
        color = None
        if random_color:
            color = discord.Color(randint(0, 16777215))
        try:
            r = await self.bot.create_role(ctx.message.server, name=name, permissions=default_perms,
                                       colour=color, mentionable=mentionable, hoist=hoist)
        except Exception as e:
            return await self.bot.say('Could not create role because of an error\n```%s```' % e)

        await self.bot.say('Successfully created role %s `%s`' % (name, r.id))

    async def _mute_check(self, ctx, *user):
        server = ctx.message.server
        mute_role = self.bot.server_cache.get_mute_role(server.id)
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
        retval = await self._mute_check(ctx, user)
        if isinstance(retval, tuple):
            users, mute_role = retval
        else:
            return

        server = ctx.message.server
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
            chn = server.get_channel(self.bot.server_cache.get_modlog(server.id))
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
                await self.bot.send_message(chn, embed=embed)
        except:
            pass

    def remove_timeout(self, user_id, server_id):
        session = self.bot.get_session
        try:
            sql = 'DELETE FROM `timeouts` WHERE `server` = %s AND `user` = %s' % (server_id, user_id)
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Could not delete untimeout')

    async def untimeout(self, user, server_id):
        mute_role = self.bot.server_cache.get_mute_role(server_id)
        if mute_role is None:
            return

        server = self.bot.get_server(server_id)
        user = server.get_member(user)
        if not user:
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
         The format is `n d|days` `n h|hours` `n m|minutes` `n s|seconds` `reason`
         where at least one of them must be provided.
         Maximum length for a timeout is 30 days
         e.g. `!timeout <@!12345678> 10d 10h 10m 10s This is the reason for the timeout`
        """
        retval = await self._mute_check(ctx, user)
        if isinstance(retval, tuple):
            users, mute_role = retval
        else:
            return

        time, reason = parse_timeout(timeout)
        if not time:
            return await self.bot.say('Invalid time string')

        if time.days > 30:
            return await self.bot.say("Timeout can't be longer than 30 days")

        now = datetime.utcnow()
        expires_on = datetime2sql(now + time)
        user = users[0]
        session = self.bot.get_session
        try:
            sql = 'INSERT INTO `timeouts` (`server`, `user`, `expires_on`) VALUES ' \
                  '(:server, :user, :expires_on) ON DUPLICATE KEY UPDATE expires_on=VALUES(expires_on)'

            d = {'server': ctx.message.server.id, 'user': user.id, 'expires_on': expires_on}
            session.execute(sql, params=d)
            session.commit()
        except:
            session.rollback()
            logger.exception('Could not save timeout')
            return await self.bot.say('Could not save timeout. Canceling action')

        server = ctx.message.server
        t = self.timeouts.get(server.id, {}).get(user.id)
        if t:
            t.cancel()

        try:
            await self.bot.add_role(user, mute_role)
            await self.bot.say('Muted user {} for {}'.format(str(user), time))
            chn = server.get_channel(self.bot.server_cache.get_modlog(server.id))
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

                await self.bot.send_message(chn, embed=embed)
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

    @command(pass_context=True, required_perms=manage_roles)
    async def unmute(self, ctx, *user):
        server = ctx.message.server
        mute_role = self.bot.server_cache.get_mute_role(server.id)
        if mute_role is None:
            return await self.bot.say('No mute role set')

        users = ctx.message.mentions.copy()
        users.extend(get_users_from_ids(server, *user))

        if not users:
            return await self.bot.say('No user ids or mentions')

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

    @command(pass_context=True, no_pm=True)
    async def unmute_when(self, ctx, *user):
        server = ctx.message.server
        if user:
            member = find_user(' '.join(user), server.members, case_sensitive=True, ctx=ctx)
        else:
            member = ctx.message.author

        if not member:
            return await self.bot.say('User %s not found' % ' '.join(user))
        muted_role = self.bot.server_cache.get_mute_role(server.id)
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

    # Only use this inside commands
    async def _set_channel_lock(self, ctx, locked: bool):
        channel = ctx.message.channel
        everyone = ctx.message.server.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False if locked else None
        try:
            await self.bot.edit_channel_permissions(channel, everyone, overwrite)
        except Exception as e:
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

        modlog = self.bot.get_channel(self.bot.server_cache.get_modlog(ctx.message.server.id))
        if not modlog:
            return

        embed = self.purge_embed(ctx, messages)
        await self.bot.send_message(modlog, embed=embed)

    @purge.command(name='from', pass_context=True, required_perms=Perms.MANAGE_MESSAGES,
                   no_pm=True, ignore_extra=True)
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
                await self.bot.send_message(modlog, embed=embed)

            return

        channel_messages = {}
        for r in rows:
            if r['channel'] not in channel_messages:
                l = []
                channel_messages[r['channel']] = l
            else:
                l = channel_messages[r['channel']]

            l.append(str(r['message_id']))

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
            except:
                session.rollback()
                logger.exception('Could not delete messages from database')

            if modlog:
                embed = self.purge_embed(ctx, ids, users={'<@!%s>' % user}, multiple_channels=len(channel_messages.keys()) > 1)
                await self.bot.send_message(modlog, embed=embed)

    @command(pass_context=True, no_pm=True, ignore_extra=True, required_perms=discord.Permissions(4), aliases=['softbab'])
    async def softban(self, ctx, user, message_days=1):
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
    async def lock(self, ctx):
        """Set send_messages permission override of everyone to false on current channel"""
        await self._set_channel_lock(ctx, True)

    @command(pass_context=True, ignore_extra=True, required_perms=lock_perms)
    async def unlock(self, ctx):
        """Set send_messages permission override on current channel to default position"""
        await self._set_channel_lock(ctx, False)

    async def delete_messages(self, channel_id, message_ids):
        """Delete messages in bulk and take the message limit into account"""
        step = 100
        for idx in range(0, len(message_ids), step):
            await self.bot.bulk_delete(channel_id, message_ids[idx:idx+step])

    def get_modlog(self, server):
        return server.get_channel(self.bot.server_cache.get_modlog(server.id))


def setup(bot):
    bot.add_cog(Moderator(bot))

