import asyncio
import re

from cogs.cog import Cog
from utils import unzalgo


class R9K(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._messages = []
        self._update_task = asyncio.run_coroutine_threadsafe(self._update_loop(), loop=bot.loop)
        self.emote_regex = re.compile(r'<:(\w+):\d+>')

    def cog_unload(self):
        self._update_task.cancel()
        try:
            self._update_task.result(timeout=20)
        except (TimeoutError, asyncio.CancelledError):
            pass

    async def _update_loop(self):
        while True:
            if not self._messages:
                await asyncio.sleep(10)
                continue

            messages = self._messages
            self._messages = []

            try:
                sql = 'INSERT INTO r9k (message) VALUES ($1) ON CONFLICT DO NOTHING'
                await self.bot.dbutil.execute(sql, messages)
            except:
                pass

            await asyncio.sleep(10)

    @Cog.listener()
    async def on_message(self, msg):
        if msg.channel.id != 297061271205838848:
            return

        # Don't wanna log bot messages
        if msg.author.bot:
            return

        # Gets the content like you see in the client
        content = msg.clean_content

        # Remove zalgo text
        content = unzalgo.unzalgo(content)
        content = self.emote_regex.sub(r'\1', content)

        self._messages.append(content)
        if self._update_task.done():
            self._update_task = asyncio.run_coroutine_threadsafe(self._update_loop(), loop=self.bot.loop)


def setup(bot):
    bot.add_cog(R9K(bot))
