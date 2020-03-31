import asyncio
import logging
import random
from datetime import timedelta, datetime

import discord
from asyncpg.exceptions import IntegrityConstraintViolationError
from discord.ext.commands import is_owner
from discord.ext.tasks import Loop

from bot.bot import command
from cogs.cog import Cog
from utils.utilities import call_later

logger = logging.getLogger('terminal')


class Status:
    INFECTED = None
    RECOVERED = True
    DEAD = False


class User:
    def __init__(self, user, last_activity):
        self.user = user
        self.last_activity = last_activity

    def __eq__(self, other):
        if isinstance(other, User):
            return self.user == other.user

        return other == self.user


class AprilFools(Cog):
    INFECTION_RATE = 0.08
    SPAM_RATE = 0.03
    DEATH_RATE = 0.1
    RECOVERY_RATE = 0.03
    USER_COUNT = 5
    INFECTION_DURATION_MAX = 60*120
    INFECTION_DURATION_MIN = 60*60
    RANDOM_INFECTION_INTERVAL = 60*30

    def __init__(self, bot):
        super().__init__(bot)
        self.latest_channel_users = {}
        self._dead_role = 355372853681455114 if bot.test_mode else 694607122779865250
        self._recovered_role = 355372865693941770 if bot.test_mode else 694607139125330084

        self._recovered_channel = 354712220761980939 if bot.test_mode else 694606329964134551
        self._dead_channel = 354712220761980939 if bot.test_mode else 694606372813406369

        self._guild = 353927534439825429 if bot.test_mode else 217677285442977792
        self._infected = {}
        self._infected_durations = {}
        self._process_infected = None
        self._random_infect = Loop(self.random_infect, seconds=0, minutes=0,
                                   hours=0, count=None, reconnect=True,
                                   loop=self.bot.loop)
        asyncio.run_coroutine_threadsafe(self.cache_infected(), bot.loop).result()

    def cog_unload(self):
        async def cancel():
            if self._process_infected:
                self._process_infected.cancel()
            self._random_infect.cancel()

        asyncio.run_coroutine_threadsafe(cancel(), self.bot.loop)

    async def random_infect(self):
        await asyncio.sleep(self.RANDOM_INFECTION_INTERVAL)

        def f(u):
            return u.id not in self._infected

        m = random.choice(map(f, self.bot.get_guild(self._guild).members))
        await self.add_infected(m.id)

    async def cache_infected(self):
        try:
            self._random_infect.start()
        except RuntimeError:
            pass

        rows = await self.bot.dbutil.fetch("SELECT uid, status, infected_at "
                                           'FROM infections')

        for row in rows:
            if row['status'] == Status.INFECTED and (datetime.utcnow() - row['infected_at']).total_seconds() > self.INFECTION_DURATION_MAX:
                await self.recover(row['uid'])
                continue

            self._infected[row['uid']] = row['status']
            if row['status'] == Status.INFECTED:
                self._infected_durations[row['uid']] = row['infected_at']

        await self.process_infected()

    @Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.message_id != 561980345239601173:
            return

        guild = self.bot.get_guild(217677285442977792)
        r = guild.get_role(694607094439215195)
        m = guild.get_member(payload.user_id)
        if not m:
            return

        if r in m.roles:
            return

        try:
            await m.add_roles(r)
        except discord.HTTPException:
            pass

    async def add_infected(self, uid):
        try:
            await self.bot.dbutil.execute('INSERT INTO infections (uid, status, infected_at) VALUES ($1, NULL, $2)',
                                          (uid, datetime.utcnow()))
        except IntegrityConstraintViolationError:
            return

        logger.debug(f'Set status of {uid} to infected')
        self._infected[uid] = Status.INFECTED
        self._infected_durations[uid] = datetime.utcnow()

    async def process_infected(self):
        try:
            rows = await self.bot.dbutil.fetch("SELECT uid "
                                               "FROM infections "
                                               "WHERE status IS NULL AND LOCALTIME - infected_at > $1",
                                            (timedelta(seconds=self.INFECTION_DURATION_MAX),))

            for row in rows:
                await self.recover(row['uid'])

            row = await self.bot.dbutil.fetch("SELECT MIN(LOCALTIME - infected_at) as min FROM infections WHERE status IS NULL", fetchmany=False)
        except:
            row = None

        if not row or row['min'] is None:
            self._process_infected = call_later(self.process_infected, self.bot.loop,
                                                self.INFECTION_DURATION_MAX)

        else:
            self._process_infected = call_later(self.process_infected, self.bot.loop,
                                                row['min'].total_seconds())

    async def recover(self, uid):
        status = Status.RECOVERED
        if random.random() < self.DEATH_RATE:
            status = Status.DEAD

        logger.debug(f'Set status of {uid} to {status}')
        await self.bot.dbutil.execute('UPDATE infections SET status=$1 WHERE uid=$2', (status, uid))

        g = self.bot.get_guild(self._guild)
        member = g.get_member(uid)
        if not member:
            return

        roles = member.roles
        if status == Status.DEAD:
            roles.append(g.get_role(self._dead_role))
            await member.edit(roles=roles)
            c = g.get_channel(self._dead_channel)
            await c.send(f'{member.mention} has died')
        else:
            roles.append(g.get_role(self._recovered_role))
            await member.edit(roles=roles)
            c = g.get_channel(self._recovered_channel)
            await c.send(f'{member.mention} has recovered')

        self._infected_durations.pop(uid, None)

    @is_owner()
    @command()
    async def infect(self, ctx, user: discord.Member):
        await self.add_infected(user.id)
        await ctx.send(':ok_hand:')

    @command()
    @is_owner()
    async def create_perms(self, ctx):
        guild = ctx.guild

        await guild.get_channel(694606250830331935).set_permissions(guild.default_role, read_messages=True)

        for c in guild.categories:
            if c.id not in (360692585687285761,):
                continue

            for cc in c.channels:
                await cc.set_permissions(guild.default_role, read_messages=False)

        chn = [484450452243742720, 384422173462364163, 509462073432997890]
        for c in chn:
            await guild.get_channel(c).set_permissions(guild.default_role, read_messages=False)

    @Cog.listener()
    async def on_message(self, msg):
        if not msg.guild or msg.guild.id not in (353927534439825429, 217677285442977792) or msg.webhook_id or msg.type != discord.MessageType.default:
            return

        latest_users = self.latest_channel_users.get(msg.channel.id)
        if not latest_users:
            latest_users = []
            self.latest_channel_users[msg.channel.id] = latest_users

        # Get the rate of infection
        rate = self.INFECTION_RATE
        user = [x for x in latest_users if x.user == msg.author]
        if user:
            # If same author sent last message decrease rates
            if latest_users[-1] == msg.author:
                rate = self.SPAM_RATE

            latest_users.remove(user[0])

        # don't insert bot at the end or it'll be immediately removed
        if msg.author.bot:
            latest_users.insert(1, User(msg.author, msg.created_at))
        else:
            latest_users.append(User(msg.author, msg.created_at))

        # If over user count remove last user
        if len(latest_users) > self.USER_COUNT:
            latest_users.pop(0)

        for u in filter(lambda u: (datetime.utcnow() - u.last_activity).total_seconds() > 300, latest_users.copy()):
            latest_users.remove(u)

        has_infection = [u for u in latest_users if self._infected.get(u.user.id, 0) == Status.INFECTED]
        if not has_infection:
            return

        for u in latest_users:
            u = u.user
            infected = self._infected.get(u.id, 'a')
            if infected == 'a':
                if random.random() < rate:
                    await self.add_infected(u.id)

            elif infected == Status.INFECTED:
                dur = datetime.utcnow() - self._infected_durations.get(u.id, datetime.utcnow())
                if dur.total_seconds() < self.INFECTION_DURATION_MIN:
                    continue

                # Reduce recovery rate when sending multiple messages in a row
                rate = self.RECOVERY_RATE if rate == self.INFECTION_RATE else self.RECOVERY_RATE / 4

                if random.random() < rate:
                    await self.recover(u.id)


def setup(bot):
    bot.add_cog(AprilFools(bot))
