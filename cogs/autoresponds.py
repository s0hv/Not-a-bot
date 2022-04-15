import re

import disnake

from cogs.cog import Cog
from utils.utilities import check_botperm

r = re.compile('(?:^| )billy(?: |$)')


class Autoresponds(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.emoji.name == '🇳🇿':
            channel = self.bot.get_channel(payload.channel_id)
            if not channel:
                return

            me = channel.guild.me if channel.guild else self.bot.user
            if not check_botperm('add_reactions', channel=channel, me=me):
                return

            if payload.user_id == self.bot.user.id:
                return

            try:
                await self.bot.http.add_reaction(payload.message_id,
                                                 payload.channel_id, '🇳🇿')
            except disnake.HTTPException:
                pass

    @Cog.listener()
    async def on_message(self, message):
        if r.findall(message.content):
            me = message.channel.guild.me if message.channel.guild else self.bot.user
            if not check_botperm('add_reactions', channel=message.channel, me=me):
                return

            try:
                await message.add_reaction('🇫')
            except disnake.HTTPException:
                pass


def setup(bot):
    bot.add_cog(Autoresponds(bot))
