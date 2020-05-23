import asyncio
from datetime import datetime

import discord

from cogs.cog import Cog


class UserSeen:
    def __init__(self, user, guild_id=None):
        self.user_id = user.id
        self.username = str(user)
        self.guild_id = 0 if guild_id is None else guild_id
        self.timestamp = datetime.utcnow()

    def __hash__(self):
        return hash(self.user_id)

    def __eq__(self, other):
        # Called when adding one of this object to a set
        # set compares the item already in it to the item being added
        # It does not however replace on duplicate
        # This is why we have to modify the object ourselves in case newer data is present
        eq = self.user_id == other.user_id and self.guild_id == other.guild_id
        if eq:
            self.timestamp = other.timestamp

        return eq


class LastSeen(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._updates = set()
        self._update_task = asyncio.run_coroutine_threadsafe(self._status_loop(), loop=bot.loop)
        self._update_task_checker = asyncio.run_coroutine_threadsafe(self._check_loop(), loop=bot.loop)
        self._update_now = asyncio.Event(loop=bot.loop)

    def cog_unload(self):
        self._update_task_checker.cancel()
        self.bot.loop.call_soon_threadsafe(self._update_now.set)
        try:
            self._update_task.result(timeout=20)
        except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
            self._update_task.cancel()

    async def save_updates(self):
        if not self._updates:
            return

        updates = self._updates
        self._updates = set()
        user_ids = []
        guild_ids = []
        times = []
        usernames = []
        for update in updates:
            user_ids.append(update.user_id)
            usernames.append(update.username)
            guild_ids.append(update.guild_id)
            times.append(update.timestamp)
        await self.bot.dbutils.multiple_last_seen(user_ids, usernames, guild_ids, times)
        del updates

    async def _check_loop(self):
        await asyncio.sleep(120)
        if self._update_task.done():
            self._update_task = self.bot.loop.create_task(self._status_loop())

    async def _status_loop(self):
        while not self._update_now.is_set():
            try:
                await asyncio.wait_for(self._update_now.wait(), timeout=5, loop=self.bot.loop)
            except asyncio.TimeoutError:
                pass

            if not self._updates:
                continue

            await self.save_updates()

    @staticmethod
    def status_changed(before, after):
        if before.status != after.status:
            return True

        try:
            if before.activity != after.activity:
                return True

        # KeyError is raised when activity start time doesn't exist
        except KeyError:
            pass

        if before.nick != after.nick:
            return True

        if before.avatar != after.avatar:
            return False

    @staticmethod
    def get_guild(user):
        if isinstance(user, discord.user.BaseUser):
            return None
        else:
            return user.guild.id

    @Cog.listener()
    async def on_message(self, message):
        guild = self.get_guild(message.author)
        o = UserSeen(message.author, guild)
        self._updates.add(o)

    @Cog.listener()
    async def on_member_update(self, before, after):
        if self.status_changed(before, after):
            o = UserSeen(after, None)
            self._updates.add(o)
            return

    @Cog.listener()
    async def on_reaction_add(self, _, user):
        guild = self.get_guild(user)
        o = UserSeen(user, guild)
        self._updates.add(o)

    @Cog.listener()
    async def on_member_join(self, user):
        guild = user.guild.id
        o = UserSeen(user, guild)
        self._updates.add(o)

    @Cog.listener()
    async def on_member_leave(self, user):
        guild = user.guild.id
        o = UserSeen(user, guild)
        self._updates.add(o)


def setup(bot):
    bot.add_cog(LastSeen(bot))
