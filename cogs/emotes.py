from bot.bot import command, group
from discord.ext.commands import cooldown
from discord.ext import commands
import discord
from utils.utilities import split_string


class Emotes:
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def get_emotes(server):
        global_emotes = []
        local_emotes = []
        emotes = server.emojis

        for emote in emotes:
            if emote.managed:
                global_emotes.append(emote)
            else:
                local_emotes.append(emote)

        return global_emotes, local_emotes

    @staticmethod
    def _format_emotes(emotes, include_name=True, delim='\n'):
        e = ''
        for emote in emotes:
            if include_name:
                e += '{} {}{}'.format(emote.name, emote, delim)
            else:
                e += '{}{}'.format(emote, delim)

        return e[:-len(delim)]

    @cooldown(1, 10, commands.BucketType.server)
    @group(pass_context=True)
    async def emotes(self, ctx):
        server = ctx.message.server

        if ctx.invoked_subcommand is None:
            global_emotes, local_emotes = self.get_emotes(server)

            g = 'No global emotes\n'
            if global_emotes:
                g = 'Global emotes:\n' + self._format_emotes(global_emotes)

            g += '\n'
            l = 'No local emotes'
            if local_emotes:
                l = 'Local emotes:\n' + self._format_emotes(local_emotes)

            strings = split_string(g + l, maxlen=2000, splitter='\n')

            for s in strings:
                await self.bot.say(s)

    @cooldown(1, 10, commands.BucketType.server)
    @emotes.command(name='global', pass_context=True)
    async def global_(self, ctx, include_name=True, delim='\n'):
        server = ctx.message.server

        global_, local_ = self.get_emotes(server)
        s = self._format_emotes(global_, include_name, delim)

        for s in split_string(s, maxlen=2000, splitter=delim):
            await self.bot.say(s)

    @cooldown(1, 10, commands.BucketType.server)
    @emotes.command(name='local', pass_context=True)
    async def local_(self, ctx, include_name=True, delim='\n'):
        server = ctx.message.server

        global_, local_ = self.get_emotes(server)
        s = self._format_emotes(local_, include_name, delim)

        for s in split_string(s, maxlen=2000, splitter=delim):
            await self.bot.say(s)


def setup(bot):
    bot.add_cog(Emotes(bot))