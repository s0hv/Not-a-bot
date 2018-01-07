from cogs.cog import Cog
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
from bot.bot import command
from sqlalchemy.exc import SQLAlchemyError
from utils.utilities import check_user_mention


class UserSeen:
    def __init__(self, user, server_id=None):
        self.user_id = user.id
        self.username = str(user)
        self.server_id = 0 if server_id is None else server_id
        self.timestamp = datetime.utcnow()

    def __hash__(self):
        return hash((self.user_id + ' ' + str(self.server_id)))

    def __eq__(self, other):
        return self.user_id == other.user_id and self.server_id == other.server_id


class LastSeen(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._updates = {}
        self.threadpool = ThreadPoolExecutor(4)
        self._update_task = self.bot.loop.create_task(self._status_loop())
        self._update_task_checker = self.bot.loop.create_task(self._check_loop())
        self._lock = asyncio.Lock(loop=self.bot.loop)

    def save_updates(self):
        if not self._updates:
            return

        user_ids = []
        server_ids = []
        times = []
        usernames = []
        for update in self._updates.values():
            user_ids.append(int(update.user_id))
            usernames.append(update.username)
            server_ids.append(int(update.server_id))
            times.append(update.timestamp.strftime('%Y-%m-%d %H:%M:%S'))
        self._updates.clear()
        self.bot.dbutils.multiple_last_seen(user_ids, usernames, server_ids, times)

    async def _check_loop(self):
        await asyncio.sleep(60)
        if self._update_task.done():
            self._update_task = self.bot.loop.create_task(self._status_loop())
            self._lock.release()

    async def _status_loop(self):
        while True:
            await asyncio.sleep(10)

            if not self._updates:
                continue

            if self._lock.locked():
                continue

            await self._lock.acquire()
            try:
                await asyncio.shield(self.bot.loop.run_in_executor(self.threadpool, self.save_updates))
            except asyncio.CancelledError:
                return
            except asyncio.TimeoutError:
                continue
            finally:
                self._lock.release()

    @staticmethod
    def status_changed(before, after):
        if before.status != after.status:
            return True

        if getattr(before.game, 'name', None) != getattr(after.game, 'name', None):
            return True

    async def on_message(self, message):
        server = None if not message.server else message.server.id
        o = UserSeen(message.author, server)
        self._updates[o] = o

    async def on_member_update(self, before, after):
        if self.status_changed(before, after):
            o = UserSeen(after, None)
            self._updates[o] = o
            return


def setup(bot):
    bot.add_cog(LastSeen(bot))
