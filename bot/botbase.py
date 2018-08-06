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

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from discord.ext.commands import CommandNotFound, CommandError
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from bot import exceptions
from bot.bot import Bot
from bot.dbutil import DatabaseUtils
from bot.globals import Auth
from bot.guildcache import GuildCache

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class BotBase(Bot):
    """Base class for main bot. Used to separate audio part from main bot"""
    def __init__(self, prefix, conf, aiohttp=None, test_mode=False, cogs=None, **options):
        super().__init__(self.get_command_prefix, conf, aiohttp, **options)
        self.default_prefix = prefix
        self._mention_prefix = ()
        self.test_mode = test_mode
        if test_mode:
            self.loop.set_debug(True)

        self._guild_cache = GuildCache(self)
        self._dbutil = DatabaseUtils(self)
        self.call_laters = {}
        self._setup_db()
        self.threadpool = ThreadPoolExecutor(4)
        self.loop.set_default_executor(self.threadpool)

        if cogs:
            self.default_cogs = {'cogs.' + c for c in cogs}
        else:
            self.default_cogs = set()

    def _setup_db(self):
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
        if not guild:
            prefixes = (*self._mention_prefix, self.default_prefix)
        else:
            prefixes = (*self.guild_cache.prefixes(guild.id), *self._mention_prefix)
        return prefixes

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
        self._mention_prefix = (self.user.mention, f'<@!{self.user.id}>')
        terminal.info('Logged in as {0.user.name}'.format(self))
        await self.dbutil.add_command('help')
        await self.loop.run_in_executor(self.threadpool, self._load_cogs)
        terminal.debug('READY')

        for guild in self.guilds:
            if await self.dbutil.is_guild_blacklisted(guild.id):
                await guild.leave()
                continue

    async def on_message(self, message):
        local = time.perf_counter()
        await self.wait_until_ready()
        if message.author.bot or message.author == self.user:
            return

        # Ignore if user is botbanned
        if message.author.id != self.owner_id and (await self.dbutil.execute('SELECT 1 FROM `banned_users` WHERE user=%s' % message.author.id)).first():
            return

        await self.process_commands(message, local_time=local)

    async def _check_auth(self, user_id, auth_level):
        if auth_level == 0:
            return True

        sql = 'SELECT `auth_level` FROM `bot_staff` WHERE user=%s' % user_id
        rows = (await self.dbutil.execute(sql)).first()
        if not rows:
            return False

        if rows['auth_level'] >= auth_level:
            return True
        else:
            return False

    async def check_auth(self, ctx):
        if not await self._check_auth(ctx.author.id, ctx.command.auth):
            raise exceptions.PermException(Auth.to_string(ctx.command.auth))

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

    async def on_guild_join(self, guild):
        terminal.info(f'Joined guild {guild.name} {guild.id}')
        if await self.dbutil.is_guild_blacklisted(guild.id):
            await guild.leave()
            return
