import asyncio
from datetime import datetime

from cogs.cog import Cog


class UserSeen:
    def __init__(self, user, guild_id=None):
        self.user_id = user.id
        self.username = str(user)
        self.guild_id = 0 if guild_id is None else guild_id
        self.timestamp = datetime.utcnow()


class LastSeen(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._updates = set()
        self._update_task = asyncio.run_coroutine_threadsafe(self._status_loop(), loop=bot.loop)
        self._update_task_checker = asyncio.run_coroutine_threadsafe(self._check_loop(), loop=bot.loop)

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
            times.append(update.timestamp.strftime('%Y-%m-%d %H:%M:%S'))
        await self.bot.dbutils.multiple_last_seen(user_ids, usernames, guild_ids, times)
        del updates

    async def _check_loop(self):
        await asyncio.sleep(120)
        if self._update_task.done():
            self._update_task = self.bot.loop.create_task(self._status_loop())

    async def _status_loop(self):
        while True:
            await asyncio.sleep(10)

            if not self._updates:
                continue

            try:
                await asyncio.shield(self.save_updates())
            except asyncio.CancelledError:
                return
            except asyncio.TimeoutError:
                continue

    @staticmethod
    def status_changed(before, after):
        if before.status != after.status:
            return True

        if before.activity != after.activity:
            return True

    async def on_message(self, message):
        guild = None if not message.guild else message.guild.id
        o = UserSeen(message.author, guild)
        self._updates.add(o)

    async def on_member_update(self, before, after):
        if self.status_changed(before, after):
            o = UserSeen(after, None)
            self._updates.add(o)
            return

    async def on_reaction_add(self, reaction, user):
        guild = None if not user.guild else user.guild.id
        o = UserSeen(user, guild)
        self._updates.add(o)


def setup(bot):
    bot.add_cog(LastSeen(bot))
