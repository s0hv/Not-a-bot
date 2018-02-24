from cogs.cog import Cog
from bot.bot import command


class gachiGASM(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(pass_context=True)
    async def gachify(self, ctx, *, words):
        """Gachify a string"""
        if ' ' not in words:
            # We need to undo the string view or it will skip the first word
            ctx.view.undo()
            await self.gachify2.invoke(ctx)
        else:
            return await self.bot.say(words.replace(' ', ' ♂ ').upper())

    @command(pass_context=True)
    async def gachify2(self, ctx, *, words):
        """An alternative way of gachifying"""
        return await self.bot.say('♂ ' + words.replace(' ', ' ♂ ').upper() + ' ♂')


def setup(bot):
    bot.add_cog(gachiGASM(bot))
