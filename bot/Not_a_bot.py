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
from typing import Optional

import matplotlib
from disnake.ext import tasks

matplotlib.use('Agg')

import logging
import time

from redis.asyncio.client import Redis
import disnake
from asyncpg.exceptions import PostgresError, InterfaceError

from bot.botbase import BotBase
from bot.server import WebhookServer
from utils.init_tf import LoadedModel
from utils.utilities import (random_color)

logger = logging.getLogger('terminal')


class NotABot(BotBase):
    def __init__(self, prefix, conf, test_mode=False, cogs=None, model: LoadedModel=None, poke_model=None, **options):
        super().__init__(prefix, conf, test_mode=test_mode, cogs=cogs, **options)

        self._tf_model = model
        self._poke_model = poke_model
        self.polls = {}
        self.timeouts = {}
        self.temproles = {}
        self.banner_rotate = {}
        self.gachilist = []
        self.every_giveaways = {}
        self.anti_abuse_switch = False  # lol
        self._server = WebhookServer(self)
        self.redis: Optional[Redis] = None
        self.antispam = True
        self._ready_called = False

    async def async_init(self):
        await super().async_init()
        await self._server.create_server()

    @property
    def server(self):
        return self._server

    @property
    def tf_model(self):
        return self._tf_model

    @property
    def poke_model(self):
        return self._poke_model

    async def cache_guilds(self):
        logger.info('Caching guilds')
        t = time.time()
        guilds = self.guilds
        sql = 'SELECT guild FROM guilds'
        guild_ids = {r[0] for r in await self.dbutil.fetch(sql)}
        new_guilds = {s.id for s in guilds}.difference(guild_ids)

        blacklisted = await self.dbutil.get_blacklisted_guilds()
        blacklisted = {row['guild'] for row in blacklisted}

        for guild in guilds:
            if guild.id in blacklisted:
                await guild.leave()
                continue

            if guild.unavailable:
                continue
            if len(guild.roles) < 2:
                continue

            if not self._ready_called:
                await self.dbutil.index_guild_roles(guild)
                await self.dbutil.index_join_dates(guild)

        logger.debug('Caching prefixes')
        if new_guilds:
            await self.dbutils.add_guilds(*new_guilds)

        sql = 'SELECT guilds.*, prefixes.prefix FROM guilds LEFT OUTER JOIN prefixes ON guilds.guild=prefixes.guild'
        rows = {}
        for row in await self.dbutil.fetch(sql):
            guild_id = row['guild']
            if guild_id in rows:
                prefix = row['prefix']
                if prefix is not None:
                    rows[guild_id]['prefixes'].add(prefix)

            else:
                d = {**row}
                d.pop('guild', None)
                d['prefixes'] = {d.get('prefix') or self.default_prefix}
                d.pop('prefix', None)
                rows[guild_id] = d

        for guild_id, row in rows.items():
            self.guild_cache.update_cached_guild(guild_id, **row)

        if not self._ready_called:
            logger.info('Indexing user roles')
            for guild in guilds:
                if self.guild_cache.keeproles(guild.id):
                    if guild.unavailable:
                        continue

                    success = await self.dbutil.index_guild_member_roles(guild)
                    if not success:
                        raise EnvironmentError('Failed to cache keeprole servers')

        # Always chunk my own server
        g = self.get_guild(217677285442977792)
        if g:
            await g.chunk()

        logger.info('Guilds cached')
        logger.info('Cached guilds in {} seconds'.format(round(time.time()-t, 2)))

    async def on_ready(self):
        logger.info(f'Logged in as {self.user.name}')

        # If this has been already called once only do a subset of actions
        if self._ready_called:
            if self.config.default_activity:
                await self.change_presence(activity=disnake.Activity(**self.config.default_activity))
            return

        self._ready_called = True

        self._random_color_task.start()

        self._mention_prefix = (self.user.mention + ' ', f'<@!{self.user.id}> ')
        await self.dbutil.add_command('help')
        try:
            await self.cache_guilds()
        except InterfaceError as e:
            logger.exception("Failed to cache guilds")
            raise e

        self.redis: Redis = self.create_redis()

        self.do_not_track = await self.dbutil.get_do_not_track()

        if self.config.default_activity:
            await self.change_presence(activity=disnake.Activity(**self.config.default_activity))
        logger.debug('READY')

    def create_redis(self) -> Redis:
        logger.info('Creating redis connection')
        redis = Redis.from_url(f'redis://{self.config.redis_host}',
                               port=self.config.redis_port,
                               encoding='utf-8')

        return redis

    @tasks.loop(hours=3)
    async def _random_color_task(self):
        if self.test_mode:
            return

        guild = self.get_guild(217677285442977792)
        if not guild:
            return

        role = guild.get_role(348208141541834773)
        if not role:
            return

        await role.edit(color=random_color())

    async def on_guild_join(self, guild):
        logger.info(f'Joined guild {guild.name} {guild.id}')
        if await self.dbutil.is_guild_blacklisted(guild.id):
            await guild.leave()
            return

        sql = 'INSERT INTO guilds (guild) VALUES (%s) ON CONFLICT (guild) DO NOTHING' % guild.id
        try:
            await self.dbutil.execute(sql)
            await self.dbutil.execute('INSERT INTO prefixes (guild) VALUES (%s) ON CONFLICT DO NOTHING' % guild.id)
        except PostgresError:
            logger.exception('Failed to add new server')

        sql = 'SELECT guilds.*, prefixes.prefix FROM guilds LEFT OUTER JOIN prefixes ON guilds.guild=prefixes.guild WHERE guilds.guild=%s' % guild.id
        rows = await self.dbutil.fetch(sql)
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
