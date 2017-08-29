from cogs.cog import Cog


class Autoresponds(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    async def on_reaction_add(self, reaction, user):
        if isinstance(reaction.emoji, str) and reaction.emoji == '🇳🇿':
            await self.bot.add_reaction(reaction.message, '🇳🇿')


def setup(bot):
    bot.add_cog(Autoresponds(bot))
