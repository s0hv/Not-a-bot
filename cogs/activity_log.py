import asyncio
from datetime import datetime

import discord
from discord.activity import ActivityType
from discord.ext.commands import BucketType

from bot.bot import command, cooldown
from cogs.cog import Cog
from utils.utilities import (get_avatar, seconds2str, bool_check, is_false,
                             basic_check)


class ActivityLog(Cog):
    def __init__(self, bot):
        super(ActivityLog, self).__init__(bot)
        self._db_queue = []
        self._update_task = asyncio.run_coroutine_threadsafe(self._game_loop(), loop=bot.loop)
        self._update_task_checker = asyncio.run_coroutine_threadsafe(self._check_loop(), loop=bot.loop)
        self._update_now = asyncio.Event(loop=bot.loop)

    def cog_unload(self):
        self._update_task_checker.cancel()
        self.bot.loop.call_soon_threadsafe(self._update_now.set)
        try:
            self._update_task.result(timeout=20)
        except TimeoutError:
            pass

    async def add_game_time(self):
        if not self._db_queue:
            return

        q = self._db_queue
        self._db_queue = []
        await self.bot.dbutils.add_multiple_activities(q)
        del q

    async def _game_loop(self):
        while not self._update_now.is_set():
            try:
                await asyncio.wait_for(self._update_now.wait(), timeout=10, loop=self.bot.loop)
            except asyncio.TimeoutError:
                pass

            if not self._db_queue:
                continue

            try:
                await asyncio.shield(self.add_game_time())
            except asyncio.CancelledError:
                return
            except asyncio.TimeoutError:
                continue

    async def _check_loop(self):
        await asyncio.sleep(120)
        if self._update_task.done():
            self._update_task = self.bot.loop.create_task(self._game_loop())

    @staticmethod
    def status_changed(before, after):
        try:
            if before.activity and before.activity.type == ActivityType.playing and before.activity.start and after.activity is None:
                return True

        # Sometimes you get the error ValueError: year 505XX is out of range
        except ValueError:
            pass

        return False

    @Cog.listener()
    async def on_member_update(self, before, after):
        if self.status_changed(before, after):
            self._db_queue.append({'user': after.id,
                                   'time': (datetime.utcnow() - before.activity.start).seconds,
                                   'game': before.activity.name})

    @command()
    @cooldown(1, 60, BucketType.user)
    async def played(self, ctx):
        games = await self.bot.dbutils.get_activities(ctx.author.id)
        if games is False:
            await ctx.send('Failed to execute sql')
            return
        elif not games:
            await ctx.send('No played data has been logged')
            return

        embed = discord.Embed(title='Top games played')
        embed.set_author(name=str(ctx.author), icon_url=get_avatar(ctx.author))
        for game in games:

            embed.add_field(name=game['game'], value=seconds2str(seconds=game['time'], long_def=False), inline=False)

        await ctx.send(embed=embed)

    @command(aliases=['del_played'])
    @cooldown(1, 60, BucketType.user)
    async def delete_played(self, ctx):
        """This will delete all your data from the games you've played
        This is an unreversable action"""
        await ctx.send('This will delete all of your date from the db. This cannot be reversed\nContinue?')

        _check = basic_check(ctx.author, ctx.channel)

        def check(msg):
            return _check(msg) and bool_check(msg.content)

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send('Cancelling')
            return

        if is_false(msg.content.lower().strip()):
            await ctx.send('Cancelling')
            return

        res = await self.bot.dbutils.delete_activities(ctx.author.id)
        if not res:
            return await ctx.send('Failed to delete game records. Exception has been logged')

        await ctx.send('All of your game data has been removed')


def setup(bot):
    bot.add_cog(ActivityLog(bot))
