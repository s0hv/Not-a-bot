from cogs.cog import Cog
from bot.bot import command
from discord.ext.commands import cooldown
from sqlalchemy import text
from bot.globals import BlacklistTypes
from utils.utilities import check_channel_mention, check_role_mention, check_user_mention
import logging
import discord

logger = logging.getLogger('debug')
perms = discord.Permissions(8)


class CommandBlacklist(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(pass_context=True, ignore_extra=True, no_pm=True, required_perms=perms)
    @cooldown(1, 5)
    async def blacklist(self, ctx, command_: str, mention=None):
        msg = ctx.message
        server = msg.server

        async def _blacklist(name):
            if mention is None:
                whereclause = 'server=%s AND type IN (%s, %s) AND command="%s" AND channel IS NULL AND role IS NULL AND user IS NULL' % (
                               server.id, BlacklistTypes.BLACKLIST, BlacklistTypes.WHITELIST, name)
                success = await self._set_blacklist(whereclause, server=int(server.id), command=name)
                if success:
                    await self.bot.say('Blacklisted command {} from this server'.format(name))
                elif success is None:
                    await self.bot.say('Removed blacklist for command {} on this server'.format(name))

            elif check_user_mention(msg, mention):
                await self._add_user_blacklist(name, msg.mentions[0], server)

            elif msg.raw_role_mentions:
                id = msg.raw_role_mentions[0]
                if id not in mention:
                    return await self.bot.say('Invalid role mention or arguments not provided correctly')

                role = list(filter(lambda r: r.id == id, server.roles))
                if not role:
                    return await self.bot.say('Invalid role mention or arguments not provided correctly')

                await self._add_role_blacklist(name, role[0], server)

            elif check_channel_mention(msg, mention):
                await self._add_channel_blacklist(name, msg.channel_mentions[0], server)
            else:
                await self.bot.say('Failed to parse mentions')

        commands = command_.split(' ')
        for command_ in commands:
            command = self.bot.get_command(command_)
            if command is None:
                if not await self._set_all_commands(server, msg, command_):
                    await self.bot.say('Could not find command %s' % command_)
                continue

            await _blacklist(command)

    async def _set_all_commands(self, server, msg, mention, type=BlacklistTypes.BLACKLIST):
        values = {'command': None, 'server': int(server.id), 'type': type}
        role = check_role_mention(msg, mention, server)
        where = 'server=%s AND command IS NULL AND NOT type=%s AND ' % (server.id, BlacklistTypes.GLOBAL)
        type_string = 'Blacklisted' if type == BlacklistTypes.BLACKLIST else 'Whitelisted'
        type_string2 = 'blacklist' if type == BlacklistTypes.BLACKLIST else 'whitelist'

        if check_user_mention(msg, mention):
            userid = msg.mentions[0].id
            success = await self._set_blacklist(where + 'user=%s' % userid, user=int(userid), **values)
            if success:
                message = '%s all commands from user %s' % (type_string, msg.mentions[0])
            elif success is None:
                message = 'removed %s from user %s' % (type_string2, msg.mentions[0])

        elif role:
            success = await self._set_blacklist(where + 'role=%s' % role.id, role=int(role.id), **values)
            if success:
                message = '{0} all commands from role {1} `{1.id}`'.format(type_string, role)
            elif success is None:
                message = 'Removed {0} from role {1} `{1.id}`'.format(type_string2, role)

        elif check_channel_mention(msg, mention):
            channel = msg.channel_mentions[0]
            success = await self._set_blacklist(where + 'channel=%s' % channel.id,
                                                channel=int(channel.id), **values)
            if success:
                message = '{0} all commands from channel {1} `{1.id}`'.format(type_string, channel)
            elif success is None:
                message = 'Removed {0} from channel {1} `{1.id}`'.format(type_string2, channel)

        else:
            return False

        await self.bot.say(message)
        return True

    @command(pass_context=True, required_perms=perms, ignore_extra=True, no_pm=True)
    @cooldown(1, 5)
    async def whitelist(self, ctx, command_: str, mention=None):
        msg = ctx.message
        server = msg.server

        async def _whitelist(_command):
            name = _command.name
            if mention is None:
                return await self.bot.say('Please mention the thing you want to whitelist. (user, role, channel)')

            elif msg.mentions:
                if mention != msg.mentions[0].mention:
                    return await self.bot.say('Invalid user mention or arguments not provided correctly')

                await self._add_user_whitelist(name, msg.mentions[0], server)

            elif msg.raw_role_mentions:
                id = msg.raw_role_mentions[0]
                role = list(filter(lambda r: r.id == id, server.roles))
                if not role:
                    return await self.bot.say('Invalid role mention or arguments not provided correctly')

                await self._add_role_whitelist(name, role[0], server)

            elif msg.channel_mentions:
                if mention != msg.channel_mentions[0].mention:
                    return await self.bot.say('Invalid channel mention or arguments not provided correctly')

                await self._add_channel_whitelist(name, msg.channel_mentions[0], server)
            else:
                await self.bot.say('Could not get the user/role/channel from %s' % mention)

        for command_ in command_.split(' '):
            _command = self.bot.get_command(command_)
            if command is None:
                if not await self._set_all_commands(server, msg, command_, type=BlacklistTypes.WHITELIST):
                    await self.bot.say('Could not find command %s' % command_)
                continue
            await _whitelist(_command)

    async def _set_blacklist(self, whereclause, type=BlacklistTypes.BLACKLIST, **values):
        session = self.bot.get_session
        type_string = 'blacklist' if type == BlacklistTypes.BLACKLIST else 'whitelist'
        sql = 'SELECT `id`, `type` FROM `command_blacklist` WHERE %s' % whereclause
        row = session.execute(text(sql)).first()
        if row:
            if row['type'] == type:
                sql = 'DELETE FROM `command_blacklist` WHERE id=%s' % (
                row['id'])
                try:
                    session.execute(text(sql))
                except:
                    logger.exception('Could not update %s with whereclause %s' % (type_string, whereclause))
                    await self.bot.say('Failed to remove %s' % type_string)
                    return False
                else:
                    return
            else:
                sql = 'UPDATE `command_blacklist` SET type=%s WHERE id=%s' % (
                type, row['id'])
                try:
                    session.execute(text(sql))
                except:
                    logger.exception('Could not update %s with whereclause %s' % (type_string, whereclause))
                    await self.bot.say('Failed to remove %s' % type_string)
                    return False
                else:
                    return True
        else:
            sql = 'INSERT INTO `command_blacklist` ('
            values['type'] = type
            keys = values.keys()
            val = '('
            l = len(keys)
            for idx, k in enumerate(keys):
                sql += '`%s`' % k
                val += ':%s' % k
                if idx != l - 1:
                    sql += ', '
                    val += ', '

            sql += ') VALUES ' + val + ')'
            try:
                session.execute(text(sql), params=values)
            except:
                logger.exception('Could not set values %s' % values)
                await self.bot.say('Failed to set %s' % type_string)
                return False

        session.commit()
        return True

    async def _add_user_blacklist(self, command_name, user, server):
        whereclause = 'server=%s AND command="%s" AND user=%s AND NOT type=%s' % (
                       server.id, command_name, user.id, BlacklistTypes.GLOBAL)
        success = await self._set_blacklist(whereclause, command=command_name,
                                            user=int(user.id),
                                            server=int(server.id))
        if success:
            await self.bot.say('Blacklisted command {0} from user {1} `{1.id}`'.format(command_name, user))
        elif success is None:
            await self.bot.say('Removed command {0} blacklist from user {1} `{1.id}`'.format(command_name, user))

    async def _add_role_blacklist(self, command_name, role, server):
        whereclause = 'server=%s AND command="%s" AND role=%s AND NOT type=%s' % (
                       server.id, command_name, role.id, BlacklistTypes.GLOBAL)
        success = await self._set_blacklist(whereclause, command=command_name,
                                            role=int(role.id),
                                            server=int(server.id))
        if success:
            await self.bot.say('Blacklisted command {0} from role {1} `{1.id}`'.format(command_name, role))
        elif success is None:
            await self.bot.say('Removed command {0} blacklist from role {1} `{1.id}`'.format(command_name, role))

    async def _add_channel_blacklist(self, command_name, channel, server):
        whereclause = 'server=%s AND command="%s" AND channel=%s AND NOT type=%s' % (
        server.id, command_name, channel.id, BlacklistTypes.GLOBAL)
        success = await self._set_blacklist(whereclause, command=command_name,
                                            channel=int(channel.id),
                                            server=int(server.id))
        if success:
            await self.bot.say('Blacklisted command {0} from channel {1} `{1.id}`'.format(command_name, channel))
        elif success is None:
            await self.bot.say('Removed command {0} blacklist from channel {1} `{1.id}`'.format(command_name, channel))

    async def _add_user_whitelist(self, command_name, user, server):
        whereclause = 'server=%s AND command="%s" AND user=%s AND NOT type=%s' % (
                       server.id, command_name, user.id, BlacklistTypes.GLOBAL)
        success = await self._set_blacklist(whereclause,
                                            type=BlacklistTypes.WHITELIST,
                                            command=command_name,
                                            user=int(user.id),
                                            server=int(server.id))
        if success:
            await self.bot.say('Whitelisted command {0} from user {1} `{1.id}`'.format(command_name, user))
        elif success is None:
            await self.bot.say('Removed command {0} whitelist from user {1} `{1.id}`'.format(command_name, user))

    async def _add_role_whitelist(self, command_name, role, server):
        whereclause = 'server=%s AND command="%s" AND role=%s AND NOT type=%s' % (
                       server.id, command_name, role.id, BlacklistTypes.GLOBAL)
        success = await self._set_blacklist(whereclause,
                                            type=BlacklistTypes.WHITELIST,
                                            command=command_name,
                                            role=int(role.id),
                                            server=int(server.id))
        if success:
            await self.bot.say('Whitelisted command {0} from role {1} `{1.id}`'.format(command_name, role))
        elif success is None:
            await self.bot.say('Removed command {0} whitelist from role {1} `{1.id}`'.format(command_name, role))

    async def _add_channel_whitelist(self, command_name, channel, server):
        whereclause = 'server=%s AND command="%s" AND channel=%s AND NOT type=%s' % (
                       server.id, command_name, channel.id, BlacklistTypes.GLOBAL)
        success = await self._set_blacklist(whereclause,
                                            type=BlacklistTypes.WHITELIST,
                                            command=command_name,
                                            channel=int(channel.id),
                                            server=int(server.id))
        if success:
            await self.bot.say('Whitelisted command {0} from channel {1} `{1.id}`'.format(command_name, channel))
        elif success is None:
            await self.bot.say('Removed command {0} whitelist from channel {1} `{1.id}`'.format(command_name, channel))

    @command(pass_context=True, owner_only=True)
    async def test_perms(self, ctx, command):
        u = ctx.message.mentions[0] if ctx.message.mentions else ctx.message.author
        await self.bot.say(self.check_blacklist(command, u, ctx))

    def check_blacklist(self, command, user, ctx):
        session = self.bot.get_session
        sql = 'SELECT * FROM `command_blacklist` WHERE type=%s AND command="%s" ' \
              'AND (user=%s OR user IS NULL) LIMIT 1' % (
               BlacklistTypes.GLOBAL, command, user.id)
        rows = session.execute(sql).fetchall()

        if rows:
            return False

        if ctx.message.server is None:
            return True

        channel = ctx.message.channel.id
        if user.roles:
            roles = '(role IS NULL OR role IN ({}))'.format(
                ', '.join(map(lambda r: r.id, user.roles)))
        else:
            roles = 'role IS NULL'
        sql = 'SELECT `type`, `role`, `user`, `channel`  FROM `command_blacklist` WHERE server=%s AND command="%s" ' \
              'AND (user IS NULL OR user=%s) AND %s AND (channel IS NULL OR channel=%s)' % (
                  user.server.id, command, user.id, roles, channel)

        rows = session.execute(sql).fetchall()
        if not rows:
            return True

        values = {'user': 0x1, 'whitelist': 0x0, 'blacklist': 0x2, 'role': 0x4,
                  'channel': 0x8, 'server': 0x10}
        returns = {1: True, 3: False, 4: True, 6: False, 8: True, 10: False,
                   16: True, 18: False}
        smallest = 18
        """
        Here are the returns
            1 user AND whitelist  
            3 user AND blacklist  
            4 whitelist AND role  
            6 blacklist AND role  
            8 channel AND whitelist  
            10 channel AND blacklist 
            16 whitelist AND server 
            18 blacklist AND server 
        """

        for row in rows:
            if row['type'] == BlacklistTypes.WHITELIST:
                v1 = values['whitelist']
            else:
                v1 = values['blacklist']

            if row['user'] is not None:
                v2 = values['user']
            elif row['role'] is not None:
                v2 = values['role']
            elif row['channel'] is not None:
                v2 = values['channel']
            else:
                v2 = values['server']

            v = v1 | v2
            if v < smallest:
                smallest = v

        return returns[smallest]


def setup(bot):
    bot.add_cog(CommandBlacklist(bot))
