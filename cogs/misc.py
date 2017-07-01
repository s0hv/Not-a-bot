from bot.bot import command
from cogs.cog import Cog
from utils import wolfram, memes


class Misc(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(pass_context=True)
    async def math(self, ctx, *, query):
        """Queries a math problem to be solved by wolfram alpha"""
        await self.bot.send_message(ctx.message.channel,
                                    await wolfram.math(query,
                                                       self.bot.aiohttp_client,
                                                       self.bot.config.wolfram_key))

    @command(name='say', pass_context=True)
    async def say_command(self, ctx, *, words):
        """Says the text that was put as a parameter"""
        await self.bot.say('{0} {1}'.format(ctx.message.author.mention, words))

    @command(pass_context=True, ignore_extra=True)
    async def twitchquote(self, ctx):
        """CURRENTLY BROKEN. Random twitch quote from twitchquotes.com"""
        await self.bot.send_message(ctx.message.channel, await memes.twitch_poems(self.bot.aiohttp_client))


def setup(bot):
    bot.add_cog(Misc(bot))