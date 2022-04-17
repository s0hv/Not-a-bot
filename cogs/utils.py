import inspect
import logging
import os
import re
import shlex
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from email.utils import formatdate as format_rfc2822
from io import StringIO
from typing import Union, cast
from urllib.parse import quote

import aiohttp
import disnake
import psutil
import pytz
from asyncpg.exceptions import PostgresError
from dateutil import parser
from dateutil.tz import gettz
from disnake.ext.commands import (BucketType, Group, cooldown,
                                  guild_only)
from disnake.ext.commands.errors import BadArgument

from bot.bot import command, bot_has_permissions, Context
from bot.converters import FuzzyRole, TzConverter, PossibleUser
from bot.paginator import Paginator
from cogs.cog import Cog
from utils.tzinfo import fuzzy_tz, tz_dict
from utils.unzalgo import unzalgo
from utils.utilities import (random_color, get_avatar, split_string,
                             format_timedelta,
                             parse_timeout, DateAccuracy, utcnow)

try:
    from pip.commands import SearchCommand
except ImportError:
    try:
        from pip._internal.commands.search import SearchCommand
    except (ImportError, TypeError):
        SearchCommand = None

logger = logging.getLogger('terminal')
parserinfo = parser.parserinfo(dayfirst=True)


class Utilities(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command()
    @cooldown(1, 10, BucketType.guild)
    async def changelog(self, ctx, starting_page: int=1):
        sql = 'SELECT * FROM changelog ORDER BY time DESC'
        rows = await self.bot.dbutil.fetch(sql)

        def create_embed(row):
            embed = disnake.Embed(title='Changelog', description=row['changes'],
                                  timestamp=row['time'])
            return embed

        def get_page(idx: int):
            page = rows[idx]
            if not isinstance(page, disnake.Embed):
                page = create_embed(page)
                page.set_footer(text=f'Page {idx+1}/{len(rows)}')
                rows[idx] = page

            return page

        if starting_page > 0:
            starting_page -= 1
        elif starting_page == 0:
            starting_page = 1

        paginator = Paginator(rows, generate_page=get_page, initial_page=starting_page,
                              hide_page_count=True, show_stop_button=True)
        await paginator.send(ctx)

    @command(aliases=['pong'])
    @cooldown(1, 5, BucketType.guild)
    async def ping(self, ctx):
        """Ping pong"""
        t = time.perf_counter()
        if ctx.received_at:
            local_delay = t - ctx.received_at
        else:
            local_delay = utcnow().timestamp() - ctx.message.created_at.timestamp()

        await ctx.trigger_typing()
        t = time.perf_counter() - t
        message = 'Pong!\n🏓 took {:.0f}ms\nLocal delay {:.0f}ms\nWebsocket ping {:.0f}ms'.format(t*1000, local_delay*1000, self.bot.latency*1000)
        if hasattr(self.bot, 'pool'):
            try:
                _, sql_t = await self.bot.dbutil.fetch('SELECT 1', measure_time=True)
                message += '\nDatabase ping {:.0f}ms'.format(sql_t * 1000)
            except PostgresError:
                message += '\nDatabase could not be reached'

        await ctx.send(message)

    @command(aliases=['e', 'emoji'])
    @cooldown(1, 5, BucketType.channel)
    async def emote(self, ctx, emote: disnake.PartialEmoji):
        """Get the link to an emote"""
        await ctx.send(emote.url)

    @command(aliases=['roleping'])
    @cooldown(1, 4, BucketType.channel)
    async def how2role(self, ctx, *, role: FuzzyRole):
        """Searches a role and tells you how to ping it"""
        role = cast(disnake.Role, role)
        name = role.name.replace('@', '@\u200b')
        await ctx.send(f'`{role.mention}` {name}')

    @command(aliases=['howtoping'])
    @cooldown(1, 4, BucketType.channel)
    async def how2ping(self, ctx, *, user):
        """Searches a user by their name and get the string you can use to ping them"""
        if ctx.guild:
            members = ctx.guild.members
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
            return await ctx.send(s.format(found.id, str(found)))

        found = filter_users(lambda u: user in str(u))

        if found:
            return await ctx.send(s.format(found.id, str(found)))

        else:
            return await ctx.send('No users found with %s' % user)

    @command(aliases=['src', 'source_code', 'sauce'])
    @cooldown(1, 5, BucketType.user)
    async def source(self, ctx, *, cmd=None):
        """Link to the source code for this bot
        You can also get the source code of commands by doing {prefix}{name} cmd_name"""
        if cmd:
            full_name = cmd
            cmnd = self.bot.all_commands.get(cmd[0])
            if cmnd is None:
                raise BadArgument(f'Command "{full_name}" not found')

            for c in cmd[1:]:
                if not isinstance(cmnd, Group):
                    raise BadArgument(f'Command "{full_name}" not found')

                cmnd = cmnd.get_command(c)

            cmd = cmnd

        if not cmd:
            await ctx.send('You can find the source code for this bot here https://github.com/s0hv/Not-a-bot')
            return

        source, line_number = inspect.getsourcelines(cmd.callback)
        filename = inspect.getsourcefile(cmd.callback).replace(os.getcwd(), '').strip('\\/')

        # unformatted source
        original_source = textwrap.dedent(''.join(source))

        # Url pointing to the command in github
        url = f'https://github.com/s0hv/Not-a-bot/tree/master/{filename}#L{line_number}'

        # Source code in message
        source = original_source.replace('```', '`\u200b`\u200b`')  # Put zero width space between backticks so they can be within a codeblock
        source = f'<{url}>\n```py\n{source}\n```'

        if len(source) > 2000:
            file = disnake.File(StringIO(original_source), filename=f'{full_name}.py')
            await ctx.send(file=file)
            return
        await ctx.send(source)

    @command()
    @cooldown(1, 5, BucketType.user)
    async def undo(self, ctx):
        """
        Undoes the last undoable command result. Not all messages will be undoable
        and undoable messages override each other because only one message can be
        undone.
        """
        if not await ctx.undo():
            await ctx.send('Failed to undo the latest undoable command for you.\n'
                           'Do note that they expire in one minute')

    @command()
    @cooldown(1, 10, BucketType.user)
    async def invite(self, ctx):
        """This bots invite link"""
        await ctx.send(f'<https://discordapp.com/api/oauth2/authorize?client_id={self.bot.user.id}&permissions=1342557248&scope=bot>')

    @staticmethod
    def _unpad_zero(value):
        if not isinstance(value, str):
            return
        return value.lstrip('0')

    @command(aliases=['bot', 'botinfo'])
    @cooldown(2, 5, BucketType.user)
    @bot_has_permissions(embed_links=True)
    async def stats(self, ctx):
        """Get stats about this bot"""
        pid = os.getpid()
        process = psutil.Process(pid)
        uptime = time.time() - process.create_time()
        d = datetime.utcfromtimestamp(uptime)
        uptime = f'{d.day-1}d {d.hour}h {d.minute}m {d.second}s'
        current_memory = round(process.memory_info().rss / 1048576, 2)
        memory_usage = f' Current: {current_memory}MB'
        if sys.platform == 'linux':
            try:
                # use pmap to find the memory usage of this process and turn it to megabytes
                # Since shlex doesn't care about pipes | I have to do this
                s1 = subprocess.Popen(shlex.split('pmap %s' % os.getpid()),
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                s2 = subprocess.Popen(
                    shlex.split(r'grep -Po "total +\K([0-9])+(?=K)"'),
                    stdin=s1.stdout, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
                s1.stdin.close()
                memory = round(int(s2.communicate()[0].decode('utf-8')) / 1024, 1)
                usable_memory = str(memory) + 'MB'
                memory_usage = f'{current_memory}MB/{usable_memory} ({(current_memory/memory*100):.1f}%)'

            except:
                logger.exception('Failed to get extended mem usage')
                raise

        users = 0
        for _ in self.bot.get_all_members():
            users += 1

        guilds = len(self.bot.guilds)

        try:
            # Get the last time the bot was updated
            last_updated = format_rfc2822(os.stat('.git/refs/heads/master').st_mtime, localtime=True)
        except OSError:
            logger.exception('Failed to get last updated')
            last_updated = 'N/A'

        sql = 'SELECT * FROM command_stats ORDER BY uses DESC LIMIT 3'
        try:
            rows = await self.bot.dbutil.fetch(sql)
        except PostgresError:
            logger.exception('Failed to get command stats')
            top_cmd = 'Failed to get command stats'
        else:
            top_cmd = ''
            i = 1
            for row in rows:
                name = row['parent']
                cmd = row['cmd']
                if cmd:
                    name += ' ' + cmd

                top_cmd += f'{i}. `{name}` with {row["uses"]} uses\n'
                i += 1

        embed = disnake.Embed(title='Stats', colour=random_color())
        embed.add_field(name='disnake version', value=f"{disnake.__version__}")
        embed.add_field(name='Uptime', value=uptime)
        if ctx.guild and ctx.guild.shard_id is not None:
            embed.add_field(name='Shard', value=ctx.guild.shard_id)
        embed.add_field(name='Servers', value=str(guilds))
        embed.add_field(name='Users', value=str(users))
        embed.add_field(name='Memory usage', value=memory_usage)
        embed.add_field(name='Last updated', value=last_updated)
        embed.add_field(name='Most used commands', value=top_cmd)
        embed.set_thumbnail(url=get_avatar(self.bot.user))
        embed.set_author(name=self.bot.user.name, icon_url=get_avatar(self.bot.user))

        await ctx.send(embed=embed)

    @command(name='roles')
    @cooldown(1, 10, type=BucketType.guild)
    @guild_only()
    async def get_roles(self, ctx, starting_page: int=0):
        """Get roles on this server"""
        guild_roles = sorted(ctx.guild.roles, key=lambda r: r.name)

        if starting_page > 0:
            starting_page -= 1

        roles = 'A total of %s roles\n' % len(guild_roles)
        for role in guild_roles:
            roles += '{}: {}\n'.format(role.name, role.mention)

        roles = split_string(roles, splitter='\n', maxlen=1000)

        def generate_page(page_index) -> str:
            role_str = roles[page_index]
            return f'```{role_str}```'

        paginator = Paginator(roles, initial_page=starting_page, generate_page=generate_page)
        await paginator.send(ctx, allowed_mentions=disnake.AllowedMentions.none())

    @command(aliases=['created_at', 'snowflake', 'snoflake'])
    @cooldown(1, 5, type=BucketType.guild)
    async def snowflake_time(self, ctx, id: int):
        """Gets creation date from the specified discord id in UTC"""
        try:
            int(id)
        except ValueError:
            return await ctx.send("{} isn't a valid integer".format(id))

        await ctx.send(str(disnake.utils.snowflake_time(id)))

    @command(hidden=True)
    @cooldown(1, 5, BucketType.user)
    async def birthday(self, ctx, *, user): # clean_content):
        url = 'http://itsyourbirthday.today/#' + quote(user)
        await ctx.send(url)

    @command(name='unzalgo', hidden=True)
    @cooldown(2, 5, BucketType.guild)
    async def unzalgo_(self, ctx, *, zalgo_text: str):
        """Unzalgo text
        if text is not specified a cache lookup on zalgo text is done for the last 100 msgs
        and the first found zalgo text is unzalgo'd"""
        await ctx.send(unzalgo(zalgo_text))

    @command()
    @cooldown(1, 20, BucketType.guild)
    async def support(self, ctx):
        """
        Support server
        """
        await ctx.send('The bot does not have a dedicated support server but you '
                       'can join this server and ask me (s0hvaperuna#4758) stuff\n' +
                       self.bot.config.support_server)

    @command()
    @cooldown(1, 120, BucketType.user)
    async def feedback(self, ctx, *, feedback):
        """
        Send feedback of the bot.
        Bug reports should go to https://github.com/s0hvaperuna/Not-a-bot/issues
        """

        webhook = self.bot.config.feedback_webhook
        if not webhook:
            return await ctx.send('This command is unavailable atm')

        e = disnake.Embed(title='Feedback', description=feedback)
        author = ctx.author
        avatar = get_avatar(author)
        e.set_thumbnail(url=avatar)
        e.set_footer(text=str(author), icon_url=avatar)
        e.add_field(name='Guild', value=f'{ctx.guild.id}\n{ctx.guild.name}')

        json = {'embeds': [e.to_dict()],
                'avatar_url': avatar,
                'username': ctx.author.name,
                'wait': True}
        headers = {'Content-type': 'application/json'}
        success = False
        try:
            async with aiohttp.ClientSession() as client:
                r = await client.post(webhook, json=json, headers=headers)
        except aiohttp.ClientError:
            logger.exception('')
        else:
            status = str(r.status)
            # Accept 2xx status codes
            if status.startswith('2'):
                success = True

        if success:
            await ctx.send('Feedback sent')
        else:
            await ctx.send('Failed to send feedback')

    @command(ingore_extra=True)
    @cooldown(1, 10, BucketType.guild)
    async def vote(self, ctx):
        """Pls vote thx"""
        await ctx.send('https://top.gg/bot/214724376669585409/vote')

    @staticmethod
    def find_emoji(emojis, name):
        for e in emojis:
            if e.name.lower() == name:
                return e

    @command()
    @cooldown(1, 5, BucketType.user)
    async def emojify(self, ctx, *, text: str):
        """Turns your text without emotes to text with discord custom emotes
        To blacklist words from emoji search use a quoted string at the
        beginning of the command denoting those words
        e.g. emojify "blacklisted words here" rest of the sentence
        This will make sure that the words blacklisted, words and here are not turned into emojis"""
        emojis = ctx.bot.emojis
        new_text = ''
        word_blacklist = None

        # Very simple method to parse word blacklist
        if text.startswith('"'):
            idx = text.find('"', 1)  # Find second quote idx
            word_blacklist = text[1:idx]
            if word_blacklist:
                text = text[idx+1:]
                word_blacklist = [s.lower().strip(',.') for s in word_blacklist.split(' ')]

        if not text:
            await ctx.send('No text given to emojify. Text needs to be given in addition to blacklisted words.')
            return

        emoji_cache = {}
        lines = text.split('\n')
        for line in lines:
            for s in line.split(' '):
                es = s.lower().strip(',.:')
                # We don't want to look for emotes that are only a couple characters long
                if len(s) <= 3 or (word_blacklist and es in word_blacklist):
                    new_text += s + ' '
                    continue

                e = emoji_cache.get(es)
                if not e:
                    e = self.find_emoji(emojis, es)
                    if e is None:
                        e = s
                    else:
                        e = str(e)
                        emoji_cache[es] = e

                new_text += e + ' '

            new_text += '\n'

        await ctx.send(new_text[:2000], undoable=True)

    @command(name='pip', enabled=False)
    @cooldown(1, 5, BucketType.channel)
    @bot_has_permissions(embed_links=True)
    async def get_package(self, ctx, *, name):
        """Get a package from pypi"""
        if SearchCommand is None:
            return await ctx.send('Not supported')

        def search():
            try:
                search_command = SearchCommand('search', 'search command')
                options, _ = search_command.parse_args([name])
                hits = search_command.search(name, options)
                if hits:
                    return hits[0]
            except:
                logger.exception('Failed to search package from PyPi')
                raise

        hit = await self.bot.loop.run_in_executor(self.bot.threadpool, search)
        if not hit:
            return await ctx.send('No matches')

        async with aiohttp.ClientSession() as client:
            async with client.get(f'https://pypi.org/pypi/{quote(hit["name"])}/json') as r:
                if r.status != 200:
                    return await ctx.send(f'HTTP error {r.status}')

                json = await r.json()

        info = json['info']
        description = info['description']
        if len(description) > 1000:
            description = split_string(description, splitter='\n', maxlen=1000)[0] + '...'

        embed = disnake.Embed(title=hit['name'],
                              description=description,
                              url=info["package_url"])
        embed.add_field(name='Author', value=info['author'] or 'None')
        embed.add_field(name='Version', value=info['version'] or 'None')
        embed.add_field(name='License', value=info['license'] or 'None')

        await ctx.send(embed=embed)

    async def get_timezone(self, ctx, user_id: int):
        tz = await self.bot.dbutil.get_timezone(user_id)
        if tz:
            try:
                return await ctx.bot.loop.run_in_executor(ctx.bot.threadpool, pytz.timezone, tz)
            except pytz.UnknownTimeZoneError:
                pass

        return pytz.FixedOffset(0)

    @command(aliases=['tz'])
    @cooldown(2, 7)
    async def timezone(self, ctx, *, timezone: str=None):
        """
        Set or view your timezone. If timezone isn't given shows your current timezone
        If timezone is given sets your current timezone to that.
        Summer time should be supported for any timezone that's not a plain utc offset.
        Due to [technical reasons](https://en.wikipedia.org/wiki/Tz_database#Area)
        the sign in gmt offsets is flipped. e.g. UTC+5 offset is GMT-5
        Examples:
        • `{prefix}{name} utc+4`
        • `{prefix}{name} London`
        • `{prefix}{name} EST`
        """
        user = ctx.author
        if not timezone:
            tz = await self.get_timezone(ctx, user.id)
            s = tz.localize(utcnow()).strftime('Your current timezone is UTC %z')
            await ctx.send(s)
            return

        tz = fuzzy_tz.get(timezone.lower())

        # Extra info to be sent
        extra = ''

        if not tz:
            tz = tz_dict.get(timezone.upper())
            if tz:
                tz = fuzzy_tz.get(f'utc{int(tz)//3600:+d}')

        if not tz:
            await ctx.send(f'Timezone {timezone} not found')
            ctx.command.undo_use(ctx)
            return

        if tz.startswith('Etc/GMT'):
            extra = "UTC offset used. Consider using a locality based timezone instead. " \
                    "You can set it usually by using your country's capital's name or your country's name as long as it has a single timezone\n" \
                    "The sign in the GMT timezone is flipped due to technical reasons."

        if await self.bot.dbutil.set_timezone(user.id, tz):
            await ctx.send(f'Timezone set to {tz}\n{extra}')
        else:
            await ctx.send('Failed to set timezone because of an error')

    @command(name='timedelta', aliases=['td'],
             usage="[duration or date] [timezones and users]")
    @cooldown(1, 3, BucketType.user)
    async def timedelta_(self, ctx, *, args=''):
        """
        Get a date that is in the amount of duration given.
        To get past dates start your duration with `-`
        Time format is `1d 1h 1m 1s` where each one is optional.
        When no time is given it is interpreted as 0 seconds.

        You can also give a date and duration will be calculated as the time to that point in time.
        Timezone will be user timezone by default but you can specify the date utc offset with e.g. UTC+3
        If the date doesn't have spaces in it, put it inside quotes. In ambiguous 3-integer dates day is assumed to be first
        e.g. `"14:00"`, `14:00 UTC+1`, `"Mon 14:00 UTC-3"`

        You can also specify which timezones to use for comparison.
        By default your own timezone is always put at the bottom (defaults to UTC).
        Timezones can be just an integer determining the UTC offset in hours or
        a city name or a country (Not all countries and cities are accepted as input).
        Remember to use quotes if the city name contains spaces.
        You can also give users and their timezone is used if they've set it
        Max given timezones is 5.

        Examples
        `{prefix}{name} 1h ny`
        `{prefix}{name} "Mon 22:00 UTC-3"`
        `{prefix}{name} "Jan 4th 10:00" @user berlin`
        """

        addition = True
        if args.startswith('-'):
            addition = False
            args = args[1:]

        duration, timezones = parse_timeout(args)
        # Used to guess if time with quotes might've been given
        # This way we can give the correct portion of the string to dateutil parser
        quote_start = timezones.startswith('"')
        user_tz = await self.get_timezone(ctx, ctx.author.id)

        timezones = shlex.split(timezones)

        if not duration and timezones:
            try:
                if quote_start:
                    t = timezones[0]
                else:
                    t = ' '.join(timezones[:2])

                def get_date():

                    def get_tz(name, offset):
                        # If name specified get by name
                        if name:
                            found_tz = tz_dict.get(name)
                            if not found_tz:
                                # Default value cannot be None or empty string
                                found_tz = gettz(fuzzy_tz.get(name.lower(), 'a'))

                            return found_tz
                        # if offset specified get by utc offset and reverse it
                        # because https://stackoverflow.com/questions/53076575/time-zones-etc-gmt-why-it-is-other-way-round
                        elif offset:
                            return offset*-1

                    return parser.parse(t.upper(), tzinfos=get_tz, parserinfo=parserinfo)

                date = await self.bot.run_async(get_date)

                if not date.tzinfo:
                    duration = user_tz.localize(date) - datetime.now(user_tz)
                else:
                    # UTC timezones are inverted in dateutil UTC+3 gives UTC-3
                    tz = pytz.FixedOffset(date.tzinfo.utcoffset(utcnow()).total_seconds()//60)
                    duration = date.replace(tzinfo=tz) - datetime.now(user_tz)

                addition = duration.days >= 0

                if not addition:
                    duration *= -1

                if quote_start:
                    timezones = timezones[1:]
                else:
                    timezones = timezones[2:]

            except (ValueError, OverflowError):
                pass

        if len(timezones) > 5:
            await ctx.send('Over 5 timezones given. Give fewer timezones (Use quotes if a tz has spaces)')
            return

        async def add_time(dt: datetime) -> datetime:
            try:
                if addition:
                    return dt + duration
                else:
                    return dt - duration

            except OverflowError:
                await ctx.send('Failed to get new date because of an Overflow error. Try giving a smaller duration')

        tz_converter = TzConverter()
        user_converter = PossibleUser()

        s = ''
        for timezone in timezones:
            try:
                tz = await tz_converter.convert(ctx, timezone)
            except BadArgument as e:
                try:
                    user = await user_converter.convert(ctx, timezone)
                    if isinstance(user, int):
                        tz = await self.get_timezone(ctx, user)
                    else:
                        tz = await self.get_timezone(ctx, user.id)
                except BadArgument:
                    raise e

            dt = await add_time(datetime.now(tz))
            if not dt:
                return

            s += f'`{dt.strftime("%Y-%m-%d %H:%M UTC%z")}` `{tz.zone}`\n'

        dt = await add_time(datetime.now(user_tz))
        if not dt:
            return

        s += f'`{dt.strftime("%Y-%m-%d %H:%M UTC%z")}` `{user_tz.zone}`\n'

        td = format_timedelta(duration, accuracy=DateAccuracy.Day-DateAccuracy.Minute)

        if addition:
            s += f'which is in {td}'
        else:
            s += f'which was {td} ago'

        await ctx.send(s)

    @command(aliases=['st'])
    @cooldown(1, 4, BucketType.user)
    async def sort_tags(self, ctx, tagname, *, tags):
        """Gets missing tag indexes from a 42 bot tag search.
        The first tagname must be the one that is gonna be looked for"""
        tagname = tagname.rstrip(',')
        tags = tags.split(', ')
        match = re.match(r'(.+?)(\d+)', tagname)
        numbers = set()
        if match:
            tagname, number = match.groups()
            numbers.add(int(number))
        else:
            numbers.add(0)

        tagname = tagname.lstrip('\u200b')

        tl = len(tagname)
        for tag in tags:
            if tag.endswith('...'):
                continue
            if tagname not in tag:
                continue

            if tagname == tag:
                numbers.add(0)
                continue

            try:
                # Ignore long numbers
                n = tag[tl:]
                if len(n) > 4:
                    continue

                numbers.add(int(n))
            except ValueError:
                continue

        if not numbers:
            await ctx.send(f'No other numbered tags found for {tagname}')
            return

        numbers = list(sorted(numbers))
        last = numbers[0]

        if last > 2:
            s = f'-{last - 1}, '
        else:
            s = ''

        for i in numbers[1:]:
            delta = i - last
            if delta > 4:
                s += f'{last + 1}-{i - 1}, '
            elif delta == 3:
                s += f'{last + 1}, {i - 1}, '
            elif delta == 2:
                s += f'{i - 1}, '

            last = i

        s += f'{last+1}-'
        await ctx.send(f'Missing tag numbers for {tagname} are {s}')

    @command(aliases=['who', 'user', 'whois'])
    @cooldown(7, 10, BucketType.guild)
    async def userinfo(self, ctx: Context, *, user: Union[disnake.Member, disnake.User]):
        """
        Shows info of a user.
        Using the username might not always work.  In those cases use the user id
        """
        embed = disnake.Embed(title=str(user))
        embed.set_thumbnail(url=get_avatar(user))
        embed.add_field(name='Username', value=str(user))
        embed.add_field(name='ID', value=str(user.id))

        embed.add_field(
            name='Created at',
            value=disnake.utils.format_dt(user.created_at, 'R')
        )

        if isinstance(user, disnake.Member):
            embed.add_field(
                name='Joined at',
                value=disnake.utils.format_dt(user.joined_at, 'R')
            )

            max_roles = 20
            embed.add_field(
                name='Roles',
                value=' '.join([r.mention for r in reversed(user.roles[-max_roles:])]) +
                      (f' and {len(user.roles)-max_roles} more' if len(user.roles) > max_roles else ''),
                inline=False
            )

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Utilities(bot))
