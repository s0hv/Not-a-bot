import re
from utils.utilities import check_botperm
from cogs.cog import Cog

r = re.compile('(?:^| )billy(?: |$)')


class Autoresponds(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    async def on_raw_reaction_add(self, payload):
        if payload.emoji.name == '🇳🇿':
            channel = self.bot.get_channel(payload.channel_id)
            me = channel.guild.me if channel.guild else self.bot.user
            if not check_botperm('add_reactions', channel=channel, me=me):
                return

            if payload.user_id == self.bot.user.id:
                return

            await self.bot.http.add_reaction(payload.message_id,
                                             payload.channel_id, '🇳🇿')

    async def on_message(self, message):
        if r.findall(message.content):
            me = message.channel.guild.me if message.channel.guild else self.bot.user
            if not check_botperm('add_reactions', channel=message.channel, me=me):
                return

            await message.add_reaction('🇫')


def setup(bot):
    bot.add_cog(Autoresponds(bot))
