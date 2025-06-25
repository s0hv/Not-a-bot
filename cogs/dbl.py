import asyncio
import logging
import os
from datetime import timedelta

import aiohttp

from cogs.cog import Cog

logger = logging.getLogger('terminal')

topgg_api = 'https://top.gg/api/bots'


class DBApi(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot.server.add_listener(self.on_vote)
        self._token = self.bot.config.dbl_token
        self.update_task = None

    async def cog_load(self):
        await super().cog_load()
        if not self.bot.test_mode:
            await self._thread_safe_init()

    async def _thread_safe_init(self):
        self.update_task = self.bot.loop.create_task(self.update_stats())

    async def on_vote(self, json):
        s = f'<@{json["user"]}> voted for <@{json["bot"]}>'
        json = {'content': s}
        headers = {'Content-type': 'application/json'}
        async with aiohttp.ClientSession() as client:
            await client.post(self.bot.config.dbl_webhook, json=json, headers=headers)

    async def do_request(self, client, endpoint, method, payload=None):
        headers = {
            "Content-Type": "application/json",
            "Authorization": self._token,
        }
        return await client.request(
            method,
            f'{topgg_api}/{endpoint}',
            json=payload,
            headers=headers
        )

    async def post_guild_count(self, *, guild_count: int):
        async with aiohttp.ClientSession() as client:
            return await self.do_request(
                client,
                f'{self.bot.user.id}/stats',
                'GET',
                {'server_count': guild_count})

    async def get_bot_info(self):
        async with aiohttp.ClientSession() as client:
            res = await self.do_request(
                client,
                f'{self.bot.user.id}',
                'GET'
            )
            content = await res.json()
            return content

    async def _thread_safe_stop(self):
        if self.update_task:
            self.update_task.cancel()

    def cog_unload(self):
        self.bot.server.remove_listener(self.on_vote)
        self.bot.loop.create_task(self._thread_safe_stop())

    async def update_stats(self):
        while True:
            await asyncio.sleep(3600)
            logger.info('Posting server count')
            try:
                await self.post_guild_count(guild_count=len(self.bot.guilds))
                logger.info(f'Posted server count {len(self.bot.guilds)}')
            except aiohttp.ClientResponseError as e:
                if e.status >= 500:
                    return
                logger.exception(f'Failed to post server count\n{e}')
                return
            except Exception as e:
                logger.exception(f'Failed to post server count\n{e}')

            await self._check_votes()

    async def _check_votes(self):
        try:
            bot_info = await self.get_bot_info()
        except aiohttp.ClientResponseError as e:
            if e.status >= 500:
                return
            logger.exception(f'Failed to get bot info\n{e}')
            return
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
