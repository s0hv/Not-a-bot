import dbl
from cogs.cog import Cog
import logging
import asyncio
from threading import Thread

logger = logging.getLogger('debug')


class DBApi(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._token = self.bot.config.dbl_token
        self.dbl = dbl.Client(self.bot, self._token)
        if not self.bot.test_mode:
            self.update_task = self.bot.loop.create_task(self.update_stats())
            self.server = Thread(target=self.run_webhook_server, args=(self.bot.loop,))
            self.server.start()

    async def update_stats(self):
        while True:
            await asyncio.sleep(3600)
            logger.info('Posting server count')
            try:
                await self.dbl.post_server_count()
                logger.info(f'Posted server count {len(self.bot.guilds)}')
            except Exception as e:
                logger.exception(f'Failed to post server count\n{e}')

    def run_webhook_server(self, main_loop):
        try:
            from sanic import Sanic
            from sanic.response import json
        except ImportError:
            logger.warning('Sanic not found. Webhook server not started')
            return

        loop = asyncio.new_event_loop()
        app = Sanic()

        @app.route("/webhook", methods=["POST", ])
        async def webhook(request):
            if request.headers.get('Authorization') != self.bot.config.dbl_auth:
                logger.warning('Unauthorized webhook access')
                return

            js = request.json
            main_loop.create_task(self.on_vote(int(js['bot']),
                                               int(js['user']),
                                               js['type'],
                                               js['isWeekend']))

            return json({'a': 'a'}, status=200)

        logger.info(f'Starting webhook server {self.bot.config.dbl_server} on the port {self.bot.config.dbl_port}')
        fut = asyncio.run_coroutine_threadsafe(app.create_server(host=self.bot.config.dbl_server, port=self.bot.config.dbl_port), loop=loop)
        loop.run_until_complete(fut)

    async def on_vote(self, bot: int, user: int, type: str, is_weekend: bool):
        print(f'{user} voted on bot {bot}')


def setup(bot):
    bot.add_cog(DBApi(bot))
