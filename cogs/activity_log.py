import asyncio
from datetime import datetime

from discord.activity import ActivityType

from cogs.cog import Cog


class ActivityLog(Cog):
    def __init__(self, bot):
        super(ActivityLog, self).__init__(bot)
        self._db_queue = []
        self._update_task = asyncio.run_coroutine_threadsafe(self._game_loop(), loop=bot.loop)
        self._update_task_checker = asyncio.run_coroutine_threadsafe(self._check_loop(), loop=bot.loop)

    async def add_game_time(self):
        if not self._db_queue:
            return

        q = self._db_queue
        self._db_queue = []
        await self.bot.dbutils.add_multiple_activities(q)
        del q

    async def _game_loop(self):
        while True:
            await asyncio.sleep(10)

            if not self._db_queue:
                continue

            try:
                await asyncio.shield(self.add_game_time())
            except asyncio.CancelledError:
                return
            except asyncio.TimeoutError:
                continue

    async def _check_loop(self):
        await asyncio.sleep(120)
        if self._update_task.done():
            self._update_task = self.bot.loop.create_task(self._game_loop())

    @staticmethod
    def status_changed(before, after):
        if before.activity and before.activity.type == ActivityType.playing and after.activity is None:
            return True

        return False

    async def on_member_update(self, before, after):
        if self.status_changed(before, after):
            self._db_queue.append({'user': after.id,
                                   'time': (datetime.utcnow() - before.activity.start).seconds,
                                   'game': before.activity.name})


def setup(bot):
    bot.add_cog(ActivityLog(bot))
