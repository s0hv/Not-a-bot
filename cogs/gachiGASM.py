from bot.bot import command
from cogs.cog import Cog


class gachiGASM(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command()
    async def gachify(self, ctx, *, words):
        """Gachify a string"""
        if ' ' not in words:
            # We need to undo the string view or it will skip the first word
            ctx.view.undo()
            await self.gachify2.invoke(ctx)
        else:
            return await ctx.send(words.replace(' ', ' ♂ ').upper())

    @command()
    async def gachify2(self, ctx, *, words):
        """An alternative way of gachifying"""
        return await ctx.send('♂ ' + words.replace(' ', ' ♂ ').upper() + ' ♂')


def setup(bot):
    bot.add_cog(gachiGASM(bot))
