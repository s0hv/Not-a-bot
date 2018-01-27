from cogs.cog import Cog


class Autoresponds(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    async def on_reaction_add(self, reaction, user):
        if isinstance(reaction.emoji, str) and reaction.emoji == '🇳🇿':
            if user.id == self.bot.user.id:
                return
            if reaction.me:
                return
            await self.bot.add_reaction(reaction.message, '🇳🇿')

    async def on_raw_reaction_add(self, data):
        if data['user_id'] == self.bot.user.id:
            return

        if data['emoji']['name'] != '🇳🇿':
            return
        await self.bot.http.add_reaction(data['message_id'], data['channel_id'], '🇳🇿')


def setup(bot):
    bot.add_cog(Autoresponds(bot))
