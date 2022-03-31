import asyncio
import logging
import math
import random
from asyncio.locks import Lock
from datetime import timedelta, datetime
from typing import Union, Optional

import discord
from discord.ext.commands import is_owner, Greedy
from discord.ext.commands.cooldowns import CooldownMapping, BucketType
from numpy.random import choice

from bot.bot import command
from bot.commands import cooldown
from bot.converters import TimeDelta
from cogs.cog import Cog
from cogs.moderator import Moderator
from utils.utilities import call_later

logger = logging.getLogger('terminal')


class PointSpawn:
    def __init__(self, amount: int, msg: discord.Message):
        self.amount = amount
        self.msg = msg


class BattleArena(Cog):
    SPAWN_RATE = 0.1
    MINIMUM_SPAWN_TIME = timedelta(minutes=2)

    def __init__(self, bot):
        super().__init__(bot)
        self._penalty_role = 355372880898424832 if bot.test_mode else 959150196435075072
        self._battle_channel = 354712220761980939 if bot.test_mode else 297061271205838848

        self._guild = 353927534439825429 if bot.test_mode else 217677285442977792

        self._spawn_rate = self.SPAWN_RATE
        self._min_spawn_time = self.MINIMUM_SPAWN_TIME
        self._message_ratelimit = CooldownMapping.from_cooldown(1, self._min_spawn_time.total_seconds(), BucketType.guild)

        self._members = set()

        self._active_spawn: Optional[PointSpawn] = None
        self._claim_lock = Lock(loop=self.bot.loop)
        self._protects = {}

        asyncio.run_coroutine_threadsafe(self.load_users(), loop=self.bot.loop)

    def cog_unload(self):
        for v in self._protects.values():
            v.cancel()

    def get_guild(self) -> discord.Guild:
        return self.bot.get_guild(self._guild)

    async def load_users(self):
        users = await self.bot.dbutil.get_event_users()

        for user in users:
            protected = user['protected_until']
            if protected and protected > datetime.utcnow():
                self.add_protect(user['uid'], (protected - datetime.utcnow()).total_seconds())

            self._members.add(user['uid'])

    async def cog_check(self, ctx):
        if not ctx.guild or ctx.guild.id != self._guild:
            return False

        if ctx.command.name == 'join_event':
            return True

        if not self.is_participating(ctx.author):
            await ctx.send(f'You must join the event with `{ctx.prefix}join_event` to use event commands.')
            return False

        return True

    def is_participating(self, user: Union[discord.User, int, discord.Member]):
        uid = user if isinstance(user, int) else user.id

        return uid in self._members

    def get_mute_role(self) -> discord.Role:
        return self.bot.get_guild(self._guild).get_role(self._penalty_role)

    async def remove_temprole(self, user: discord.Member):
        uid = user.id
        temproles = self.bot.temproles.get(self._guild, {}).get(uid, {})

        task = temproles.get(self._penalty_role)
        if task:
            task.cancel()

        await self.bot.dbutil.remove_temprole(uid, self._penalty_role)
        try:
            await user.remove_roles(self.get_mute_role())
        except:
            logger.exception('Failed to remove silence')
            raise

    def temprole_duration_left(self, uid: int) -> timedelta:
        temproles = self.bot.temproles.get(self._guild, {}).get(uid, {})

        task = temproles.get(self._penalty_role)
        td = task.runs_at - datetime.utcnow()
        return td

    async def timeout(self, ctx, user: discord.Member, time: timedelta,
                      reason: str, ignore_protect: bool = False) -> bool:
        moderator: Moderator = self.bot.get_cog('Moderator')

        if not ignore_protect and user.id in self._protects:
            await self.remove_protect(user.id)
            await ctx.send(f'{user.mention} protected themselves')
            return False

        try:
            await user.add_roles(self.get_mute_role(), reason=reason)
        except:
            logger.exception('Failed to add event mute role')

        moderator.register_temprole(user.id, self._penalty_role,
                                    ctx.guild.id, time.total_seconds(), force_save=True)
        await self.bot.dbutil.add_temprole(user.id, self._penalty_role, user.guild.id,
                                           datetime.utcnow() + time)
        return True

    async def has_required_points(self, ctx, cmd: str, cost: int):
        points = await self.bot.dbutil.get_event_points(ctx.author.id)
        if points < cost:
            await ctx.send(f'{cmd.capitalize()} costs {cost} point(s) but you have only {points} point(s)')
            return False

        return True

    async def can_affect(self, ctx, author: discord.Member, user: discord.Member):
        retval = self.is_participating(author) and self.is_participating(user)
        if not retval:
            await ctx.send('User must be participating in the event')

        return retval

    def is_unmuted(self, user: discord.Member):
        return self.get_mute_role() not in user.roles

    async def remove_protect(self, uid: int):
        task = self._protects.pop(uid, None)
        if task:
            task.cancel()

        await self.bot.dbutil.update_user_protect(uid)

    @staticmethod
    def random_timedelta(lower: timedelta, upper: timedelta) -> timedelta:
        return timedelta(seconds=random.randint(int(lower.total_seconds()), int(upper.total_seconds())))

    @command()
    @cooldown(1, 10, BucketType.user)
    async def join_event(self, ctx):
        """
        Join the april fools event.
        """
        user = ctx.author
        if not self.is_participating(user.id):
            self._members.add(user.id)
            await self.bot.dbutil.add_event_users([user.id])
            await ctx.reply(f'Joined the event', mention_author=False)

        role_id = 355372865693941770 if self.bot.test_mode else 959146213645615154
        role = self.get_guild().get_role(role_id)
        if role in user.roles:
            await ctx.send('You already have the event role')
            return

        await user.add_roles(role)
        await ctx.send('Event role added')

    @command()
    @cooldown(1, 7, BucketType.user)
    async def collect(self, ctx):
        """
        Collect spawned points. Works in any channel
        """
        active = None
        async with self._claim_lock:
            if not self._active_spawn:
                msg = 'No active points to collect'
            else:
                # Add points to user
                points = self._active_spawn.amount
                await self.bot.dbutil.update_event_points(ctx.author.id, points)
                active = self._active_spawn

                self._active_spawn: Optional[PointSpawn] = None
                msg = f'{points} point(s) collected'

        await ctx.send(msg)

        if active:
            await active.msg.delete()

    @command()
    @cooldown(1, 1, BucketType.user)
    async def points(self, ctx):
        """
        Shows the amount of points you have
        """
        points = await self.bot.dbutil.get_event_points(ctx.author.id)
        await ctx.reply(f'You have {points or 0} points', mention_author=False)

    @command()
    @cooldown(1, 1, BucketType.user)
    async def silence(self, ctx, *, user: discord.Member):
        """
        COST 1

        Silence a user for 30 minutes
        """
        COST = 1

        if not await self.can_affect(ctx, ctx.author, user):
            return

        if not await self.has_required_points(ctx, 'silence', COST):
            return

        await self.bot.dbutil.update_event_points(ctx.author.id, -COST)
        if await self.timeout(ctx, user, timedelta(minutes=30), f'{ctx.author} silenced'):
            await ctx.send(f'Silenced {user}')

    def add_protect(self, uid: int, time_left: int):
        self._protects[uid] = call_later(self.remove_protect, self.bot.loop,
                                         time_left, uid)

    @command()
    @cooldown(1, 1, BucketType.user)
    async def protect(self, ctx):
        """
        COST 1

        Protect yourself from the next silence targeted on you.
        Lasts until targeted or after 1 hour
        """
        COST = 1
        uid = ctx.author.id

        if not await self.has_required_points(ctx, 'protect', COST):
            return

        if uid in self._protects:
            await ctx.send('Already protected')
            return

        td = timedelta(hours=1)
        self.add_protect(uid, int(td.total_seconds()))
        await self.bot.dbutil.update_user_protect(uid, datetime.utcnow() + td)
        await self.bot.dbutil.update_event_points(uid, -COST)
        await ctx.send('Protected yourself for 1 hour or until the next silence attempt')

    @command()
    @cooldown(1, 1, BucketType.user)
    async def unsilence(self, ctx):
        """
        COST 2

        Remove an active silence on you if it's under 1 hour long
        """
        COST = 2
        author = ctx.author
        uid = author.id

        if not await self.has_required_points(ctx, 'unsilence', COST):
            return

        if self.is_unmuted(author):
            await ctx.send('You are not silenced at the moment')
            return

        if self.temprole_duration_left(uid) > timedelta(hours=1):
            await ctx.send('Over 1h left of silence. Cannot unsilence')
            return

        await self.bot.dbutil.update_event_points(uid, -COST)
        await self.remove_temprole(author)
        await ctx.reply('Unsilenced', mention_author=False)

    @command()
    @cooldown(1, 2, BucketType.user)
    async def force_unsilence(self, ctx):
        """
        COST 2 + silence hours left * 2

        Remove an active silence on you
        """
        author = ctx.author
        uid = author.id

        if self.is_unmuted(author):
            await ctx.send('You are not silenced at the moment')
            return

        COST = 2 + math.ceil(2 * self.temprole_duration_left(uid).total_seconds() / 3600)

        if not await self.has_required_points(ctx, 'force_unsilence', COST):
            return

        await self.bot.dbutil.update_event_points(uid, -COST)
        await self.remove_temprole(author)
        await ctx.reply('Unsilenced', mention_author=False)

    @command()
    @cooldown(1, 2, BucketType.user)
    async def rng_pls(self, ctx, *, user: discord.Member):
        """
        COST 2

        Silences the given user for 0.5-2h.
        Rarely silences the caller instead of the target
        """
        COST = 2

        if not await self.can_affect(ctx, ctx.author, user):
            return

        if random.random() < 0.08:
            user = ctx.author

        if not await self.has_required_points(ctx, 'rng_pls', COST):
            return

        td = self.random_timedelta(timedelta(minutes=30), timedelta(hours=2))
        await self.bot.dbutil.update_event_points(ctx.author.id, -COST)
        if await self.timeout(ctx, user, td, f'{ctx.author} silenced'):
            await ctx.send(f'Silenced {user}')

    @command()
    @cooldown(1, 1, BucketType.user)
    async def selfdestruct(self, ctx, users: Greedy[discord.Member], *, time: TimeDelta):
        """
        COST: 3

        Times out a maximum of 4 users for the given time,
        while timing you out for `time*amount of enemies timed out`.
        Max time is 1h

        Usage:
        {prefix}{name} @user @user2 10m
        """
        COST = 3

        if time > timedelta(hours=1):
            await ctx.send('1 hour max')
            return

        author = ctx.author

        if not self.is_unmuted(author):
            await ctx.send('You are already silenced')
            return

        # Filter out duplicates and users that are not participating
        users = list(set(filter(self.is_unmuted, filter(self.is_participating, users))))
        if len(users) > 4:
            await ctx.send(f'Tried to silence {len(users)}>4 users. Try again with 4 or less users.')
            return

        if not users:
            await ctx.send('None of the mentioned users were participating in the event or they were already silenced')
            return

        if not await self.has_required_points(ctx, 'selfdestruct', COST):
            return

        await self.bot.dbutil.update_event_points(author.id, -COST)

        reason = f'{author} self destructed'
        timeouted_users = []
        timeouts = 0
        for user in users:
            try:
                if await self.timeout(ctx, user, time, reason):
                    timeouted_users.append(user)

                timeouts += 1
            except:
                logger.exception('fail selfdestruct')
                await ctx.send(f'Failed to silence {user}')

        await self.timeout(ctx, author, time*timeouts, reason, ignore_protect=True)

        if timeouts == 0:
            await self.bot.dbutil.update_event_points(author.id, 3)
            await ctx.send('Failed to silence anyone. Points refunded')
            return

        if len(timeouted_users) == 1:
            users_str = timeouted_users[0].mention
        elif len(timeouted_users) == 0:
            users_str = 'no one'
        else:
            users_str = f'{", ".join(map(discord.Member.mention.fget, timeouted_users[:-1]))} and {timeouted_users[-1].mention}'

        await ctx.send(f'{author.mention} self destructs and takes {users_str} with them.', allowed_mentions=discord.AllowedMentions.none())

    @is_owner()
    @command(aliases=['set_sd'])
    async def set_spawn_delay(self, ctx, *, spawn_time: TimeDelta):
        """
        Set minimum time between 2 spawns
        """
        self._min_spawn_time = spawn_time
        self._message_ratelimit = CooldownMapping.from_cooldown(1, self._min_spawn_time.total_seconds(), BucketType.guild)
        await ctx.send(':ok_hand:')

    @is_owner()
    @command(name='spawn_points', aliases=['spawnp'])
    async def spawn_points(self, _):
        await self.do_spawn()

    @command()
    @is_owner()
    async def create_perms(self, ctx):
        pass

    @staticmethod
    def get_random_point_amount() -> int:
        return choice([1, 2, 3], 1, p=[0.7, 0.2, 0.1])[0]

    async def do_spawn(self):
        chn = self.get_guild().get_channel(self._battle_channel)
        amount = self.get_random_point_amount()

        embed = discord.Embed(
            title='Event points',
            description=f'{amount} point(s) spawned. Use `!collect` to collect them.'
        )

        self._active_spawn = PointSpawn(amount, await chn.send(embed=embed))

    @Cog.listener()
    async def on_message(self, msg):
        if not msg.guild or msg.guild.id != self._guild or msg.webhook_id or msg.type != discord.MessageType.default:
            return

        if not self._message_ratelimit.valid:
            return

        bucket = self._message_ratelimit.get_bucket(msg)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            return

        # If no spawn reset cooldown
        if random.random() > self.SPAWN_RATE:
            bucket.reset()
            return

        await self.do_spawn()


def setup(bot):
    bot.add_cog(BattleArena(bot))
