from cogs.cog import Cog
from bot.bot import command
from discord.ext.commands import cooldown
from utils.utilities import split_string, emote_url_from_id, get_emote_id
import time
import discord
import os
import subprocess
import shlex
import sys
import re
from utils.utilities import random_color, get_avatar


class Utilities(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._runtime = re.compile(r'(?P<days>\d*(?:-))?(?P<hours>\d\d):(?P<minutes>\d\d):(?P<seconds>\d\d)')

    @command(ignore_extra=True)
    async def ping(self):
        """Ping pong"""
        t = time.time()

        msg = await self.bot.say('Pong!')
        t = time.time() - t
        sql_t = time.time()
        self.bot.get_session.execute('SELECT 1').fetchall()
        sql_t = time.time() - sql_t
        await self.bot.edit_message(msg, 'Pong!\n🏓 took {:.0f}ms\nDatabase ping {:.0f}ms'.format(t*1000, sql_t*1000))

    @command(ignore_extra=True, aliases=['e', 'emoji'])
    async def emote(self, emote: str):
        emote = get_emote_id(emote)
        if emote is None:
            return await self.bot('You need to specify an emote. Default (unicode) emotes are not supported yet')

        await self.bot.say(emote_url_from_id(emote))

    @cooldown(1, 1)
    @command(pass_context=True, aliases=['howtoping'])
    async def how2ping(self, ctx, *, user):
        if ctx.message.server:
            members = ctx.message.server.members
        else:
            members = self.bot.get_all_members()

        def filter_users(predicate):
            for member in members:
                if predicate(member):
                    return member

                if member.nick and predicate(member.nick):
                    return member

        if ctx.message.raw_role_mentions:
            i = len(ctx.invoked_with) + len(ctx.prefix) + 1

            user = ctx.message.clean_content[i:]
            user = user[user.find('@')+1:]

        found = filter_users(lambda u: str(u).startswith(user))
        s = '`<@!{}>` {}'
        if found:
            return await self.bot.say(s.format(found.id, str(found)))

        found = filter_users(lambda u: user in str(u))

        if found:
            return await self.bot.say(
                s.format(found.id, str(found)))

        else:
            return await self.bot.say('No users found with %s' % user)

    @command(ignore_extra=True, aliases=['src', 'source_code'])
    async def source(self):
        await self.bot.say('You can find the source code for this bot here https://github.com/s0hvaperuna/Not-a-bot')

    @command(ignore_extra=True, aliases=['bot', 'about', 'botinfo'], pass_context=True)
    async def stats(self, ctx):
        """Get info about this bot"""
        pid = os.getpid()

        # We have a lot of linux only cmd commands here so most things won't show values on other OSs
        if sys.platform == 'linux':
            uptime = subprocess.check_output(shlex.split('ps -o etime= -p "%s"' % pid)).decode('utf-8')
            match = self._runtime.match(uptime)
            if match:
                uptime = '{hours}h {minutes}m {seconds}s'
                d = match.groupdict()
                if d['days']:
                    uptime = '{days}d ' + uptime

                    uptime = uptime.format(d)

        else:
            uptime = "%s uptime support isn't implemented" % sys.platform

        users = len([a for a in self.bot.get_all_members()])
        servers = len(self.bot.servers)
        try:
            # use pmap to find the memory usage of this process and turn it to megabytes
            memory_usage = subprocess.check_output(shlex.split('pmap %s | grep -Po "total +\K([0-9])+(?=K)"' % pid))
            memory_usage = str(round(int(memory_usage)/1024, 1)) + 'MB'
        except:
            memory_usage = 'N/A'

        try:
            # Get the last time a successful pull was done
            last_updated = subprocess.check_output(shlex.split('date -d "$(stat -c %y .git/refs/heads/master)" -R'))
        except:
            last_updated = 'N/A'

        embed = discord.Embed(title='Stats', colour=random_color())
        embed.add_field(name='discord.py version', value=discord.__version__)
        embed.add_field(name='Uptime', value=uptime)
        embed.add_field(name='Users', value=str(users))
        embed.add_field(name='Servers', value=str(servers), inline=True)
        embed.add_field(name='Memory usage', value=memory_usage)
        embed.add_field(name='Last updated', value=last_updated)
        embed.set_thumbnail(url=get_avatar(self.bot.user))
        embed.set_author(name=self.bot.user.name, icon_url=get_avatar(self.bot.user))

        await self.bot.send_message(ctx.message.channel, embed=embed)


def setup(bot):
    bot.add_cog(Utilities(bot))
