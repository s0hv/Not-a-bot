import logging

from discord.ext.commands import cooldown

from bot.bot import command
from bot.globals import Perms
from cogs.cog import Cog
from utils.utilities import get_role, get_user_id
import subprocess
import shlex
import asyncio

logger = logging.getLogger('debug')


class ServerSpecific(Cog):
    def __init__(self, bot):
        super().__init__(bot)

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
    @cooldown(2, 4)
    async def grant(self, ctx, user, *, role):
        """"""
        server = ctx.message.server
        if server.id not in ('217677285442977792', '353927534439825429'):
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
    @cooldown(2, 4)
    async def ungrant(self, ctx, user, *, role):
        """"""
        server = ctx.message.server
        if server.id not in ('217677285442977792', '353927534439825429'):
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
    @cooldown(2, 4)
    async def add_grant(self, ctx, role, target_role):
        server = ctx.message.server
        if server.id not in ('217677285442977792', '353927534439825429'):
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
    @cooldown(2, 4)
    async def remove_grant(self, ctx, role, target_role):
        server = ctx.message.server
        if server.id not in ('217677285442977792', '353927534439825429'):
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

    @command(pass_context=True)
    @cooldown(1, 3)
    async def text(self, ctx):
        server = ctx.message.server
        if server.id not in ('217677285442977792', '353927534439825429'):
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


def setup(bot):
    bot.add_cog(ServerSpecific(bot))
