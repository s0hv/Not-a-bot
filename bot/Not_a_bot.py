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
import matplotlib
matplotlib.use('Agg')

import asyncio
import logging
import time

import aioredis
import discord
from sqlalchemy.exc import SQLAlchemyError

from bot.botbase import BotBase
from bot.cooldown import CooldownManager
from bot.server import WebhookServer
from utils.init_tf import LoadedModel
from utils.utilities import (split_string, slots2dict, retry, random_color)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class NotABot(BotBase):
    def __init__(self, prefix, conf, aiohttp=None, test_mode=False, cogs=None, model: LoadedModel=None, poke_model=None, **options):
        super().__init__(prefix, conf, aiohttp=aiohttp, test_mode=test_mode, cogs=cogs, **options)
        cdm = CooldownManager()
        cdm.add_cooldown('oshit', 3, 8)
        self.cdm = cdm
        
        self._random_color = None
        self._tf_model = model
        self._poke_model = poke_model
        self.polls = {}
        self.timeouts = {}
        self.temproles = {}
        self.gachilist = []
        self.hi_new = {ord(c): '' for c in ", '"}
        self.every_giveaways = {}
        self.anti_abuse_switch = False  # lol
        self._server = WebhookServer(self)
        self.redis = None
        self.antispam = True

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
        import time
        t = time.time()
        guilds = self.guilds
        sql = 'SELECT guild FROM `guilds`'
        guild_ids = {r[0] for r in await self.dbutil.execute(sql)}
        new_guilds = {s.id for s in guilds}.difference(guild_ids)
        for guild in guilds:
            if await self.dbutil.is_guild_blacklisted(guild.id):
                await guild.leave()
                continue

            if guild.unavailable:
                continue
            if len(guild.roles) < 2:
                continue

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
                d.pop('prefix', None)
                rows[guild_id] = d

        for guild_id, row in rows.items():
            self.guild_cache.update_cached_guild(guild_id, **row)

        for guild in guilds:
            if self.guild_cache.keeproles(guild.id):
                if guild.unavailable:
                    continue

                success = await self.dbutil.index_guild_member_roles(guild)
                if not success:
                    raise EnvironmentError('Failed to cache keeprole servers')

        logger.info('Cached guilds in {} seconds'.format(round(time.time()-t, 2)))

    async def on_ready(self):
        self._mention_prefix = (self.user.mention + ' ', f'<@!{self.user.id}> ')
        terminal.info('Logged in as {0.user.name}'.format(self))
        await self.dbutil.add_command('help')
        await self.cache_guilds()

        self.redis = await aioredis.create_redis((self.config.db_host, self.config.redis_port),
                                                 password=self.config.redis_auth,
                                                 loop=self.loop, encoding='utf-8')

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

        role = guild.get_role(348208141541834773)
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
                role = guild.get_role(348208141541834773)
                if role is None:
                    return

    async def on_message(self, message):
        local = time.perf_counter()
        await self.wait_until_ready()
        if message.author == self.user:
            return

        # Ignore if user is botbanned
        if message.author.id != self.owner_id and (await self.dbutil.execute('SELECT 1 FROM `banned_users` WHERE user=%s' % message.author.id)).first():
            return

        await self.process_commands(message, local_time=local)

        oshit = self.cdm.get_cooldown('oshit')
        channel = message.channel
        if oshit and oshit.trigger(False) and message.content.lower().strip() == 'o shit':
            msg = 'waddup'
            try:
                await channel.send(msg)
            except discord.HTTPException:
                return

            try:
                await self.wait_for('message', timeout=12, check=lambda m: m.author == message.author and m.content == 'here come')
            except asyncio.TimeoutError:
                await channel.send(':(')
            else:
                await channel.send('dat boi')
            return

    async def on_guild_join(self, guild):
        terminal.info(f'Joined guild {guild.name} {guild.id}')
        if await self.dbutil.is_guild_blacklisted(guild.id):
            await guild.leave()
            return

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
        role = guild.get_role(318762162552045568)
        if not role:
            return

        name = member.name if not member.nick else member.nick
        if ord(name[0]) <= 46:
            await retry(member.add_roles, role, break_on=discord.Forbidden, reason="Wants attention")
            return True

        elif remove and role in member.roles:
            await retry(member.remove_roles, role, break_on=discord.Forbidden, reason="Doesn't want attention")
            return False

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
