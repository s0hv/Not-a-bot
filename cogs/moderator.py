from cogs.cog import Cog
from bot.bot import command
from random import randint
import discord
from utils.utilities import get_users_from_ids, call_later, parse_timeout, datetime2sql
from datetime import datetime
import logging

logger = logging.getLevelName('debug')
manage_roles = discord.Permissions(268435456)
lock_perms = discord.Permissions(268435472 )


class Moderator(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._load_timeouts()

    def _load_timeouts(self):
        session = self.bot.get_session
        sql = 'SELECT * FROM `timeouts`'
        rows = session.execute(sql)
        for row in rows:
            try:
                print(datetime.utcnow(), row['expires_on'])
                time = row['expires_on'] - datetime.utcnow()
                call_later(self.untimeout, self.bot.loop, time.total_seconds(),
                           str(row['user']), str(row['server']))

            except:
                logger.exception('Could not untimeout %s' % row)

    # Required perms: manage roles
    @command(pass_context=True, required_perms=manage_roles)
    async def add_role(self, ctx, name, random_color=True, mentionable=True):
        if ctx.message.server is None:
            return await self.bot.say('Cannot create roles in DM')

        default_perms = ctx.message.server.default_role.permissions
        color = None
        if random_color:
            color = discord.Color(randint(0, 16777215))
        try:
            await self.bot.create_role(ctx.message.server, name=name, permissions=default_perms,
                                       colour=color, mentionable=mentionable)
        except Exception as e:
            return await self.bot.say('Could not create role because of an error\n```%s```' % e)

        await self.bot.say('Successfully created role %s' % name)

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

        try:
            server = ctx.message.server
            user = users[0]
            await self.bot.add_roles(user, mute_role)
        except:
            await self.bot.say('Could not mute user {}'.format(str(users[0])))

        try:
            await self.bot.say('Muted user {} `{}`'.format(user.name, user.id))
            chn = server.get_channel(self.bot.server_cache.get_modlog(server.id))
            if chn:
                author = ctx.message.author
                description = '{} muted {} {}'.format(author.mention, user, user.id)
                embed = discord.Embed(title='🤐 Moderation action [MUTE]',
                                      timestamp=datetime.utcnow(),
                                      description=description)
                reason = ' '.join(reason) if reason else 'No reason <:HYPERKINGCRIMSONANGRY:334717902962032640>'
                embed.add_field(name='Reason', value=reason)
                embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                embed.set_footer(text=str(author), icon_url=author.avatar_url or author.default_avatar_url)
                await self.bot.send_message(chn, embed=embed)
        except:
            pass

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
                await self.bot.remove_roles(user, mute_role)
            except:
                logger.exception('Could not autounmute user %s' % user.id)

        try:
            session = self.bot.get_session
            sql = 'DELETE FROM `timeouts` WHERE `server` = %s AND `user` = %s' % (server.id, user.id)
            session.execute(sql)
            session.commit()
        except:
            logger.exception('Could not delete untimeout')

    @command(pass_context=True, aliases=['temp_mute'], required_perms=manage_roles)
    async def timeout(self, ctx, user, *, timeout):
        """Mute user for a specified amount of time
         `timeout` is the duration of the mute.
         The format is `n d|days` `n h|hours` `n m|minutes` `n s|seconds`
         where at least one of them must be provided.
         Maximum length for a timeout is 30 days
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
                  '(:server, :user, :expires_on) ON DUPLICATE KEY UPDATE expires_on=expires_on'

            d = {'server': ctx.message.server.id, 'user': user.id, 'expires_on': expires_on}
            session.execute(sql, params=d)
            session.commit()
        except:
            logger.exception('Could not save timeout')
            return await self.bot.say('Could not save timeout. Canceling action')

        server = ctx.message.server
        try:
            await self.bot.add_roles(user, mute_role)
            await self.bot.say('Muted user {} for {}'.format(str(user), time))
            chn = server.get_channel(self.bot.server_cache.get_modlog(server.id))
            if chn:
                author = ctx.message.author
                description = '{} muted {} `{}` for {}'.format(author.mention,
                                                               user, user.id, time)

                embed = discord.Embed(title='🕓 Moderation action [TIMEOUT]',
                                      timestamp=datetime.utcnow(),
                                      description=description)
                reason = reason if reason else 'No reason <:HYPERKINGCRIMSONANGRY:334717902962032640>'
                embed.add_field(name='Reason', value=reason)
                embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                embed.set_footer(text=str(author), icon_url=author.avatar_url or author.default_avatar_url)

                await self.bot.send_message(chn, embed=embed)
        except:
            await self.bot.say('Could not mute user {}'.format(str(users[0])))

        call_later(self.untimeout, self.bot.loop,
                   time.total_seconds(), user.id, ctx.message.server.id)

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
            await self.bot.remove_roles(users[0], mute_role)
        except:
            await self.bot.say('Could not unmute user {}'.format(users[0]))
        else:
            await self.bot.say('Unmuted user {}'.format(users[0]))

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

    @command(pass_context=True, ignore_extra=True, required_perms=lock_perms)
    async def lock(self, ctx):
        await self._set_channel_lock(ctx, True)

    @command(pass_context=True, ignore_extra=True, required_perms=lock_perms)
    async def unlock(self, ctx):
        await self._set_channel_lock(ctx, False)


def setup(bot):
    bot.add_cog(Moderator(bot))
