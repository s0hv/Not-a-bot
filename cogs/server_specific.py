import logging

from discord.ext.commands import cooldown, BucketType

from bot.bot import command
from bot.globals import Perms
from cogs.cog import Cog
from utils.utilities import get_role, get_user_id, split_string, find_user
import subprocess
import shlex
import asyncio
from random import randint, random

logger = logging.getLogger('debug')


class ServerSpecific(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.whitelist = ['217677285442977792', '353927534439825429']

    @property
    def dbutil(self):
        return self.bot.dbutil

    async def _check_role_grant(self, user, role_id, server_id):
        l = len(user.roles)
        if l == 1:
            user_role = 'user_role=%s' % role_id
        else:
            user_role = 'user_role IN (%s)' % ', '.join([r.id for r in user.roles])

        sql = 'SELECT `role_id` FROM `role_granting` WHERE server_id=%s AND role_id=%s AND %s LIMIT 1' % (server_id, role_id, user_role)
        session = self.bot.get_session
        try:
            row = session.execute(sql).first()
            if not row:
                return False
        except:
            await self.bot.say('Something went wrong. Try again in a bit')
            return None

        return True

    @command(pass_context=True, no_pm=True)
    @cooldown(1, 4, type=BucketType.user)
    async def grant(self, ctx, user, *, role):
        """"""
        server = ctx.message.server
        if server.id not in self.whitelist:
            return

        author = ctx.message.author
        l = len(author.roles)
        if l == 0:
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
        except Exception as e:
            return await self.bot.say('Failed to add role\n%s' % e)

        await self.bot.say('👌')

    @command(pass_context=True, no_pm=True)
    @cooldown(2, 4, type=BucketType.user)
    async def ungrant(self, ctx, user, *, role):
        """"""
        server = ctx.message.server
        if server.id not in self.whitelist:
            return

        author = ctx.message.author
        l = len(author.roles)
        if l == 0:
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
        except Exception as e:
            return await self.bot.say('Failed to remove role\n%s' % e)

        await self.bot.say('👌')

    @command(pass_context=True, required_perms=Perms.ADMIN, no_pm=True, ignore_extra=True)
    @cooldown(2, 4, type=BucketType.server)
    async def add_grant(self, ctx, role, target_role):
        server = ctx.message.server
        if server.id not in self.whitelist:
            return

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
        except:
            session.rollback()
            logger.exception('Failed to add grant role')
            return await self.bot.say('Failed to add perms. Exception logged')

        await self.bot.say('👌')

    @command(pass_context=True, required_perms=Perms.ADMIN, no_pm=True, ignore_extra=True)
    @cooldown(1, 4, type=BucketType.user)
    async def remove_grant(self, ctx, role, target_role):
        server = ctx.message.server
        if server.id not in self.whitelist:
            return
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
        except:
            session.rollback()
            logger.exception('Failed to remove grant role')
            return await self.bot.say('Failed to remove perms. Exception logged')

        await self.bot.say('👌')

    @command(pass_context=True, no_pm=True, aliases=['get_grants', 'grants'])
    @cooldown(1, 4)
    async def show_grants(self, ctx, *user):
        server = ctx.message.server
        if server.id not in self.whitelist:
            return

        if user:
            user = ' '.join(user)
            user_ = find_user(user, server.members, case_sensitive=True, ctx=ctx)
            if not user_:
                return await self.bot.say("Couldn't find a user with %s" %  user)
            author = user_
        else:
            author = ctx.message.author
        session = self.bot.get_session
        sql = 'SELECT `role_id` FROM `role_granting` WHERE server_id=%s AND user_role IN (%s)' % (server.id, ', '.join([r.id for r in author.roles]))
        try:
            rows = session.execute(sql).fetchall()
        except:
            logger.exception('Failed to get role grants')
            return await self.bot.say('Failed execute sql')

        if not rows:
            return await self.bot.say("You can't grant any roles")

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
    async def text(self, ctx):
        server = ctx.message.server
        if server.id not in self.whitelist:
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
    async def default_role(self, ctx):
        """Temporary fix to easily get default role"""
        server = ctx.message.server
        if server.id not in self.whitelist:
            return

        role = self.bot.get_role(server, '352099343953559563')
        if not role:
            return await self.bot.say('Default role not found')

        member = ctx.message.author
        if role in member.roles:
            return await self.bot.say('You already have the default role')

        try:
            await self.bot.add_role(member, role)
        except:
            return await self.bot.say('Failed to add default role. Try again in a bit')

        await self.bot.say('You now have the default role')

    async def on_member_join(self, member):
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
