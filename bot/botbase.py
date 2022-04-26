"""
MIT License

Copyright (c) 2017-2019 s0hvaperuna

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
from typing import Union

import asyncpg
import disnake
from disnake import ApplicationCommandInteraction

from bot import exceptions
from bot.bot import Bot, Context
from bot.dbutil import DatabaseUtils
from bot.globals import Auth
from bot.guildcache import GuildCache

logger = logging.getLogger('terminal')


class BotBase(Bot):
    """Base class for main bot. Used to separate audio part from main bot"""
    def __init__(self, prefix, conf, test_mode=False, cogs=None, **options):
        super().__init__(self.get_command_prefix, conf, **options)
        self.default_prefix = prefix
        self._mention_prefix = ()
        self.test_mode = test_mode
        if test_mode:
            self.loop.set_debug(True)

        self._guild_cache = GuildCache(self)
        self._dbutil = DatabaseUtils(self)
        self.call_laters = {}
        self.threadpool = ThreadPoolExecutor(4)
        self.loop.set_default_executor(self.threadpool)
        self.do_not_track = set()

        if cogs:
            self.default_cogs = set(cogs)
        else:
            self.default_cogs = set()

    async def async_init(self):
        await self._setup_db()
        await self.dbutil.add_command('help')

    def load_default_cogs(self):
        for cog in self.default_cogs:
            self.load_extension(cog)

    def can_track(self, user: Union[int, disnake.User, disnake.Member]) -> bool:
        if isinstance(user, int):
            uid = user
        else:
            uid = user.id

        return uid not in self.do_not_track

    async def _setup_db(self):
        db = 'discord' if not self.test_mode else 'test'
        self._pool = await asyncpg.create_pool(database=db,
                                               user=self.config.db_user,
                                               host=self.config.db_host,
                                               loop=self.loop,
                                               password=self.config.db_password,
                                               max_inactive_connection_lifetime=600,
                                               min_size=10,
                                               max_size=20)

    # The prefix function is defined to take bot as it's first parameter
    # no matter what so in order to not have the same object added in twice
    # I made this a staticmethod instead
    @staticmethod
    def get_command_prefix(self, message):  # skipcq: PYL-W0211
        guild = message.guild
        if not guild:
            prefixes = (*self._mention_prefix, self.default_prefix)
        else:
            prefixes = (*self.guild_cache.prefixes(guild.id), *self._mention_prefix)
        return prefixes

    @property
    def pool(self) -> asyncpg.Pool:
        return self._pool

    @property
    def guild_cache(self):
        return self._guild_cache

    @property
    def dbutil(self) -> DatabaseUtils:
        return self._dbutil

    @property
    def dbutils(self) -> DatabaseUtils:
        return self._dbutil

    async def on_ready(self):
        self._mention_prefix = (self.user.mention, f'<@!{self.user.id}>')
        logger.info(f'Logged in as {self.user.name}')
        logger.debug('READY')

        for guild in self.guilds:
            if await self.dbutil.is_guild_blacklisted(guild.id):
                await guild.leave()
                continue

    async def run_async(self, f, *args):
        return await self.loop.run_in_executor(self.threadpool, f, *args)

    async def on_message(self, message):
        local = time.perf_counter()
        await self.wait_until_ready()
        if message.author.bot or message.author == self.user:
            return

        # Ignore if user is botbanned
        if message.author.id != self.owner_id and (await self.dbutil.fetch('SELECT 1 FROM banned_users WHERE uid=%s' % message.author.id, fetchmany=False)):
            return

        await self.process_commands(message, local_time=local)

    async def _check_auth(self, user_id, auth_level):
        if auth_level == 0:
            return True

        sql = 'SELECT auth_level FROM bot_staff WHERE uid=%s' % user_id
        rows = await self.dbutil.fetch(sql, fetchmany=False)
        if not rows:
            return False

        if rows['auth_level'] >= auth_level:
            return True
        else:
            return False

    async def check_auth(self, ctx: Context | ApplicationCommandInteraction):
        if isinstance(ctx, ApplicationCommandInteraction):
            return True

        if not hasattr(ctx.command, 'auth'):
            return True

        if not await self._check_auth(ctx.author.id, ctx.command.auth):
            raise exceptions.PermException(Auth.to_string(ctx.command.auth))

        return True

    async def on_guild_join(self, guild):
        logger.info(f'Joined guild {guild.name} {guild.id}')
        if await self.dbutil.is_guild_blacklisted(guild.id):
            await guild.leave()
            return
