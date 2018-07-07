import re

from cogs.cog import Cog

r = re.compile('(?:^| )billy(?: |$)')


class Autoresponds(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    async def on_raw_reaction_add(self, payload):
        if payload.emoji.name == '🇳🇿':

            if payload.user_id == self.bot.user.id:
                return

            await self.bot.http.add_reaction(payload.message_id,
                                             payload.channel_id, '🇳🇿')

    async def on_message(self, message):
        if r.findall(message.content):
            await message.add_reaction('🇫')


def setup(bot):
    bot.add_cog(Autoresponds(bot))
