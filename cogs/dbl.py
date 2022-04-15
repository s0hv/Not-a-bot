import asyncio
import logging
import os
from datetime import timedelta
from typing import Optional

import aiohttp
import topgg

from cogs.cog import Cog

logger = logging.getLogger('terminal')


class DBApi(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot.server.add_listener(self.on_vote)
        self._token = self.bot.config.dbl_token
        self.update_task = None
        self.dbl: Optional[topgg.DBLClient] = None

    async def cog_load(self):
        await super().cog_load()
        if not self.bot.test_mode:
            await self._thread_safe_init()

    async def _thread_safe_init(self):
        self.dbl = topgg.DBLClient(self._token)
        self.update_task = self.bot.loop.create_task(self.update_stats())

    async def on_vote(self, json):
        s = f'<@{json["user"]}> voted for <@{json["bot"]}>'
        json = {'content': s}
        headers = {'Content-type': 'application/json'}
        async with aiohttp.ClientSession() as client:
            await client.post(self.bot.config.dbl_webhook, json=json, headers=headers)

    async def _thread_safe_stop(self):
        if self.update_task:
            self.update_task.cancel()
        if self.dbl:
            task = self.bot.loop.create_task(self.dbl.close())
            try:
                await asyncio.wait_for(task, 20)
            except (asyncio.CancelledError, asyncio.InvalidStateError,
                    asyncio.TimeoutError):
                return

    def cog_unload(self):
        self.bot.server.remove_listener(self.on_vote)
        self.bot.loop.create_task(self._thread_safe_stop())

    async def update_stats(self):
        while True:
            await asyncio.sleep(3600)
            logger.info('Posting server count')
            try:
                await self.dbl.post_guild_count(guild_count=len(self.bot.guilds))
                logger.info(f'Posted server count {len(self.bot.guilds)}')
            except topgg.ServerError:
                pass
            except Exception as e:
                logger.exception(f'Failed to post server count\n{e}')

            await self._check_votes()

    async def _check_votes(self):
        try:
            bot_info = await self.dbl.get_bot_info(self.bot.user.id)
        except Exception as e:
            logger.exception(f'Failed to get bot info\n{e}')
            return

        server_specific = self.bot.get_cog('ServerSpecific')
        if not server_specific:
            return

        channel = self.bot.get_channel(339517543989379092)
        if not channel:
            return

        with open(os.path.join(os.getcwd(), 'data', 'votes.txt'), 'r') as f:
            old_votes = int(f.read().strip(' \n\r\t'))

        points = bot_info.points
        new_votes = points - old_votes
        new_giveaways = new_votes // 20
        if not new_giveaways:
            return

        with open(os.path.join(os.getcwd(), 'data', 'votes.txt'), 'w') as f:
            f.write(str(points - points % 20))

        await server_specific._toggle_every(channel, new_giveaways * 5, timedelta(days=1))


def setup(bot):
    bot.add_cog(DBApi(bot))
