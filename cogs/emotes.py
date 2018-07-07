from discord.ext import commands
from discord.ext.commands import cooldown

from bot.bot import group
from cogs.cog import Cog
from utils.utilities import split_string


class Emotes(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @staticmethod
    def get_emotes(guild):
        global_emotes = []
        local_emotes = []
        emotes = guild.emojis

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

    @cooldown(1, 10, type=commands.BucketType.guild)
    @group()
    async def emotes(self, ctx):
        """Show emotes on this server"""
        guild = ctx.guild

        if ctx.invoked_subcommand is None:
            global_emotes, local_emotes = self.get_emotes(guild)

            g = 'No global emotes\n'
            if global_emotes:
                g = 'Global emotes:\n' + self._format_emotes(global_emotes)

            g += '\n'
            l = 'No local emotes'
            if local_emotes:
                l = 'Local emotes:\n' + self._format_emotes(local_emotes)

            strings = split_string(g + l, maxlen=2000, splitter='\n')

            for s in strings:
                await ctx.send(s)

    @cooldown(1, 10, type=commands.BucketType.guild)
    @emotes.command(name='global')
    async def global_(self, ctx, include_name=True, delim='\n'):
        """Show global emotes on this server"""
        guild = ctx.guild

        global_, local_ = self.get_emotes(guild)
        s = self._format_emotes(global_, include_name, delim)
        s = s if s else 'No global emotes'
        for s in split_string(s, maxlen=2000, splitter=delim):
            await ctx.send(s)

    @cooldown(1, 10, type=commands.BucketType.guild)
    @emotes.command(name='local')
    async def local_(self, ctx, include_name=True, delim='\n'):
        """Show all non global emotes on this server"""
        guild = ctx.guild

        global_, local_ = self.get_emotes(guild)
        s = self._format_emotes(local_, include_name, delim)
        s = s if s else 'No local emotes'
        for s in split_string(s, maxlen=2000, splitter=delim):
            await ctx.send(s)


def setup(bot):
    bot.add_cog(Emotes(bot))
