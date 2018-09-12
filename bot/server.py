import asyncio
import logging

from sanic import Sanic

logger = logging.getLogger('debug')


class WebhookServer:
    def __init__(self, bot, listeners=None):
        app = Sanic()
        self.bot = bot
        self._listeners = set() if not listeners else set(listeners)

        @app.route('/webhook', methods=['POST'])
        async def webhook(request):
            if request.headers.get('Authorization', None) != self.bot.config.dbl_auth:
                logger.warning('Unauthorized webhook access')
                return

            for listener in self._listeners:
                asyncio.ensure_future(listener(request.json), loop=bot.loop)

        self._server = asyncio.run_coroutine_threadsafe(app.create_server(bot.config.dbl_host,
                                                                          bot.config.dbl_port),
                                                        bot.loop)

    def add_listener(self, listener):
        self._listeners.add(listener)

    def remove_listener(self, listener):
        self._listeners.discard(listener)

