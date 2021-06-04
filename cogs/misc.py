import json
import math
import urllib
from datetime import timedelta, datetime

import aiohttp
import discord
from discord.ext.commands import BucketType

from bot.bot import command, cooldown
from cogs.cog import Cog
from utils import wolfram, memes
from utils.utilities import format_timedelta, DateAccuracy


class Misc(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(aliases=['math'])
    @cooldown(1, 2, type=BucketType.user)
    async def wolfram(self, ctx, *, query):
        """Queries a problem to be solved by wolfram alpha"""
        await ctx.send(await wolfram.math(query, self.bot.aiohttp_client,
                                          self.bot.config.wolfram_key))

    @command(name='say')
    @cooldown(1, 2, BucketType.channel)
    async def say_command(self, ctx, *, words: str):
        """Says the text that was put as a parameter"""
        await ctx.send('{0} {1}'.format(ctx.author.mention, words[:1950]))

    @command(aliases=['twitchquotes'])
    @cooldown(1, 2, type=BucketType.guild)
    async def twitchquote(self, ctx, tts: bool=None):
        """Random twitch quote from twitchquotes.com"""
        await ctx.send(await memes.twitch_poems(self.bot.aiohttp_client), tts=tts)

    @command(cooldown_after_parsing=True)
    @cooldown(1, 60, BucketType.user)
    async def rep(self, ctx, user: discord.Member):
        if ctx.author == user:
            await ctx.send(f'{ctx.author} ~~repped~~ raped ... himself <:peepoWeird:423445885180051467>')
        else:
            await ctx.send(f'{ctx.author} ~~repped~~ raped {user.mention}')

    @command()
    @cooldown(1, 5, BucketType.user)
    async def manga(self, ctx, *, manga_name):
        """
        Search for manga and return estimated the next release date and the estimated release interval for it
        """
        if len(manga_name) > 300:
            await ctx.send('Name too long.')
            return

        manga_name = urllib.parse.quote_plus(manga_name)
        async with self.bot.aiohttp_client.get(f'https://manga-tracker-rss.herokuapp.com/api/search?query={manga_name}') as r:
            if r.status != 200:
                await ctx.send('Http error. Try again later')
                return

            try:
                data = await r.json()
            except (json.decoder.JSONDecodeError, aiohttp.ContentTypeError):
                await ctx.send('Invalid data received. Try again later')
                return

            err = data.get('error')
            if err:
                await ctx.send(f'Error while getting data: {err.get("message", "")}')
                return

            data = data.get('data')
            if not data:
                await ctx.send('Nothing found. Try a different search word')
                return

            manga = data['manga']

            title = manga['title']
            cover = manga['cover']
            release_interval = manga['releaseInterval']
            estimated_release = manga['estimatedRelease']
            latest_release = manga.get('latestRelease')

            description = ''

            if manga.get('status') == 1:
                description = 'This manga has finished publishing\n'
                estimated_release = None
            else:
                if release_interval:
                    release_interval = timedelta(**release_interval)
                    release_interval_ = format_timedelta(release_interval, DateAccuracy.Day-DateAccuracy.Hour)
                    description += f'Estimated release interval: {release_interval_}\n'

                if estimated_release:
                    estimated_release = datetime.strptime(estimated_release, '%Y-%m-%dT%H:%M:%S.%fZ')
                    now = datetime.utcnow()
                    to_estimate = None
                    if estimated_release < now:
                        diff = now - estimated_release
                        if not release_interval:
                            pass
                        elif diff.days > 0:
                            estimated_release += release_interval * math.ceil(diff/release_interval)
                            to_estimate = format_timedelta(estimated_release - now, DateAccuracy.Day - DateAccuracy.Hour)
                    else:
                        to_estimate = format_timedelta(estimated_release - now, DateAccuracy.Day-DateAccuracy.Hour)

                    description += f"Estimated release is on {estimated_release.strftime('%A %H:00, %b %d %Y')} UTC"
                    if to_estimate:
                        description += f' which is in {to_estimate}\n'
                    else:
                        description += '\n'

            if latest_release:
                latest_release = datetime.strptime(latest_release, '%Y-%m-%dT%H:%M:%S.%fZ')
                since_latest_release = format_timedelta(datetime.utcnow() - latest_release, DateAccuracy.Day - DateAccuracy.Hour)
                description += f'Latest release: {since_latest_release} ago ({latest_release.strftime("%A %H:00, %b %d %Y")})'

            if not description:
                description = 'No information available at this time'

            embed = discord.Embed(title=title[:256], description=description)
            if cover:
                embed.set_thumbnail(url=cover)

            if estimated_release:
                embed.timestamp = estimated_release
                embed.set_footer(text='Estimate in your timezone')

            await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Misc(bot))
