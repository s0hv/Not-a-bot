import logging

from discord.ext.commands import cooldown, BucketType, check

from bot.bot import command
from bot.globals import Perms
from cogs.cog import Cog
from utils.utilities import (get_role, get_user_id, split_string, find_user,
                             parse_time, datetime2sql, call_later, get_avatar,
                             retry)
import subprocess
import shlex
import asyncio
from datetime import datetime
from random import randint, random
from sqlalchemy.exc import SQLAlchemyError
from discord.errors import HTTPException
import discord
from numpy.random import choice


logger = logging.getLogger('debug')


def create_check(server_ids):
    def server_check(ctx, command_):
        return ctx.message.server.id in server_ids

    return server_check


whitelist = ('217677285442977792', '353927534439825429')
main_check = create_check(whitelist)


class ServerSpecific(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.load_giveaways()

    def load_giveaways(self):
        sql = 'SELECT * FROM `giveaways`'
        session = self.bot.get_session
        try:
            rows = session.execute(sql).fetchall()
        except SQLAlchemyError:
            logger.exception('Failed to load giveaways')
            return

        for row in rows:
            server = str(row['server'])
            channel = str(row['channel'])
            message = str(row['message'])
            title = row['title']
            winners = row['winners']
            timeout = max((row['expires_in'] - datetime.utcnow()).total_seconds(), 0)
            call_later(self.remove_every, self.bot.loop, timeout, server, channel, message, title, winners)

    @property
    def dbutil(self):
        return self.bot.dbutil

    async def _check_role_grant(self, user, role_id, server_id):
        length = len(user.roles)
        if length == 1:
            user_role = 'user_role=%s' % role_id
        else:
            user_role = 'user_role IN (%s)' % ', '.join([r.id for r in user.roles])

        sql = 'SELECT `role_id` FROM `role_granting` WHERE server_id=%s AND role_id=%s AND %s LIMIT 1' % (server_id, role_id, user_role)
        session = self.bot.get_session
        try:
            row = session.execute(sql).first()
            if not row:
                return False
        except SQLAlchemyError:
            await self.bot.say('Something went wrong. Try again in a bit')
            return None

        return True

    @command(pass_context=True, no_pm=True)
    @cooldown(1, 4, type=BucketType.user)
    @check(main_check)
    async def grant(self, ctx, user, *, role):
        """Give a role to the specified user if you have the perms to do it"""
        server = ctx.message.server
        author = ctx.message.author
        length = len(author.roles)
        if length == 0:
            return

        target_user = get_user_id(user)
        if not target_user:
            return await self.bot.say("User %s wasn't found" % user, delete_after=30)

        role_ = get_role(role, server.roles, True)
        if not role_:
            return await self.bot.say('Role %s not found' % role)

        role_id = role_.id

        can_grant = await self._check_role_grant(author, role_id, server.id)
        if can_grant is None:
            return
        elif can_grant is False:
            return await self.bot.say("You don't have the permission to grant this role", delete_after=30)

        try:
            await self.bot.add_role(target_user, role_id, server)
        except HTTPException as e:
            return await self.bot.say('Failed to add role\n%s' % e)

        await self.bot.say('👌')

    @command(pass_context=True, no_pm=True)
    @cooldown(2, 4, type=BucketType.user)
    @check(main_check)
    async def ungrant(self, ctx, user, *, role):
        """Remove a role from a user if you have the perms"""
        server = ctx.message.server
        author = ctx.message.author
        length = len(author.roles)
        if length == 0:
            return

        target_user = get_user_id(user)
        if not target_user:
            return await self.bot.say("User %s wasn't found" % user, delete_after=30)

        role_ = get_role(role, server.roles, True)
        if not role_:
            return await self.bot.say('Role %s not found' % role)

        role_id = role_.id

        can_grant = await self._check_role_grant(author, role_id, server.id)
        if can_grant is None:
            return
        elif can_grant is False:
            return await self.bot.say("You don't have the permission to remove this role", delete_after=30)

        try:
            await self.bot.remove_role(target_user, role_id, server)
        except HTTPException as e:
            return await self.bot.say('Failed to remove role\n%s' % e)

        await self.bot.say('👌')

    @command(pass_context=True, required_perms=Perms.ADMIN, no_pm=True, ignore_extra=True)
    @cooldown(2, 4, type=BucketType.server)
    @check(main_check)
    async def add_grant(self, ctx, role, target_role):
        """Make the given role able to grant the target role"""
        server = ctx.message.server
        role_ = get_role(role, server.roles)
        if not role_:
            return await self.bot.say('Could not find role %s' % role, delete_after=30)

        target_role_ = get_role(target_role, server.roles)
        if not target_role_:
            return await self.bot.say('Could not find role %s' % target_role, delete_after=30)

        if not self.dbutil.add_roles(server.id, target_role_.id, role_.id):
            return await self.bot.say('Could not add roles to database')

        sql = 'INSERT IGNORE INTO `role_granting` (`user_role`, `role_id`, `server_id`) VALUES ' \
              '(%s, %s, %s)' % (role_.id, target_role_.id, server.id)
        session = self.bot.get_session
        try:
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to add grant role')
            return await self.bot.say('Failed to add perms. Exception logged')

        await self.bot.say('👌')

    @command(pass_context=True, required_perms=Perms.ADMIN, no_pm=True, ignore_extra=True)
    @cooldown(1, 4, type=BucketType.user)
    @check(main_check)
    async def remove_grant(self, ctx, role, target_role):
        """Remove a grantable role from the target role"""
        server = ctx.message.server
        role_ = get_role(role, server.roles)
        if not role_:
            return await self.bot.say('Could not find role %s' % role, delete_after=30)

        target_role_ = get_role(target_role, server.roles)
        if not target_role_:
            return await self.bot.say('Could not find role %s' % target_role, delete_after=30)

        sql = 'DELETE FROM `role_granting` WHERE user_role=%s AND role_id=%s AND server_id=%s' % (role_.id, target_role_.id, server.id)
        session = self.bot.get_session
        try:
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to remove grant role')
            return await self.bot.say('Failed to remove perms. Exception logged')

        await self.bot.say('👌')

    @command(pass_context=True, no_pm=True, aliases=['get_grants', 'grants'])
    @cooldown(1, 4)
    @check(main_check)
    async def show_grants(self, ctx, *user):
        """Shows the roles you or the specified user can grant"""
        server = ctx.message.server
        if user:
            user = ' '.join(user)
            user_ = find_user(user, server.members, case_sensitive=True, ctx=ctx)
            if not user_:
                return await self.bot.say("Couldn't find a user with %s" % user)
            author = user_
        else:
            author = ctx.message.author
        session = self.bot.get_session
        sql = 'SELECT `role_id` FROM `role_granting` WHERE server_id=%s AND user_role IN (%s)' % (server.id, ', '.join([r.id for r in author.roles]))
        try:
            rows = session.execute(sql).fetchall()
        except SQLAlchemyError:
            logger.exception('Failed to get role grants')
            return await self.bot.say('Failed execute sql')

        if not rows:
            return await self.bot.say("{} can't grant any roles".format(author))

        msg = 'Roles {} can grant:\n'.format(author)
        found = False
        for row in rows:
            role = self.bot.get_role(server, row['role_id'])
            if not role:
                continue

            if not found:
                found = True
            msg += '{0.name} `{0.id}`\n'.format(role)

        if not found:
            return await self.bot.say("{} can't grant any roles".format(author))

        for s in split_string(msg, maxlen=2000, splitter='\n'):
            await self.bot.say(s)

    @command(pass_context=True)
    @cooldown(1, 3, type=BucketType.server)
    @check(main_check)
    async def text(self, ctx):
        """Generate text"""
        if self.bot.test_mode:
            return

        p = '/home/pi/neural_networks/torch-rnn/cv/checkpoint_pi.t7'
        script = '/home/pi/neural_networks/torch-rnn/sample.lua'
        cmd = '/home/pi/torch/install/bin/th %s -checkpoint %s -length 200 -gpu -1' % (script, p)
        p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd='/home/pi/neural_networks/torch-rnn/')
        await self.bot.send_typing(ctx.message.channel)
        while p.poll() is None:
            await asyncio.sleep(0.2)

        out, err = p.communicate()
        await self.bot.say(out.decode('utf-8'))

    @command(pass_context=True, no_pm=True)
    @cooldown(1, 3, type=BucketType.user)
    @check(create_check(('217677285442977792', )))
    async def default_role(self, ctx):
        """Temporary fix to easily get default role"""
        if self.bot.test_mode:
            return

        server = ctx.message.server
        role = self.bot.get_role(server, '352099343953559563')
        if not role:
            return await self.bot.say('Default role not found')

        member = ctx.message.author
        if role in member.roles:
            return await self.bot.say('You already have the default role')

        try:
            await self.bot.add_role(member, role)
        except HTTPException as e:
            return await self.bot.say('Failed to add default role because of an error.\n{}'.format(e))

        await self.bot.say('You now have the default role')

    @command(pass_context=True, required_perms=Perms.MANAGE_ROLES | Perms.MANAGE_SERVER)
    @cooldown(1, 3, type=BucketType.server)
    @check(main_check)
    async def toggle_every(self, ctx, winners: int, *, expires_in):
        """Host a giveaway to toggle the every role"""
        expires_in = parse_time(expires_in)
        if not expires_in:
            return await self.bot.say('Invalid time string')

        if expires_in.days > 29:
            return await self.bot.say('Maximum time is 29 days 23 hours 59 minutes and 59 seconds')

        if expires_in.total_seconds() < 300:
            return await self.bot.say('Minimum time is 5 minutes')

        if winners < 1:
            return await self.bot.say('There must be more than 1 winner')

        if winners > 30:
            return await self.bot.say('Maximum amount of winners is 30')

        channel = ctx.message.channel
        server = ctx.message.server
        perms = channel.permissions_for(server.get_member(self.bot.user.id))
        if not perms.manage_roles and not perms.administrator:
            return await self.bot.say('Invalid server perms')

        role = self.bot.get_role(server, '323098643030736919')
        if role is None:
            return await self.bot.say('Every role not found')

        sql = 'INSERT INTO `giveaways` (`server`, `title`, `message`, `channel`, `winners`, `expires_in`) VALUES (:server, :title, :message, :channel, :winners, :expires_in)'

        now = datetime.utcnow()
        expired_date = now + expires_in
        sql_date = datetime2sql(expired_date)

        title = 'Toggle the every role on the winner.'
        embed = discord.Embed(title='Giveaway: {}'.format(title),
                              description='React with <:GWjojoGachiGASM:363025405562585088> to enter',
                              timestamp=expired_date)
        text = 'Expires at'
        if winners > 1:
            text = '{} winners | '.format(winners) + text
        embed.set_footer(text=text, icon_url=get_avatar(self.bot.user))

        message = await self.bot.send_message(channel, embed=embed)
        await self.bot.add_reaction(message, 'GWjojoGachiGASM:363025405562585088')
        session = self.bot.get_session
        try:
            session.execute(sql, params={'server': int(server.id), 'title': 'Toggle every',
                                         'message': int(message.id),
                                         'channel': int(channel.id),
                                         'winners': winners,
                                         'expires_in': sql_date})
            session.commit()
        except SQLAlchemyError:
            logger.exception('Failed to create every toggle')
            return await self.bot.say('SQL error')

        call_later(self.remove_every, self.bot.loop, expires_in.total_seconds(), server.id, channel.id, message.id, title, winners)

    def delete_giveaway_from_db(self, message_id):
        sql = 'DELETE FROM `giveaways` WHERE message=:message'
        session = self.bot.get_session
        try:
            session.execute(sql, {'message': int(message_id)})
            session.commit()
        except SQLAlchemyError:
            logger.exception('Failed to delete giveaway {}'.format(message_id))

    async def remove_every(self, server, channel, message, title, winners):
        server = self.bot.get_server(server)
        if not server:
            self.delete_giveaway_from_db(message)
            return

        role = self.bot.get_role(server, '323098643030736919')
        if role is None:
            self.delete_giveaway_from_db(message)
            return

        channel = self.bot.get_channel(channel)
        if not channel:
            self.delete_giveaway_from_db(message)
            return

        try:
            message = await self.bot.get_message(channel, message)
        except discord.NotFound:
            self.delete_giveaway_from_db(message)
            return

        react = None
        for reaction in message.reactions:
            emoji = reaction.emoji
            if isinstance(emoji, str):
                continue
            if emoji.id == '363025405562585088' and emoji.name == 'GWjojoGachiGASM':
                react = reaction
                break

        if react is None:
            logger.debug('react not found')
            return

        title = 'Giveaway: {}'.format(title)
        description = 'No winners'

        users = await self.bot.get_all_reaction_users(react, limit=react.count)
        candidates = [server.get_member(user.id) for user in users if user.id != self.bot.user.id and server.get_member(user.id)]
        winners = choice(candidates, min(winners, len(candidates)), replace=False)
        if len(winners) > 0:
            winners = sorted(winners, key=lambda u: u.name)
            description = 'Winners: {}'.format('\n'.join([user.mention for user in winners]))

        added = 0
        removed = 0
        for winner in winners:
            winner = server.get_member(winner.id)
            if not winner:
                continue
            if role in winner.roles:
                retval = await retry(self.bot.remove_role, winner, role)
                removed += 1

            else:
                retval = await retry(self.bot.add_role, winner, role)
                added += 1

            if isinstance(retval, Exception):
                logger.debug('Failed to toggle every role on {0} {0.id}\n{1}'.format(winner, retval))

        embed = discord.Embed(title=title, description=description, timestamp=datetime.utcnow())
        embed.set_footer(text='Expired at', icon_url=get_avatar(self.bot.user))
        await self.bot.edit_message(message, embed=embed)
        description += '\nAdded every to {} user(s) and removed it from {} user(s)'.format(added, removed)
        await self.bot.send_message(message.channel, description)
        self.delete_giveaway_from_db(message.id)

    async def on_member_join(self, member):
        if self.bot.test_mode:
            return

        server = member.server
        if server.id != '366940074635558912':
            return

        if random() < 0.09:
            name = str(member.discriminator)
        else:
            name = str(randint(1000, 9999))
        await self.bot.change_nickname(member, name)


def setup(bot):
    bot.add_cog(ServerSpecific(bot))
