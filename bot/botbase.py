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
from bot.guildcache import GuildCache
from utils.utilities import (split_string, slots2dict, retry, random_color)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class BotBase(Bot):
    """Base class for main bot. Used to separate audio part from main bot"""
    def __init__(self, prefix, conf, aiohttp=None, test_mode=False, cogs=None, **options):
        super().__init__(self.get_command_prefix, conf, aiohttp, **options)
        self.default_prefix = prefix
        self.test_mode = test_mode
        if test_mode:
            self.loop.set_debug(True)

        self._guild_cache = GuildCache(self)
        self._dbutil = DatabaseUtils(self)
        self._setup()
        self.threadpool = ThreadPoolExecutor(4)
        self.loop.set_default_executor(self.threadpool)

        if cogs:
            self.default_cogs = {'cogs.' + c for c in cogs}
        else:
            self.default_cogs = set()

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
        for cog in self.default_cogs:
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
        for c in self.default_cogs:
            self.unload_extension(c)

    async def on_ready(self):
        terminal.info('Logged in as {0.user.name}'.format(self))
        await self.dbutil.add_command('help')
        await self.loop.run_in_executor(self.threadpool, self._load_cogs)
        if self.config.default_activity:
            await self.change_presence(activity=discord.Activity(**self.config.default_activity))
        terminal.debug('READY')

    async def on_message(self, message):
        await self.wait_until_ready()
        if message.author.bot or message.author == self.user:
            return

        # Ignore if user is botbanned
        if message.author.id != self.owner_id and (await self.dbutil.execute('SELECT 1 FROM `banned_users` WHERE user=%s' % message.author.id)).first():
            return

        await self.process_commands(message)

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
            raise exceptions.PermException()

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
