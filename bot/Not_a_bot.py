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
from concurrent.futures import ThreadPoolExecutor

import discord
from discord.ext.commands import CommandNotFound, CommandError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import scoped_session, sessionmaker

from bot import exceptions
from bot.bot import Bot
from bot.cooldown import CooldownManager
from bot.dbutil import DatabaseUtils
from bot.globals import BlacklistTypes
from bot.guildcache import GuildCache
from utils.utilities import (split_string, slots2dict, retry, random_color,
                             check_perms)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')

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
    'cogs.misc',
    'cogs.moderator',
    'cogs.neural_networks',
    'cogs.pokemon',
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
    def __init__(self, prefix, conf, aiohttp=None, test_mode=False, **options):
        super().__init__(self.get_command_prefix, conf, aiohttp, **options)
        cdm = CooldownManager()
        cdm.add_cooldown('oshit', 3, 8)
        self.cdm = cdm
        self.default_prefix = prefix
        self.test_mode = test_mode
        if test_mode:
            self.loop.set_debug(True)

        self._random_color = None
        self.polls = {}
        self.timeouts = {}
        self._guild_cache = GuildCache(self)
        self.hi_new = {ord(c): '' for c in ", '"}
        self._dbutil = DatabaseUtils(self)
        self._setup()
        self.threadpool = ThreadPoolExecutor(4)
        self.loop.set_default_executor(self.threadpool)
        self.playlists = {}
        self.anti_abuse_switch = False  # lol

    def _setup(self):
        db = 'discord' if not self.test_mode else 'test'
        engine = create_engine('mysql+pymysql://{0.db_user}:{0.db_password}@{0.db_host}:{0.db_port}/{1}?charset=utf8mb4'.format(self.config, db),
                               encoding='utf8', pool_recycle=36000)
        session_factory = sessionmaker(bind=engine)
        Session = scoped_session(session_factory)
        self._Session = Session
        self._engine = engine

    @staticmethod
    def get_command_prefix(self, message):
        guild = message.guild
        return self.default_prefix if not guild else self.guild_cache.prefixes(guild.id)

    async def cache_guilds(self):
        import time
        t = time.time()
        guilds = self.guilds
        sql = 'SELECT guild FROM `guilds`'
        guild_ids = {r[0] for r in await self.dbutil.execute(sql)}
        new_guilds = {s.id for s in guilds}.difference(guild_ids)
        for guild in guilds:
            await self.dbutil.index_guild_roles(guild)

        await self.dbutils.add_guilds(*new_guilds)
        sql = 'SELECT guilds.*, prefixes.prefix FROM `guilds` LEFT OUTER JOIN `prefixes` ON guilds.guild=prefixes.guild'
        rows = {}
        for row in await self.dbutil.execute(sql):
            guild_id = row['guild']
            if guild_id in rows:
                prefix = row['prefix']
                if prefix is not None:
                    rows[guild_id]['prefixes'].add(prefix)

            else:
                d = {**row}
                d.pop('guild', None)
                d['prefixes'] = {d.get('prefix') or self.default_prefix}
                d.pop('prefix')
                rows[guild_id] = d

        for guild_id, row in rows.items():
            self.guild_cache.update_cached_guild(guild_id, **row)

        for guild in guilds:
            if self.guild_cache.keeproles(guild.id):
                success = await self.dbutil.index_guild_member_roles(guild)
                if not success:
                    raise EnvironmentError('Failed to cache keeprole servers')

        logger.info('Cached guilds in {} seconds'.format(round(time.time()-t, 2)))

    @property
    def get_session(self):
        return self._Session()

    @property
    def engine(self):
        return self._engine

    @property
    def guild_cache(self):
        return self._guild_cache

    @property
    def dbutil(self):
        return self._dbutil

    @property
    def dbutils(self):
        return self._dbutil

    def _load_cogs(self, print_err=True):
        if not print_err:
            errors = []
        for cog in initial_cogs:
            try:
                self.load_extension(cog)
            except Exception as e:
                if not print_err:
                    errors.append('Failed to load extension {}\n{}: {}'.format(cog, type(e).__name__, e))
                else:
                    terminal.warning('Failed to load extension {}\n{}: {}'.format(cog, type(e).__name__, e))

        if not print_err:
            return errors

    def _unload_cogs(self):
        for c in initial_cogs:
            self.unload_extension(c)

    async def on_ready(self):
        terminal.info('Logged in as {0.user.name}'.format(self))
        await self.dbutil.add_command('help')
        await self.cache_guilds()
        await self.loop.run_in_executor(self.threadpool, self._load_cogs)
        if self.config.default_activity:
            await self.change_presence(activity=discord.Activity(**self.config.default_activity))
        if self._random_color is None:
            self._random_color = self.loop.create_task(self._random_color_task())
        terminal.debug('READY')

    async def _random_color_task(self):
        if self.test_mode:
            return
        guild = self.get_guild(217677285442977792)
        if not guild:
            return

        role = self.get_role(348208141541834773, guild)
        if not role:
            return

        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return

            try:
                await role.edit(color=random_color())
            except discord.HTTPException:
                role = self.get_role(348208141541834773, guild)
                if role is None:
                    return

    async def on_message(self, message):
        await self.wait_until_ready()
        if message.author.bot or message.author == self.user:
            return

        await self.process_commands(message)

        oshit = self.cdm.get_cooldown('oshit')
        channel = message.channel
        if oshit and oshit.trigger(False) and message.content.lower().strip() == 'o shit':
            msg = 'waddup'
            await channel.send(msg)

            try:
                await self.wait_for('message', timeout=12, check=lambda m: m.author == message.author and m.content == 'here come')
            except asyncio.TimeoutError:
                await channel.send(':(')
            else:
                await channel.send('dat boi')
            return

    async def on_guild_join(self, guild):
        sql = 'INSERT IGNORE INTO `guilds` (`guild`) VALUES (%s)' % guild.id
        try:
            await self.dbutil.execute(sql)
            await self.dbutil.execute('INSERT IGNORE INTO `prefixes` (`guild`) VALUES (%s)' % guild.id, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add new server')

        sql = 'SELECT guilds.*, prefixes.prefix FROM `guilds` LEFT OUTER JOIN `prefixes` ON guilds.guild=prefixes.guild WHERE guilds.guild=%s' % guild.id
        rows = (await self.dbutil.execute(sql)).fetchall()
        if not rows:
            return

        prefixes = {r['prefix'] for r in rows if r['prefix'] is not None} or {self.default_prefix}
        d = {**rows[0]}
        d.pop('guild', None)
        d.pop('prefix', None)
        d['prefixes'] = prefixes
        self.guild_cache.update_cached_guild(guild.id, **d)

    async def on_guild_role_delete(self, role):
        await self.dbutils.delete_role(role.id, role.guild.id)

    async def _wants_to_be_noticed(self, member, guild, remove=True):
        role = self.get_role(318762162552045568, guild)
        if not role:
            return

        name = member.name if not member.nick else member.nick
        if ord(name[0]) <= 46:
                await retry(member.add_roles, role, break_on=discord.Forbidden, reason="Wants attention")

        elif remove and role in member.roles:
                await retry(member.remove_roles, role, break_on=discord.Forbidden, reason="Doesn't want attention")

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

    async def _check_auth(self, user_id, auth_level):
        if auth_level == 0:
            return True

        sql = 'SELECT `auth_level` FROM `bot_staff` WHERE user=%s' % user_id
        rows = (await self.dbutil.execute(sql)).fetchall()
        if not rows:
            return False

        if rows[0]['auth_level'] >= auth_level:
            return True
        else:
            return False

    async def check_auth(self, ctx):
        if not await self._check_auth(ctx.author.id, ctx.command.auth):
            raise exceptions.PermissionError("You aren't authorized to use this command")

        return True

    async def invoke(self, ctx):
        if ctx.command is not None:
            if ctx.guild:
                s = '{0.name}/{0.id}/{1.name}/{1.id} {2} called {3}'.format(ctx.guild, ctx.channel, str(ctx.author), ctx.command.name)
            else:
                s = 'DM/{0.id} {0} called {1}'.format(ctx.author, ctx.command.name)
            terminal.info(s)
            logger.debug(s)
            self.dispatch('command', ctx)
            try:
                if (await self.can_run(ctx, call_once=True)):
                    await ctx.command.invoke(ctx)
            except CommandError as e:
                await self.on_command_error(ctx, e)
                return
            else:
                self.dispatch('command_completion', ctx)
        elif ctx.invoked_with:
            exc = CommandNotFound('Command "{}" is not found'.format(ctx.invoked_with))
            self.dispatch('command_error', ctx, exc)
