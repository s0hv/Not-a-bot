"""
MIT License

Copyright (c) 2017 s0hvaperuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import asyncio
import logging
from datetime import datetime

import discord
from discord.ext import commands
from discord.ext.commands import CommandNotFound, CommandError
from discord.ext.commands.view import StringView
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from bot import exceptions
from bot.bot import Bot, Context
from bot.cooldown import CooldownManager
from bot.dbutil import DatabaseUtils
from bot.globals import BlacklistTypes
from bot.servercache import ServerCache
from utils.utilities import (split_string, slots2dict, retry, random_color)

logger = logging.getLogger('debug')

initial_cogs = [
    'cogs.admin',
    'cogs.audio',
    'cogs.autoresponds',
    'cogs.autoroles',
    'cogs.botadmin',
    'cogs.botmod',
    'cogs.colors',
    'cogs.command_blacklist',
    'cogs.emotes',
    'cogs.gachiGASM',
    'cogs.hearthstone',
    'cogs.images',
    'cogs.jojo',
    'cogs.logging',
    'cogs.management',
    'cogs.misc',
    'cogs.moderator',
    'cogs.neural_networks',
    'cogs.search',
    'cogs.server',
    'cogs.server_specific',
    'cogs.settings',
    'cogs.stats',
    'cogs.utils',
    'cogs.voting']


class Object:
    def __init__(self):
        pass


class NotABot(Bot):
    def __init__(self, prefix, conf, aiohttp=None, **options):
        super().__init__(prefix, conf, aiohttp, **options)
        cdm = CooldownManager()
        cdm.add_cooldown('oshit', 3, 8)
        self.cdm = cdm
        self._random_color = None
        self.polls = {}
        self.timeouts = {}
        self._server_cache = ServerCache(self)
        self._perm_values = {'user': 0x1, 'whitelist': 0x0, 'blacklist': 0x2, 'role': 0x4, 'channel': 0x8, 'server': 0x10}
        self._perm_returns = {1: True, 3: False, 4: True, 6: False, 8: True, 10: False, 16: True, 18: False}
        self._blacklist_messages = {3: 'Command has been blacklisted for you',
                                    6: 'Command has been blacklisted for a role you have',
                                    10: None, 18: None}

        self.hi_new = {ord(c): '' for c in ", '"}
        self._dbutil = DatabaseUtils(self)
        self._setup()

    def _setup(self):
        db = 'test'
        engine = create_engine('mysql+pymysql://{0.db_user}:{0.db_password}@{0.db_host}:{0.db_port}/{1}?charset=utf8mb4'.format(self.config, db),
                               encoding='utf8')
        session_factory = sessionmaker(bind=engine)
        Session = scoped_session(session_factory)
        self._Session = Session
        self.mysql = Object()
        self.mysql.session = self.get_session
        self.mysql.engine = engine

    def cache_servers(self):
        servers = self.servers
        sql = 'SELECT * FROM `servers`'
        session = self.get_session
        ids = set()
        for row in session.execute(sql).fetchall():
            d = {**row}
            d.pop('server', None)
            print(d)
            self.server_cache.update_cached_server(str(row['server']), **d)
            ids.add(str(row['server']))

        new_servers = []
        for server in servers:
            if server.id in ids:
                continue

            new_servers.append('(%s)' % server.id)

        if new_servers:
            sql = 'INSERT INTO `servers` (`server`) VALUES ' + ', '.join(new_servers)
            try:
                session.execute(sql)
                session.commit()
            except:
                session.rollback()
                logger.exception('Failed to add new servers to db')

    @property
    def get_session(self):
        return self._Session()

    @property
    def server_cache(self):
        return self._server_cache

    @property
    def dbutil(self):
        return self._dbutil

    @property
    def dbutils(self):
        return self._dbutil

    async def _load_cogs(self):
        for cog in initial_cogs:
            try:
                self.load_extension(cog)
            except Exception as e:
                print('Failed to load extension {}\n{}: {}'.format(cog, type(e).__name__, e))

    async def on_ready(self):
        print('[INFO] Logged in as {0.user.name}'.format(self))
        await self.change_presence(game=discord.Game(name=self.config.game))
        asyncio.ensure_future(self._load_cogs(), loop=self.loop)
        self.cache_servers()
        if self._random_color is None:
            self._random_color = self.loop.create_task(self._random_color_task())

    async def _random_color_task(self):
        server = self.get_server('217677285442977792')
        if not server:
            return

        role = self.get_role(server, '348208141541834773')
        if not role:
            return

        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return

            try:
                await self.edit_role(server, role, color=random_color())
            except:
                role = self.get_role(server, '348208141541834773')
                if role is None:
                    return

    async def on_message(self, message):
        await self.wait_until_ready()
        if message.author.bot or message.author == self.user:
            return

        management = getattr(self, 'management', None)

        if message.server and message.server.id == '217677285442977792' and management and message.channel.id != '322839372913311744':
            if len(message.mentions) + len(message.role_mentions) > 10:
                sql = 'SELECT * FROM `automute_blacklist` WHERE channel_id=%s' % message.channel.id
                if not self.get_session.execute(sql).first():
                    whitelist = self.management.get_mute_whitelist(message.server.id)
                    invulnerable = discord.utils.find(lambda r: r.id in whitelist,
                                                      message.server.roles)
                    if invulnerable is None or invulnerable not in message.author.roles:
                        role = discord.utils.find(lambda r: r.id == '322837972317896704',
                                                  message.server.roles)
                        if role is not None:
                            user = message.author
                            await self.add_role(message.author, role)
                            d = 'Automuted user {0} `{0.id}`'.format(message.author)
                            embed = discord.Embed(title='Moderation action [AUTOMUTE]', description=d, timestamp=datetime.utcnow())
                            embed.add_field(name='Reason', value='Too many mentions in a message')
                            embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
                            embed.set_footer(text=str(self.user), icon_url=self.user.avatar_url or self.user.default_avatar_url)
                            chn = message.server.get_channel(self.server_cache.get_modlog(message.server.id)) or message.channel
                            await self.send_message(chn, embed=embed)
                            return

        # If the message is a command do that instead
        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return

        oshit = self.cdm.get_cooldown('oshit')
        if oshit and oshit.trigger(False) and message.content.lower().strip() == 'o shit':
            msg = 'waddup'
            await self.send_message(message.channel, msg)

            herecome = await self.wait_for_message(timeout=12, author=message.author, content='here come')
            if herecome is None:
                await self.send_message(message.channel, ':(')
            else:
                await self.send_message(message.channel, 'dat boi')
            return

    async def on_server_join(self, server):
        session = self.get_session
        sql = 'INSERT IGNORE INTO `servers` (`server`) ' \
              'VALUES (%s)' % server.id
        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Failed to add new server')

        sql = 'SELECT * FROM `servers` WHERE server=%s' % server.id
        row = session.execute(sql).first()
        if not row:
            return

        self.server_cache.update_cached_server(server.id, **row)

    async def on_server_role_delete(self, role):
        self.dbutils.delete_role(role.id, role.server.id)

    async def _wants_to_be_noticed(self, member, server, remove=True):
        role = list(filter(lambda r: r.id == '318762162552045568', server.roles))
        if not role:
            return

        role = role[0]

        name = member.name if not member.nick else member.nick
        if ord(name[0]) <= 46:
            for i in range(0, 2):
                try:
                    await self.add_role(member, role)
                except:
                    pass
                else:
                    break

        elif remove and role in member.roles:
                await retry(self.remove_role, member, role)

    @staticmethod
    def _parse_on_delete(msg, conf):
        content = msg.content
        user = msg.author

        message = conf['message']
        d = slots2dict(msg)
        d = slots2dict(user, d)
        for e in ['name', 'message']:
            d.pop(e, None)

        d['channel'] = msg.channel.mention
        message = message.format(name=str(user), message=content, **d)
        return split_string(message)

    async def raw_message_delete(self, data):
        id = data.get('id')
        if not id:
            return

        session = self.get_session
        result = session.execute('SELECT `message` `user_id` `server` FROM `messages` WHERE `message_id` = %s' % id)
        msg = result.first()
        if not msg:
            return

        message, user_id, server_id = msg['message'], msg['user_id'], msg['server']
        server = self.get_server(server_id)
        if not server:
            return

        user = server.get_member(user_id)
        if not user:
            return

        channel_id = session.execute('SELECT `on_delete_channel` FROM `servers` WHERE `server` = %s' % server_id).first()
        if not channel_id:
            return

        channel = server.get_channel(channel_id['channel_id'])

    def check_blacklist(self, command, user, ctx):
        session = self.get_session
        sql = 'SELECT * FROM `command_blacklist` WHERE type=%s AND %s ' \
              'AND (user=%s OR user IS NULL) LIMIT 1' % (BlacklistTypes.GLOBAL, command, user.id)
        rows = session.execute(sql).fetchall()

        if rows:
            return False

        if ctx.message.server is None:
            return True

        channel = ctx.message.channel.id
        if user.roles:
            roles = '(role IS NULL OR role IN ({}))'.format(', '.join(map(lambda r: r.id, user.roles)))
        else:
            roles = 'role IS NULL'

        sql = 'SELECT `type`, `role`, `user`, `channel`  FROM `command_blacklist` WHERE server=%s AND %s ' \
              'AND (user IS NULL OR user=%s) AND %s AND (channel IS NULL OR channel=%s)' % (user.server.id, command, user.id, roles, channel)
        rows = session.execute(sql).fetchall()
        if not rows:
            return None

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
                v1 = self._perm_values['whitelist']
            else:
                v1 = self._perm_values['blacklist']

            if row['user'] is not None:
                v2 = self._perm_values['user']
            elif row['role'] is not None:
                v2 = self._perm_values['role']
            elif row['channel'] is not None:
                v2 = self._perm_values['channel']
            else:
                v2 = self._perm_values['server']

            v = v1 | v2
            if v < smallest:
                smallest = v

        return smallest

    def _check_auth(self, user_id, auth_level):
        session = self.get_session
        sql = 'SELECT `auth_level` FROM `bot_staff` WHERE user=%s' % user_id
        rows = session.execute(sql).fetchall()
        if not rows:
            return False

        if rows[0]['auth_level'] >= auth_level:
            return True
        else:
            return False


    # ----------------------------
    # - Overridden methods below -
    # ----------------------------

    async def process_commands(self, message):
        _internal_channel = message.channel
        _internal_author = message.author

        view = StringView(message.content)
        if self._skip_check(message.author, self.user):
            return

        prefix = await self._get_prefix(message)
        invoked_prefix = prefix

        if not isinstance(prefix, (tuple, list)):
            if not view.skip_string(prefix):
                return
        else:
            invoked_prefix = discord.utils.find(view.skip_string, prefix)
            if invoked_prefix is None:
                return

        invoker = view.get_word()
        tmp = {
            'bot': self,
            'invoked_with': invoker,
            'message': message,
            'view': view,
            'prefix': invoked_prefix,
        }
        ctx = Context(**tmp)
        del tmp

        if invoker in self.commands:
            command = self.commands[invoker]
            if command.owner_only and self.owner != message.author.id:
                command.dispatch_error(exceptions.PermissionError('Only the owner can use this command'), ctx)
                return

            if command.no_pm and message.server is None:
                return

            try:
                if command.auth > 0:
                    if not self._check_auth(message.author.id, command.auth):
                        await self.send_message(message.channel, "You aren't authorized to use this command")
                        return

                else:
                    overwrite_perms = self.check_blacklist('(command="%s" OR command IS NULL)' % command, message.author, ctx)
                    msg = self._blacklist_messages.get(overwrite_perms, None)
                    if isinstance(overwrite_perms, int):
                        if message.server.owner.id == message.author.id:
                            overwrite_perms = True
                        else:
                            overwrite_perms = self._perm_returns.get(overwrite_perms, False)

                    if overwrite_perms is False:
                        if msg is not None:
                            await self.send_message(message.channel, msg)
                        return
                    elif overwrite_perms is None and command.required_perms is not None:
                        perms = message.channel.permissions_for(message.author)

                        if not perms.is_superset(command.required_perms):
                            req = [r[0] for r in command.required_perms if r[1]]
                            await self.send_message(message.channel,
                                                    'Invalid permissions. Required perms are %s' % ', '.join(req),
                                                    delete_after=15)
                            return

                    ctx.override_perms = overwrite_perms
            except Exception as e:
                await self.on_command_error(e, ctx)
                return

            self.dispatch('command', command, ctx)
            try:
                await command.invoke(ctx)
            except discord.ext.commands.errors.MissingRequiredArgument as e:
                command.dispatch_error(exceptions.MissingRequiredArgument(e), ctx)
            except CommandError as e:
                ctx.command.dispatch_error(e, ctx)
            else:
                self.dispatch('command_completion', command, ctx)
        elif invoker:
            exc = CommandNotFound('Command "{}" is not found'.format(invoker))
            self.dispatch('command_error', exc, ctx)
