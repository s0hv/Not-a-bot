import logging
import os
import re
import shlex
import subprocess
import sys
import time

import discord
from discord.ext.commands import cooldown, BucketType

from bot.bot import command
from cogs.cog import Cog
from utils.utilities import emote_url_from_id, get_emote_id, get_emote_url
from utils.utilities import random_color, get_avatar
from email.utils import formatdate as format_rfc2822
from utils.utilities import split_string

logger = logging.getLogger('debug')


class Utilities(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._runtime = re.compile(r'(?P<days>\d+)*?(?:-)?(?P<hours>\d\d)?:?(?P<minutes>\d\d):(?P<seconds>\d\d)')

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
        emote = get_emote_url(emote)
        if emote is None:
            return await self.bot('You need to specify an emote. Default (unicode) emotes are not supported yet')

        await self.bot.say(emote)

    @cooldown(1, 1, type=BucketType.user)
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

    def _unpad_zero(self, value):
        if not isinstance(value, str):
            return
        return value.lstrip('0')

    @command(ignore_extra=True, aliases=['bot', 'about', 'botinfo'], pass_context=True)
    @cooldown(2, 5, BucketType.user)
    async def stats(self, ctx):
        """Get info about this bot"""
        pid = os.getpid()

        # We have a lot of linux only cmd commands here so most things won't show values on other OSs
        if sys.platform == 'linux':
            uptime = subprocess.check_output(shlex.split('ps -o etime= -p "%s"' % pid)).decode('utf-8').strip()
            match = self._runtime.match(uptime)
            if match:
                uptime = '{minutes}m {seconds}s'
                d = match.groupdict()
                d = {k: self._unpad_zero(v) for k, v in d.items()}

                if d['hours']:
                    uptime = '{hours}h ' + uptime
                if d['days']:
                    uptime = '{days}d ' + uptime

                uptime = uptime.format(**d)

        else:
            uptime = "%s uptime support isn't implemented" % sys.platform

        users = len([a for a in self.bot.get_all_members()])
        servers = len(self.bot.servers)
        try:
            # use pmap to find the memory usage of this process and turn it to megabytes
            # Since shlex doesn't care about pipes | I have to do this
            s1 = subprocess.Popen(shlex.split('pmap %s' % os.getpid()),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            s2 = subprocess.Popen(
                shlex.split('grep -Po "total +\K([0-9])+(?=K)"'),
                stdin=s1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            s1.stdin.close()
            memory_usage = s2.communicate()[0].decode('utf-8')
            memory_usage = str(round(int(memory_usage)/1024, 1)) + 'MB'
        except:
            logger.exception('Failed to get mem usage')
            memory_usage = 'N/A'

        try:
            # Get the last time the bot was updated
            last_updated = format_rfc2822(os.stat('.git/refs/heads/master').st_mtime, localtime=True)
        except:
            logger.exception('Failed to get last updated')
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

    @command(name='roles', pass_context=True, ignore_extra=True)
    @cooldown(1, 5, type=BucketType.server)
    async def get_roles(self, ctx, page=''):
        server_roles = sorted(ctx.message.server.roles, key=lambda r: r.name)
        print_all = page.lower() == 'all'
        idx = 0
        if print_all and ctx.message.author.id != self.bot.owner:
            return await self.bot.say('Only the owner can use the all modifier', delete_after=30)
        elif page and not print_all:
            try:
                idx = int(page) - 1
                if idx < 0:
                    return await self.bot.say('Index must be bigger than 0')
            except ValueError:
                return await self.bot.say('%s is not a valid integer' % page, delete_after=30)

        maxlen = 1950
        roles = 'A total of %s roles\n' % len(server_roles)
        for role in server_roles:
            roles += '{}: {}\n'.format(role.name, role.mention)

        roles = split_string(roles, splitter='\n', maxlen=maxlen)
        if not print_all:
            try:
                roles = (roles[idx],)
            except IndexError:
                return await self.bot.say('Page index %s is out of bounds' % idx, delete_after=30)

        for s in roles:
            await self.bot.say('```' + s + '```')


def setup(bot):
    bot.add_cog(Utilities(bot))
