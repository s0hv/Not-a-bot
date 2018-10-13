import os
from datetime import datetime, timedelta
from random import Random

from discord.ext.commands import BucketType

from bot.bot import command, cooldown, group, has_permissions
from bot.globals import PLAYLISTS
from cogs.cog import Cog
from utils.utilities import read_lines
from utils.utilities import call_later
import discord


class gachiGASM(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.gachilist = []
        self.reload_gachilist()
        self.reload_call = call_later(self._reload_and_post, self.bot.loop, self.time2tomorrow())

    def __unload(self):
        self.reload_call.cancel()

    async def _reload_and_post(self):
        self.reload_gachilist()
        vid = Random(self.get_day()).choice(self.gachilist)

        for guild in self.bot.guilds:
            channel = self.bot.guild_cache.dailygachi(guild.id)
            if not channel:
                continue

            channel = guild.get_channel(channel)
            if not channel:
                continue

            try:
                await channel.send(f'Daily gachi {vid}')
            except:
                pass

        self.reload_call = call_later(self._reload_and_post(), self.bot.loop,
                                      self.time2tomorrow())

    def reload_gachilist(self):
        self.gachilist = read_lines(os.path.join(PLAYLISTS, 'gachi.txt'))

    @staticmethod
    def time2tomorrow():
        # Get utcnow, add 1 day to it and check how long it is to the next day
        # by subtracting utcnow from the gained date
        now = datetime.utcnow()
        tomorrow = now + timedelta(days=1)
        return (tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
                - now).total_seconds()

    @staticmethod
    def get_day():
        return (datetime.utcnow() - datetime.min).days

    @command()
    @cooldown(1, 2, BucketType.channel)
    async def gachify(self, ctx, *, words):
        """Gachify a string"""
        if ' ' not in words:
            # We need to undo the string view or it will skip the first word
            ctx.view.undo()
            await self.gachify2.invoke(ctx)
        else:
            return await ctx.send(words.replace(' ', ' ♂ ').upper())

    @command()
    @cooldown(1, 2, BucketType.channel)
    async def gachify2(self, ctx, *, words):
        """An alternative way of gachifying"""
        return await ctx.send('♂ ' + words.replace(' ', ' ♂ ').upper() + ' ♂')

    @group(ignore_extra=True, invoke_without_command=True)
    @cooldown(1, 5, BucketType.channel)
    async def dailygachi(self, ctx):
        await ctx.send(Random(self.get_day()).choice(self.gachilist))

    @dailygachi.command()
    @cooldown(1, 5)
    @has_permissions(manage_server=True)
    async def subscribe(self, ctx, *, channel: discord.TextChannel=None):
        if channel:
            await self.bot.guild_cache.set_dailygachi(ctx.guild.id, channel.id)
            return await ctx.send(f'New dailygachi channel set to {channel}')

        channel = self.bot.guild_cache.dailygachi(ctx.guild.id)
        channel = ctx.guild.get_channel(channel)

        if channel:
            await ctx.send(f'Current dailygachi channel is {channel}')
        else:
            await ctx.send('No dailygachi channel set')

    @dailygachi.command(ignore_extra=True)
    @cooldown(1, 5)
    @has_permissions(manage_server=True)
    async def unsubscribe(self, ctx):
        await self.bot.guild_cache.set_dailygachi(ctx.guild.id, None)
        await ctx.send('Dailygachi channel no longer set')


def setup(bot):
    bot.add_cog(gachiGASM(bot))
