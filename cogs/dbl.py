import dbl
from cogs.cog import Cog
import logging
import asyncio
import os
from datetime import timedelta

logger = logging.getLogger('debug')


class DBApi(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._token = self.bot.config.dbl_token
        self.dbl = dbl.Client(self.bot, self._token)
        if not self.bot.test_mode:
            self.update_task = self.bot.loop.create_task(self.update_stats())

    async def update_stats(self):
        while True:
            await asyncio.sleep(3600)
            logger.info('Posting server count')
            try:
                await self.dbl.post_server_count()
                logger.info(f'Posted server count {len(self.bot.guilds)}')
            except Exception as e:
                logger.exception(f'Failed to post server count\n{e}')

            await self._check_votes()

    async def _check_votes(self):
        try:
            botinfo = await self.dbl.get_bot_info(self.bot.user.id)
        except Exception as e:
            logger.exception(f'Failed to get botinfo\n{e}')
            return

        server_specific = self.bot.get_cog('ServerSpecific')
        if not server_specific:
            return

        channel = self.bot.get_channel(339517543989379092)
        if not channel:
            return

        with open(os.path.join(os.getcwd(), 'data', 'votes.txt'), 'r') as f:
            old_votes = int(f.read().strip(' \n\r\t'))

        new_votes = botinfo['votes'] - old_votes
        new_giveaways = new_votes // 10
        if not new_giveaways:
            return

        with open(os.path.join(os.getcwd(), 'data', 'votes.txt'), 'w') as f:
            f.write(str(botinfo['votes'] - botinfo['votes'] % 10))

        await server_specific._toggle_every(channel, new_giveaways, timedelta(days=1))


def setup(bot):
    bot.add_cog(DBApi(bot))
