import logging
from typing import TYPE_CHECKING

try:
    from sanic import Sanic
    from sanic.response import text
except ModuleNotFoundError:
    Sanic = None
    text = None

if TYPE_CHECKING:
    from bot.botbase import BotBase


logger = logging.getLogger('terminal')


class WebhookServer:
    def __init__(self, bot: 'BotBase', listeners=None):
        if not Sanic:
            self._listeners = set()
            logger.info('Sanic not installed. Webhook not initialized')
            return

        app = Sanic(name='webhook', configure_logging=bot.test_mode)
        self.bot = bot
        self._listeners = set() if not listeners else set(listeners)

        @app.route('/webhook', methods=['POST'])
        async def webhook(request):
            if request.headers.get('Authorization', None) != self.bot.config.dbl_auth:
                logger.warning('Unauthorized webhook access')
                return text('OK')

            try:
                for listener in self._listeners:
                    await listener(request.json)
            except:
                logger.exception('Failed to process vote')

            return text('OK')

        self._server = None
        self._app = app

    async def create_server(self):
        bot = self.bot
        self._server = await self._app.create_server(
            bot.config.dbl_host,
            bot.config.dbl_port,
            debug=bot.test_mode,
            return_asyncio_server=True)
        await self._server.startup()


    def add_listener(self, listener):
        self._listeners.add(listener)

    def remove_listener(self, listener):
        self._listeners.discard(listener)
