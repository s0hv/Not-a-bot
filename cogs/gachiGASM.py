import os
from datetime import datetime, timedelta
from random import Random, choice

import disnake
from disnake.ext.commands import BucketType, cooldown, guild_only

from bot.bot import command, group, has_permissions
from bot.globals import PLAYLISTS
from cogs.cog import Cog
from utils.utilities import call_later, utcnow
from utils.utilities import read_lines


class WrestlingGif:
    def __init__(self, url, text):
        self.url = url
        self.text = text

    def build_embed(self, author, recipient):
        description = self.text.format(author=author, recipient=recipient)
        embed = disnake.Embed(description=description)
        embed.set_image(url=self.url)
        return embed


wrestling_gifs = [
    WrestlingGif('https://i.imgur.com/xUi2Vq1.gif', "**{recipient.name}** tries to grab but it fails. **{author.name}** grabs **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/osDWTHG.gif', "**{recipient.name}** tries to escape but **{author.name}** pins them down"),
    WrestlingGif('https://i.imgur.com/HS6R463.gif', "**{author.name}** lifts **{recipient.name}** up. **{recipient.name}** is powerless to do anything"),
    WrestlingGif('https://i.imgur.com/jbE2XVt.gif', "**{author.name}** challenges **{recipient.name}** to a friendly wrestling match"),
    WrestlingGif('https://i.imgur.com/XVUjH9x.gif', "**{recipient.name}** tries to attack but **{author.name}** counters"),
    WrestlingGif('https://i.imgur.com/vTeoYAE.gif', "**{author.name}** and **{recipient.name}** engage in a battle of strength"),
    WrestlingGif('https://i.imgur.com/iu2kiVy.gif', "**{author.name}** gets a hold of **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/BulkVW1.gif', "**{author.name}** gets **{recipient.name}** with a knee strike"),
    WrestlingGif('https://i.imgur.com/zXaIYLp.gif', "**{author.name}** beats **{recipient.name}** down"),
    WrestlingGif('https://i.imgur.com/XNOMUcg.gif', "**{author.name}** delivers a low blow to **{recipient.name}**. Nasty strategy"),
    WrestlingGif('https://i.imgur.com/oSG0V6a.gif', "**{recipient.name}** gets beaten by **{author.name}**"),
    WrestlingGif('https://i.imgur.com/u0H0ZSA.gif', "**{author.name}** grabs **{recipient.name}**s fucking pants <:GWjojoGachiGASM:363025405562585088>"),
    WrestlingGif('https://i.imgur.com/VFruiTR.gif', "**{author.name}** flexes on **{recipient.name}** after kicking their ass. WOO"),
    WrestlingGif('https://i.imgur.com/YCd1aSo.gif', "**{author.name}** beats **{recipient.name}** up"),
    WrestlingGif('https://i.imgur.com/M3sAu23.gif', "**{author.name}** chokes **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/inEROy3.gif', "**{author.name}** throws **{recipient.name}** on the ground"),
    WrestlingGif('https://i.imgur.com/8qI8f1M.gif', "**{author.name}** battles **{recipient.name}** in a feat of pure strength"),
    WrestlingGif('https://i.imgur.com/xhVIjIt.gif', "**{author.name}** lifts **{recipient.name}** up"),
    WrestlingGif('https://i.imgur.com/RW07zr0.gif', "**{author.name}** escapes the choke of **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/g6wVGpG.gif', "**{author.name}** escapes **{recipient.name}**s grab and begins a counter-attack"),
    WrestlingGif('https://i.imgur.com/LKHtUeo.gif', "**{author.name}** gets a hold of **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/eCCAKoA.gif', "It's time to wrestle"),
    WrestlingGif('https://i.imgur.com/ZFiT5Ew.gif', "**{author.name}** lifts **{recipient.name}** up"),
    WrestlingGif('https://i.imgur.com/A4Oo0Tp.gif', "**{author.name}** puts **{recipient.name}** down"),
    WrestlingGif('https://i.imgur.com/COQlI5t.gif', "**{author.name}** swaps positions with **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/pIaErDy.gif', "**{author.name}** pulls **{recipient.name}**s arms"),
    WrestlingGif('https://i.imgur.com/hThhSrl.gif', "**{author.name}** locks **{recipient.name}**s leg"),
    WrestlingGif('https://i.imgur.com/goMZvRE.gif', "**{author.name}** turns the tables on **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/3A9eMu0.gif', "**{author.name}** slams **{recipient.name}** on the floor"),
    WrestlingGif('https://i.imgur.com/G9Iklxu.gif', "**{author.name}** and **{recipient.name}** are in the middle of an intense battle"),
    WrestlingGif('https://i.imgur.com/c1CQBnJ.gif', "**{recipient.name}** gets elbow struck by **{author.name}**"),
    WrestlingGif('https://i.imgur.com/cKcOJo0.gif', "**{author.name}** pulls **{recipient.name}**s leg"),
    WrestlingGif('https://i.imgur.com/Q41oEne.gif', "**{recipient.name}** gets elbow struck by **{author.name}**"),
    WrestlingGif('https://i.imgur.com/AP7MRnF.gif', "**{author.name}** escapes the hold of **{recipient.name}** and is ready for more"),
    WrestlingGif('https://i.imgur.com/6khggL1.gif', "**{author.name}** pulls the hair of **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/bq0Bjbl.gif', "**{author.name}** got the moves"),
    WrestlingGif('https://i.imgur.com/aIVoytr.gif', "**{author.name}** throws **{recipient.name}** on the ground"),
    WrestlingGif('https://i.imgur.com/l137Zzh.gif', "**{recipient.name}** gets elbow struck by **{author.name}**"),
    WrestlingGif('https://i.imgur.com/tFZv2j9.gif', "**{recipient.name}** and **{author.name}** engage in a fight. **{author.name}** makes the first move"),
    WrestlingGif('https://i.imgur.com/kVXjE3Q.gif',  "**{author.name}** pulls **{recipient.name}**'s hands"),
    WrestlingGif('https://i.imgur.com/4IsfXSD.gif', "**{author.name}** has **{recipient.name}** locked down"),
    WrestlingGif('https://i.imgur.com/HnLRl26.gif', "**{author.name}** spins **{recipient.name}** right round baby right round"),
    WrestlingGif('https://i.imgur.com/uJtuZ4V.gif', "**{author.name}** beats **{recipient.name}** up and locks him down"),
    WrestlingGif('https://i.imgur.com/ZgXNVIb.gif', "**{recipient.name}** flails his arms around helplessly"),
    WrestlingGif('https://i.imgur.com/Jcu4NyL.gif', "**{author.name}** manages to get a quick jab in at **{recipient.name}**"),
    WrestlingGif('https://i.imgur.com/XUpxidH.gif', "**{author.name}** pulls on **{recipient.name}**'s leg"),
    WrestlingGif('https://i.imgur.com/pTBy6ap.gif', "**{recipient.name}** and **{author.name}** engage in a hugging competition"),
    WrestlingGif('https://i.imgur.com/ggTj4xI.gif', "**{author.name}** escapes **{recipient.name}**'s hold and counters"),
    WrestlingGif('https://i.imgur.com/lS2zZre.gif', "**{author.name}** locks **{recipient.name}**'s legs"),
    WrestlingGif('https://i.imgur.com/fdgI1Br.gif', "**{recipient.name}** gets choked by **{author.name}** and tries to escape but fails"),
]


class gachiGASM(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.gachilist = self.bot.gachilist
        if not self.gachilist:
            self.reload_gachilist()

        self.reload_call = call_later(self._reload_and_post, self.bot.loop, self.time2tomorrow())

    def cog_unload(self):
        self.reload_call.cancel()

    async def _reload_and_post(self):
        self.reload_gachilist()

        for guild in self.bot.guilds:
            vid = Random(self.get_day()+guild.id).choice(self.gachilist)
            channel = self.bot.guild_cache.dailygachi(guild.id)
            if not channel:
                continue

            channel = guild.get_channel(channel)
            if not channel:
                continue

            try:
                await channel.send(f'Daily gachi {vid}')
            except disnake.HTTPException:
                pass

        self.reload_call = call_later(self._reload_and_post, self.bot.loop,
                                      self.time2tomorrow())

    def reload_gachilist(self):
        self.bot.gachilist = read_lines(os.path.join(PLAYLISTS, 'gachi.txt'))
        self.gachilist = self.bot.gachilist

    @staticmethod
    def time2tomorrow():
        # Get utcnow, add 1 day to it and check how long it is to the next day
        # by subtracting utcnow from the gained date
        now = utcnow()
        tomorrow = now + timedelta(days=1)
        return (tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
                - now).total_seconds()

    @staticmethod
    def get_day():
        return (utcnow() - datetime.min).days

    @command()
    @cooldown(1, 2, BucketType.channel)
    async def gachify(self, ctx, *, words):
        """Gachify a string"""
        if ' ' not in words:
            # We need to undo the string view or it will skip the first word
            ctx.view.undo()
            await self.gachify2.invoke(ctx)
        else:
            return await ctx.send(words.replace(' ', r' \♂ ').upper()[:2000])

    @command()
    @cooldown(1, 2, BucketType.channel)
    async def gachify2(self, ctx, *, words):
        """An alternative way of gachifying"""
        s = r'\♂ ' + words.replace(' ', r' \♂ ').upper() + r' \♂'
        return await ctx.send(s[:2000])

    @command(aliases=['rg'])
    @cooldown(1, 5, BucketType.channel)
    async def randomgachi(self, ctx):
        await ctx.send(choice(self.gachilist))

    @group(invoke_without_command=True, aliases=['dg'])
    @guild_only()
    @cooldown(1, 5, BucketType.channel)
    async def dailygachi(self, ctx):
        await ctx.send(Random(self.get_day()+ctx.guild.id).choice(self.gachilist))

    @dailygachi.command(np_pm=True)
    @cooldown(1, 5)
    @has_permissions(manage_guild=True)
    async def subscribe(self, ctx, *, channel: disnake.TextChannel=None):
        if channel:
            await self.bot.guild_cache.set_dailygachi(ctx.guild.id, channel.id)
            return await ctx.send(f'New dailygachi channel set to {channel}')

        channel = self.bot.guild_cache.dailygachi(ctx.guild.id)
        channel = ctx.guild.get_channel(channel)

        if channel:
            await ctx.send(f'Current dailygachi channel is {channel}')
        else:
            await ctx.send('No dailygachi channel set')

    @dailygachi.command()
    @cooldown(1, 5)
    @has_permissions(manage_guild=True)
    @guild_only()
    async def unsubscribe(self, ctx):
        await self.bot.guild_cache.set_dailygachi(ctx.guild.id, None)
        await ctx.send('Dailygachi channel no longer set')

    @command()
    @cooldown(1, 5, BucketType.member)
    @guild_only()
    async def wrestle(self, ctx, *, user: disnake.User):
        if user == ctx.author:
            await ctx.send('Wrestling against yourself...')
            return

        wrestling_gif = choice(wrestling_gifs)

        await ctx.send(embed=wrestling_gif.build_embed(ctx.author, user))


def setup(bot):
    bot.add_cog(gachiGASM(bot))
