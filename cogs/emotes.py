from discord.ext import commands

from bot.bot import group, cooldown
from cogs.cog import Cog
from utils.utilities import split_string


class Emotes(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @staticmethod
    def get_emotes(guild):
        global_emotes = []
        local_emotes = []
        animated_emotes = []
        emotes = guild.emojis

        for emote in emotes:
            if emote.managed:
                global_emotes.append(emote)
            elif emote.animated:
                animated_emotes.append(emote)
            else:
                local_emotes.append(emote)

        return global_emotes, local_emotes, animated_emotes

    @staticmethod
    def _format_emotes(emotes, limit, type_=None, include_name=True, delim='\n', width=3):
        e = f'{len(emotes)}/{limit} {type_} emotes\n' if type_ else ''

        for i, emote in enumerate(emotes):
            if include_name:
                e += '{} {}'.format(emote.name, emote)
            else:
                e += '{}'.format(emote)

            if i % width == 0:
                e += delim
            else:
                e += ' '

        return e.strip('\n')

    @cooldown(1, 10, type=commands.BucketType.guild)
    @group(no_pm=True)
    async def emotes(self, ctx):
        """Show emotes on this server"""
        guild = ctx.guild
        emote_limit = guild.emoji_limit

        if ctx.invoked_subcommand is None:
            global_emotes, local_emotes, animated_emotes = self.get_emotes(guild)

            if global_emotes:
                s = 'Global emotes:\n' + self._format_emotes(global_emotes, emote_limit, width=2)
            elif local_emotes:
                s = 'Local emotes:\n' + self._format_emotes(local_emotes, emote_limit, 'local')
            elif animated_emotes:
                s = 'Animated emotes:\n' + self._format_emotes(animated_emotes, emote_limit, 'animated')
            else:
                s = 'No emotes'

            strings = split_string(s, maxlen=2000, splitter='\n')

            for s in strings:
                await ctx.send(s)

    @emotes.command(aliases=['counts', 'limit', 'count'])
    @cooldown(1, 4, type=commands.BucketType.guild)
    async def limits(self, ctx):
        """
        Shows limits on emoji counts and how much they're filled on this server
        """
        guild = ctx.guild
        emote_limit = guild.emoji_limit
        _, local, animated = self.get_emotes(guild)
        await ctx.send(f"Emote limits\nStatic: {len(local)}/{emote_limit}\nAnimated: {len(animated)}/{emote_limit}")

    @cooldown(1, 10, type=commands.BucketType.guild)
    @emotes.command(name='global', no_pm=True)
    async def global_(self, ctx, include_name: bool=True):
        """Show global emotes on this server"""
        guild = ctx.guild
        emote_limit = guild.emoji_limit

        global_, _, _ = self.get_emotes(guild)
        s = self._format_emotes(global_, emote_limit, include_name=include_name)
        s = s if s else 'No global emotes'
        for s in split_string(s, maxlen=2000, splitter='\n'):
            await ctx.send(s)

    @cooldown(1, 10, type=commands.BucketType.guild)
    @emotes.command(name='local', no_pm=True)
    async def local_(self, ctx, include_name: bool=True):
        """Show all non global emotes on this server"""
        guild = ctx.guild
        emote_limit = guild.emoji_limit

        _, local_, _ = self.get_emotes(guild)
        s = self._format_emotes(local_, emote_limit, 'local', include_name)
        s = s if s else 'No local emotes'
        for s in split_string(s, maxlen=2000, splitter='\n'):
            await ctx.send(s)

    @cooldown(1, 10, type=commands.BucketType.guild)
    @emotes.command(aliases=['gif'], no_pm=True)
    async def animated(self, ctx, include_name: bool=True):
        """Show all non global emotes on this server"""
        guild = ctx.guild
        emote_limit = guild.emoji_limit

        _, _, animated = self.get_emotes(guild)
        s = self._format_emotes(animated, emote_limit, 'animated', include_name)
        s = s if s else 'No animated emotes'
        for s in split_string(s, maxlen=2000, splitter='\n'):
            await ctx.send(s)


def setup(bot):
    bot.add_cog(Emotes(bot))
