import asyncio
import logging
import re
from asyncio import Queue, QueueEmpty
from datetime import timedelta

from disnake.errors import HTTPException
from disnake.ext.commands.cooldowns import CooldownMapping, BucketType
from disnake.ext.tasks import Loop

from cogs.cog import Cog
from utils import unzalgo
from utils.utilities import utcnow

logger = logging.getLogger('terminal')


class DeleteQueue:
    """
    Class that is used to delete messages in chunks.
    """
    def __init__(self, loop, seconds=5, minutes=0, hours=0):
        self._loop = loop
        self._messages = Queue(loop=loop)
        self._delete_task = Loop(self._delete_task, seconds=seconds,
                                 minutes=minutes, hours=hours,
                                 reconnect=True, count=None, loop=loop)

    async def start(self):
        self._delete_task.start()

    async def stop(self):
        self._delete_task.cancel()

    def put(self, msg):
        self._messages.put_nowait(msg)

    async def _delete_task(self):
        try:
            msg = await self._messages.get()
        except asyncio.CancelledError:
            return

        messages = {msg.channel: [msg]}
        while not self._messages.empty():
            try:
                message = self._messages.get_nowait()
                ch = message.channel
                if ch in messages:
                    messages[ch].append(message)
                else:
                    messages[ch] = [message]

            except QueueEmpty:
                break

        for ch, msgs in messages.items():
            await ch.delete_messages(msgs)


class R9K(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._messages = []
        self.emote_regex = re.compile(r'<:(\w+):\d+>')
        self._cooldown = CooldownMapping.from_cooldown(3, 8, BucketType.user)
        self._delete_queue = DeleteQueue(bot.loop)
        # We Loop.start uses a non thread-safe operation so we need to run it thread-safe
        asyncio.run_coroutine_threadsafe(self._delete_queue.start(), loop=bot.loop).result()

    def cog_unload(self):
        try:
            asyncio.run_coroutine_threadsafe(self._delete_queue.stop(), loop=self.bot.loop).result(10)
        except asyncio.TimeoutError:
            pass

    @Cog.listener()
    async def on_message(self, msg):
        guild = msg.guild
        if self.bot.test_mode:
            if msg.channel.id != 354712220761980939:
                return
        elif not guild or guild.id != 217677285442977792:
            return

        # get-rekt
        if msg.channel.id == 322839372913311744:
            return

        # Don't wanna log bot messages
        if msg.author.bot:
            return

        # Gets the content like you see in the client
        content = msg.clean_content

        # Remove zalgo text
        content = unzalgo.unzalgo(content)
        content = self.emote_regex.sub(r'\1', content)
        content = content.replace('\u200d', '').replace('\u200b', '').replace('  ', ' ')
        content = content.strip(' \n_*`\'"´~')

        # All values will be indexed in lowercase
        sql = 'INSERT INTO r9k (message) VALUES ($1) ON CONFLICT DO NOTHING RETURNING 1'
        row = await self.bot.dbutil.fetch(sql, (content,), fetchmany=False)
        if row is None:
            self._delete_queue.put(msg)
            if not self._cooldown.valid:
                return

            bucket = self._cooldown.get_bucket(msg)
            retry_after = bucket.update_rate_limit()
            if not retry_after:
                return

            moderator = self.bot.get_cog('Moderator')
            if not moderator:
                return

            mute_role = guild.get_role(self.bot.guild_cache.mute_role(guild.id))
            if not mute_role:
                return

            try:
                await msg.author.add_roles(mute_role, reason=f'r9k violation')
            except HTTPException:
                logger.exception('Failed to mute for r9k violation')
                return

            time = timedelta(minutes=5)
            await moderator.add_timeout(
                await self.bot.get_context(msg), guild.id, msg.author.id,
                utcnow() + time,
                time.total_seconds(),
                reason='Violated r9k',
                author=guild.me,
                modlog_msg=None,
                show_in_logs=False)


def setup(bot):
    bot.add_cog(R9K(bot))
