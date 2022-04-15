import argparse
import asyncio
import contextlib
import functools
import inspect
import logging
import os
import pprint
import re
import shlex
import subprocess
import textwrap
import time
import traceback
import typing
from datetime import datetime
from enum import IntEnum
from importlib import reload, import_module
from io import BytesIO, StringIO
from pprint import PrettyPrinter
from py_compile import PyCompileError
from typing import Optional

import aiohttp
import disnake
import matplotlib.pyplot as plt
from aioredis import Redis
from asyncpg.exceptions import PostgresError
from disnake import File
from disnake.errors import HTTPException, InvalidArgument
from disnake.ext.commands.errors import ExtensionError, ExtensionFailed
from disnake.user import BaseUser
from matplotlib.dates import AutoDateLocator, DateFormatter
from matplotlib.ticker import MultipleLocator

from bot.bot import command
from bot.config import Config
from bot.converters import PossibleUser, CommandConverter
from bot.globals import SFX_FOLDER
from cogs.cog import Cog
from utils.utilities import split_string, utcnow
from utils.utilities import (y_n_check, basic_check, y_check, check_import,
                             parse_timeout, is_owner, format_timedelta,
                             call_later, seconds2str, test_url,
                             wants_to_be_noticed, DateAccuracy)

logger = logging.getLogger('terminal')


class ExitStatus(IntEnum):
    PreventRestart = 2
    ForceRestart = 3
    RestartNormally = 0


class NoStringWrappingPrettyPrinter(PrettyPrinter):
    @staticmethod
    def _format_str(s):
        if '\n' in s:
            s = f'"""{s}"""'
        else:
            s = f'"{s}"'

        return s

    def _format(self, obj, stream, *args, **kwargs):  # skipcq: PYL-W0221
        if isinstance(obj, str):
            stream.write(self._format_str(obj))
        else:
            super()._format(obj, stream, *args, **kwargs)


class NonFormatted:
    def __init__(self, original):
        self.original = original


class BotAdmin(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._last_result = None

        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('-sql', '-s', required=True)
        self.parser.add_argument('-xlabel', '-xl', default=None)
        self.parser.add_argument('-ylabel', '-yl', default=None)
        self.parser.add_argument('--date-fmt', '-df', default='%Y-%m-%d')
        self.parser.add_argument('-type', '-t', default='plot', choices=['plot', 'hist'])
        self.parser.add_argument('-fmt', default='bo--')
        self.parser.add_argument('-x_int', '-xi', action='store_true')
        self.parser.add_argument('-y_int', '-yi', action='store_true')

    def cog_check(self, ctx):
        return is_owner(ctx)

    def _reload_extension(self, name):
        t = time.perf_counter()
        # Check that the module is importable
        try:
            # Check if code compiles. If not returns the error
            # Only check this cog as the operation takes a while and
            # Other cogs can be reloaded if they fail unlike this
            if name == 'cogs.botadmin':
                check_import(name)

        except PyCompileError:
            logger.exception(f'Failed to reload extension {name}')
            return f'Failed to import module {name}.\nError has been logged'

        try:
            self.bot.reload_extension(name)

        # We wanna exclude ExtensionFailed errors since they can contain sensitive
        # data because they give the contents of the parent error message
        except ExtensionFailed as e:
            logger.exception(f'Failed to reload extension {name}')
            return f'Could not reload {name} because of {type(e).__name__}\nCheck logs for more info'

        except ExtensionError as e:
            logger.exception(f'Failed to reload {name}')
            return f'Could not reload {name} because of an error\n{e}'

        except Exception as e:
            logger.exception(f'Failed to reload {name}')
            return f'Could not reload {name} because of an error {type(e).__name__}'

        return 'Reloaded {} in {:.0f}ms'.format(name, (time.perf_counter() - t) * 1000)

    def reload_extension(self, name):
        """
        Reload an cog with the given import path
        """
        return self._reload_extension(name)

    def reload_extensions(self, names):
        """
        Same as reload_extension but for multiple files
        We are using 2 functions to optimize the usage of run_in_executor
        """
        if not names:
            # We want to return a tuple
            return "No module names given",  # skipcq: PYL-R1707

        messages = []

        for name in names:
            messages.append(self._reload_extension(name))

        return split_string(messages, list_join='\n', splitter='\n')

    @command(name='eval')
    async def eval_(self, ctx, *, code: str):
        context = globals().copy()
        context.update({'ctx': ctx,
                        'author': ctx.author,
                        'guild': ctx.guild,
                        'message': ctx.message,
                        'channel': ctx.channel,
                        'bot': ctx.bot,
                        'loop': ctx.bot.loop,
                        '_': self._last_result})

        # A quick hack to run async functions in normal function
        # It's not pretty but it does what it needs
        def disgusting(coro_or_fut):
            if isinstance(coro_or_fut, asyncio.Future):
                return asyncio.run_coroutine_threadsafe(asyncio.wait_for(coro_or_fut, 60), loop=ctx.bot.loop).result()
            return asyncio.run_coroutine_threadsafe(coro_or_fut, loop=ctx.bot.loop).result()

        # Gets source of object
        def get_source(o):
            source = inspect.getsource(o)
            original_source = textwrap.dedent(source)
            # Put zero width space between backticks so they can be within a codeblock
            source = original_source.replace('```', '`\u200b`\u200b`')
            source = f'```py\n{source}\n```'
            if len(source) > 2000:
                return original_source

            return source

        def no_pformat(o):
            return NonFormatted(o)

        def code_block(s, pretty_print=True):
            if not isinstance(s, str) or pretty_print:
                s = NoStringWrappingPrettyPrinter(width=1).pformat(s)

            return f'```py\n{s}\n```'

        context['await'] = disgusting
        context['awaitt'] = disgusting
        context['source'] = get_source
        context['src'] = get_source
        context['code_block'] = code_block
        context['no_format'] = no_pformat

        if code.startswith('```py\n') and code.endswith('\n```'):
            code = code[6:-4]

        code = textwrap.indent(code, '  ')
        lines = list(filter(bool, code.split('\n')))
        last = lines[-1]
        if not last.strip().startswith('return'):
            whitespace = len(last) - len(last.strip())
            if whitespace > 2:
                lines.append('  return')
            else:
                lines[-1] = '  return ' + last.strip()  # if code doesn't have a return make one

        lines = '\n'.join(lines)
        code = f'def f():\n{lines}'  # Transform the code to a function

        try:
            stdout = StringIO()

            def run():
                exec(compile(code, '<eval>', 'exec'), context)
                with contextlib.redirect_stdout(stdout):
                    return context['f']()

            retval = await self.bot.loop.run_in_executor(self.bot.threadpool, run)
            self._last_result = retval

        except Exception as e:
            self._last_result = e
            retval = f'```py\n{e}\n{traceback.format_exc()}\n```'
        else:
            if retval is not None:
                if not isinstance(retval, str) and not isinstance(retval, NonFormatted):
                    retval = NoStringWrappingPrettyPrinter(width=1).pformat(retval)
                retval = f'{retval}\n{stdout.getvalue()}'
            else:
                retval = f'{stdout.getvalue()}'

        if len(retval) > 2000:
            await ctx.send(file=disnake.File(StringIO(retval), filename='result.py'))
        else:
            await ctx.send(retval or '[None]')

    @command(name='exec')
    async def exec_(self, ctx, *, message):
        context = globals().copy()
        context.update({'ctx': ctx,
                        'author': ctx.author,
                        'guild': ctx.guild,
                        'message': ctx.message,
                        'channel': ctx.channel,
                        'bot': ctx.bot})

        try:
            retval = await self.bot.loop.run_in_executor(self.bot.threadpool, exec, message, context)
            if asyncio.iscoroutine(retval):
                retval = await retval

        except Exception as e:
            logger.exception('Failed to eval')
            retval = 'Exception\n%s' % e.__name__

        if not isinstance(retval, str):
            retval = str(retval)

        await ctx.send(retval)

    @command()
    async def dbeval(self, ctx, *, query):
        # Choose between fetch and execute based on first keyword
        query = query.strip('`')
        if query.lower().startswith('select '):
            f = self.bot.dbutil.fetch(query, measure_time=True)
        else:
            f = self.bot.dbutil.execute(query, measure_time=True)

        try:
            rows, t = await f
        except PostgresError:
            logger.exception('Failed to execute eval query')
            return await ctx.send('Failed to execute query. Exception logged')

        embed = disnake.Embed(title='sql', description=f'Query ran succesfully in {t*1000:.0f} ms')
        embed.add_field(name='input', value=f'```sql\n{query}\n```', inline=False)

        if not isinstance(rows, str):
            if len(rows) > 30:
                value = f'Too many results {len(rows)} > 30'
            else:
                value = '```py\n' + pprint.pformat(rows, compact=True)[:1000] + '```'

        else:
            value = f'```sql\n{rows}```'

        embed.add_field(name='output', value=value, inline=False)
        await ctx.send(embed=embed)

    @command()
    async def reload(self, ctx, *names):
        cog_names = ['cogs.' + name if not name.startswith('cogs.') else name for name in names]
        msgs = self.reload_extensions(cog_names)
        for msg in split_string(msgs, list_join='\n'):
            await ctx.send(msg)

    @command()
    async def reload_all(self, ctx):
        messages = self.reload_extensions(self.bot.default_cogs)
        for msg in split_string(messages, list_join='\n'):
            await ctx.send(msg)

    @command()
    async def load(self, ctx, cog):
        cog_name = 'cogs.%s' % cog if not cog.startswith('cogs.') else cog
        t = time.perf_counter()
        try:
            await self.bot.loop.run_in_executor(self.bot.threadpool,
                                                self.bot.load_extension, cog_name)
        except Exception as e:
            logger.exception('Failed to load')
            return await ctx.send('Could not load %s because of %s' % (cog_name, e.__class__.__name__))

        await ctx.send('Loaded {} in {:.0f}ms'.format(cog_name, (time.perf_counter() - t) * 1000))

    @command()
    async def unload(self, ctx, cog):
        cog_name = 'cogs.%s' % cog if not cog.startswith('cogs.') else cog
        t = time.perf_counter()
        try:
            await self.bot.loop.run_in_executor(self.bot.threadpool,
                                                self.bot.unload_extension, cog_name)
        except Exception as e:
            return await ctx.send('Could not unload %s because of %s' % (cog_name, e.__class__.__name__))

        await ctx.send('Unloaded {} in {:.0f}ms'.format(cog_name, (time.perf_counter() - t) * 1000))

    @command()
    async def shutdown(self, ctx):
        await self._shutdown(ctx, ExitStatus.PreventRestart)

    @command(aliases=['reboot'])
    async def restart(self, ctx):
        await self._shutdown(ctx, ExitStatus.ForceRestart)

    async def _shutdown(self, ctx, exit_code: ExitStatus):
        try:
            await ctx.send('Beep boop :wave:')
        except HTTPException:
            pass

        self.bot._exit_code = int(exit_code)

        redis: Optional[Redis] = getattr(self.bot, 'redis', None)
        if redis:
            try:
                await redis.close()
            except:
                logger.exception('Failed to gracefully close redis')

        try:
            audio = self.bot.get_cog('Audio')
            if audio:
                await audio.shutdown()

        except Exception:
            logger.exception('Failed to shutdown audio')

        try:
            logger.info('Logging out')
            await self.bot.close()
            logger.info('Logged out')
        except asyncio.exceptions.CancelledError:
            pass
        except:
            logger.exception('Failed to close bot')

        try:
            await self._bot.pool.close()
        except asyncio.exceptions.CancelledError:
            pass
        except:
            logger.exception('Failed to shut db down gracefully')
        else:
            logger.info('Closed db connection')

    @command()
    async def notice_me(self, ctx):
        guild = ctx.message.guild
        if guild.id == 217677285442977792:
            try:
                await guild.chunk()
            except InvalidArgument:
                pass

            added = 0
            removed = 0
            for member in list(guild.members):
                res = await wants_to_be_noticed(member, guild)
                if res is True:
                    added += 1
                elif res is False:
                    removed += 1

            await ctx.send(f'Added attention whore to {added} members and removed it from {removed} members')

    @command()
    async def reload_dbutil(self, ctx):
        reload(import_module('bot.dbutil'))
        from bot import dbutil
        self.bot._dbutil = dbutil.DatabaseUtils(self.bot)
        await ctx.send(':ok_hand:')

    @command()
    async def reload_help(self, ctx):
        reload(import_module('bot.formatter'))
        from bot.formatter import HelpCommand
        self.bot.help_command = HelpCommand()
        await ctx.send(':ok_hand:')

    @command()
    async def reload_config(self, ctx):
        try:
            config = Config()
        except:
            logger.exception('Failed to reload config')
            await ctx.send('Failed to reload config')
            return

        self.bot.config = config
        await ctx.send(':ok_hand:')

    @command()
    async def cache_guilds(self, ctx):
        for guild in self.bot.guilds:
            sql = 'SELECT * FROM `guilds` WHERE guild=%s' % guild.id
            row = await self.bot.dbutil.execute(sql).first()
            if not row:
                sql = 'INSERT INTO `guilds` (`guild`, `prefix`) ' \
                      'VALUES (%s, "%s")' % (guild.id, self.bot.command_prefix)
                try:
                    await self.bot.dbutil.execute(sql)
                except PostgresError:
                    logger.exception('Failed to cache guild')

                d = {'prefix': self.bot.command_prefix}
            else:
                d = {**row}
                del d['guild']

            self.bot.guild_cache.update_guild(guild.id, **d)

        await ctx.send('Done caching guilds')

    @command()
    async def reload_module(self, ctx, module_name):
        try:
            reload(import_module(module_name))
        except Exception as e:  # skipcq: PYL-W0703
            return await ctx.send('Failed to reload module %s because of %s' % (module_name, e.__name__))
        await ctx.send('Reloaded module %s' % module_name)

    @command()
    async def runas(self, ctx, *, user: disnake.User=None):
        self.bot._runas = user
        await ctx.send(f'Now running as {user}')

    @command()
    async def update_bot(self, ctx, *, options=None):
        """Does a git pull"""
        cmd = 'git pull'.split(' ')
        if options:
            cmd.extend(shlex.split(options))

        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = await self.bot.loop.run_in_executor(self.bot.threadpool, p.communicate)
        out = out.decode('utf-8')
        if err:
            out = err.decode('utf-8') + out

        # Only tries to update files in the cogs folder
        files = re.findall(r'(cogs/\w+)(?:.py *|)', out)

        if len(out) > 2000:
            out = out[:1996] + '...'

        await ctx.send(out)

        if files:
            files = [f.replace('/', '.') for f in files]
            await ctx.send(f'Do you want to reload files `{"` `".join(files)}`')

            try:
                msg = await self.bot.wait_for('message', check=basic_check(ctx.author, ctx.channel), timeout=30)
            except asyncio.TimeoutError:
                return await ctx.send('Timed out')

            if not y_n_check(msg):
                return await ctx.send('Invalid answer. Not auto reloading')

            if not y_check(msg.content):
                return await ctx.send('Not auto updating')

            messages = self.reload_extensions(files)
            for msg in messages:
                await ctx.send(msg)

    @command()
    async def add_sfx(self, ctx, file=None, name=None):
        if file and name:
            url = file
        elif not file:
            if not ctx.message.attachments:
                return await ctx.send('No files found')

            url = ctx.message.attachments[0].url
            name = url.split('/')[-1]

        else:
            if not test_url(file):
                if not ctx.message.attachments:
                    return await ctx.send('No files found')

                url = ctx.message.attachments[0].url
                name = file
            else:
                url = file
                name = url.split('/')[-1]

        p = os.path.join(SFX_FOLDER, name)
        if os.path.exists(p):
            return await ctx.send(f'File {name} already exists')

        try:
            async with aiohttp.ClientSession() as client:
                async with client.get(url) as r:
                    data = BytesIO()
                    chunk = 4096
                    async for d in r.content.iter_chunked(chunk):
                        data.write(d)
            data.seek(0)

        except aiohttp.ClientError:
            logger.exception(f'Could not download image {url}')
            await ctx.send('Failed to download %s' % url)
        else:
            def write():
                with open(p, 'wb') as f:
                    f.write(data.getvalue())

            if os.path.exists(p):
                return await ctx.send(f'File {name} already exists')

            await self.bot.loop.run_in_executor(self.bot.threadpool, write)
            await ctx.send(f'Added sfx {name}')

    @command()
    async def botban(self, ctx, user: PossibleUser, *, reason):
        """
        Ban someone from using this bot. Owner only
        """
        if isinstance(user, BaseUser):
            name = user.name + ' '
            user_id = user.id

        else:
            name = ''
            user_id = user

        try:
            await self.bot.dbutil.botban(user_id, reason)
        except PostgresError:
            logger.exception(f'Failed to botban user {name}{user_id}')
            return await ctx.send(f'Failed to ban user {name}`{user_id}`')

        await ctx.send(f'Banned {name}`{user_id}` from using this bot')

    @command()
    async def botunban(self, ctx, user: PossibleUser):
        """
        Remove someones botban
        """
        if isinstance(user, BaseUser):
            name = user.name + ' '
            user_id = user.id

        else:
            name = ''
            user_id = user

        try:
            await self.bot.dbutil.botunban(user_id)
        except PostgresError:
            logger.exception(f'Failed to remove botban of user {name}{user_id}')
            return await ctx.send(f'Failed to remove botban of user {name}`{user_id}`')

        await ctx.send(f'Removed the botban of {name}`{user_id}`')

    @command()
    async def leave_guild(self, ctx, guild_id: int):
        g = self.bot.get_guild(guild_id)
        if not g:
            return await ctx.send(f'Guild {guild_id} not found')

        await g.leave()
        await ctx.send(f'Left guild {g.name} `{g.id}`')

    @command()
    async def blacklist_guild(self, ctx, guild_id: int, *, reason):
        try:
            await self.bot.dbutil.blacklist_guild(guild_id, reason)
        except PostgresError:
            logger.exception('Failed to blacklist guild')
            return await ctx.send('Failed to blacklist guild\nException has been logged')

        guild = self.bot.get_guild(guild_id)
        if guild:
            await guild.leave()

        s = f'{guild} `{guild_id}`' if guild else guild_id
        await ctx.send(f'Blacklisted guild {s}')

    @command()
    async def unblacklist_guild(self, ctx, guild_id: int):
        try:
            await self.bot.dbutil.unblacklist_guild(guild_id)
        except PostgresError:
            logger.exception('Failed to unblacklist guild')
            return await ctx.send('Failed to unblacklist guild\nException has been logged')

        guild = self.bot.get_guild(guild_id)
        s = f'{guild} `{guild_id}`' if guild else guild_id
        await ctx.send(f'Unblacklisted guild {s}')

    @command()
    async def reload_redis(self, ctx):
        from aioredis.client import Redis
        logger.exception('Connection closed. Reconnecting')
        redis = self.bot.create_redis()

        old: Redis = self.bot.redis
        await old.close()
        self.bot.redis = redis
        del old

        await ctx.send('Reloaded redis')

    def remove_call(self, _, msg_id):
        self.bot.call_laters.pop(msg_id, None)

    @command()
    async def call_later(self, ctx, *, call):
        msg = ctx.message
        # Parse timeout can basically parse anything where you want time
        # separated from the rest
        run_in, call = parse_timeout(call)
        msg.content = f'{ctx.prefix}{call}'
        new_ctx = await self.bot.get_context(msg)
        self.bot.call_laters[msg.id] = call_later(self.bot.invoke, self.bot.loop,
                                                  run_in.total_seconds(), new_ctx,
                                                  after=functools.partial(self.remove_call, msg_id=msg.id))

        await ctx.send(f'Scheduled call `{msg.id}` to run in {seconds2str(run_in.total_seconds(), False)}')

    @command()
    async def add_todo(self, ctx, priority: int=0, *, todo):
        try:
            rowid = await self.bot.dbutil.add_todo(todo, priority=priority)
        except PostgresError:
            logger.exception('Failed to add todo')
            return await ctx.send('Failed to add to todo')

        await ctx.send(f'Added todo with priority {priority} and id {rowid}')

    @command()
    async def todo_priority(self, ctx, id: int, priority: int):
        try:
            await self.bot.dbutil.edit_todo(id, priority)
        except PostgresError:
            logger.exception('Failed to edit todo')
            await ctx.send('Failed to edit todo priority')
            return

        await ctx.send(f'Set the priority of {id} to {priority}')

    @command(name='todo')
    async def list_todo(self, ctx, limit: int=10):
        try:
            rows = await self.bot.dbutil.get_todo(limit)
        except PostgresError:
            logger.exception('Failed to get todo')
            return await ctx.send('Failed to get todo')

        if not rows:
            return await ctx.send('Nothing to do')

        s = ''
        for row in rows:
            s += f'ID: {row["id"]} at {format_timedelta(utcnow() - row["time"], DateAccuracy.Day)} `{row["priority"]}` {row["todo"]}\n\n'

        if len(s) > 2000:
            return await ctx.send('Too long todo')

        await ctx.send(s)

    @command()
    async def complete_todo(self, ctx, id: int):
        sql = 'UPDATE todo SET completed_at=CURRENT_TIMESTAMP, completed=TRUE WHERE id=%s AND completed=FALSE' % id

        res = await self.bot.dbutil.execute(sql)
        await ctx.send(f'{res.split(" ")[-1]} rows updated')

    @command()
    async def reset_cooldown(self, ctx, cmd: CommandConverter):
        cmd.reset_cooldown(ctx)
        await ctx.send(f'Cooldown of {cmd.name} reset')

    @command()
    async def send_message(self, ctx, channel: typing.Union[disnake.TextChannel, disnake.User], *, message):
        try:
            await channel.send(message)
        except disnake.HTTPException as e:
            await ctx.send(f'Failed to send message\n```py\n{e}\n```')
        except:
            await ctx.send('Failed to send message')
        else:
            await ctx.send(f'Message sent to {channel}')

    @command(aliases=['add_changelog'])
    async def add_changes(self, ctx, *, changes):
        try:
            rowid = await self.bot.dbutil.add_changes(changes)
        except PostgresError:
            logger.exception('Failed to add changes')
            return await ctx.send('Failed to add to todo')

        await ctx.send(f'Added changes with id {rowid}')

    @command()
    async def disable(self, ctx, cmd: CommandConverter):
        if cmd == self.disable:  # skipcq: PYL-W0143
            await ctx.send('Cannot disable this command')
            return

        cmd.enabled = False
        await ctx.send(f'Disabled {cmd.name}')

    @command()
    async def enable(self, ctx, cmd: CommandConverter):
        cmd.enabled = True
        await ctx.send(f'Enabled {cmd.name}')

    @command()
    async def graph_eval(self, ctx, *, args):
        """
        -sql, -s: sql statement to fetch data. Should return list of [x, y] rows.
        -xlabel, -xl: Label for x axis. If not specified both labels will be read from the sql columns.
        -ylabel, -yl: Label for y axis. Must be specified if -xlabel is specified.
        --date-fmt, -df: Format for dates. Default '%Y-%m-%d'
        -type, -t: Type of plot to be drawn. Default is 'plot'. Must be one of 'plot', 'hist'
        -fmt: plot string format. Default is 'bo--'. [More info](https://matplotlib.org/api/_as_gen/matplotlib.pyplot.plot.html)
        -x_int, -xi: If given will set x-axis ticks to integers
        -y_int, -yi: If given will set y-axis ticks to integers
        """
        try:
            parsed = self.parser.parse_args(shlex.split(args))
        except SystemExit:
            await ctx.send('Failed to parse arguments')
            return

        sql = parsed.sql

        try:
            rows = await self.bot.dbutil.fetch(sql)
        except PostgresError:
            logger.exception('Failed to execute sql')
            await ctx.send('Failed to execute sql')
            return

        if not rows:
            await ctx.send('No plot data')
            return

        type_ = parsed.type
        fmt = parsed.fmt
        xlabel: str = parsed.xlabel
        ylabel: str = parsed.ylabel

        if xlabel is None:
            xlabel, ylabel = rows[0].keys()

        def do_plot():
            buf = None
            try:
                fig = plt.figure()
                ax = fig.gca()

                if type_ == 'hist':
                    plt.hist([float(row[0]) for row in rows], bins=20, range=(0, 1))
                elif type_ == 'plot':
                    plt.plot(
                        [row[0] for row in rows],
                        [row[1] for row in rows],
                        fmt
                    )

                plt.xlabel(xlabel.title())
                plt.ylabel(ylabel.title())
                if parsed.x_int:
                    ax.xaxis.set_major_locator(MultipleLocator(1))
                if parsed.y_int:
                    ax.yaxis.set_major_locator(MultipleLocator(1))

                if isinstance(rows[0][0], datetime):
                    ax.xaxis.set_major_locator(AutoDateLocator())
                    ax.xaxis.set_major_formatter(DateFormatter(parsed.date_fmt))
                    fig.autofmt_xdate()
                if isinstance(rows[0][1], datetime):
                    ax.yaxis.set_major_locator(AutoDateLocator())
                    ax.yaxis.set_major_formatter(DateFormatter(parsed.date_fmt))

                buf = BytesIO()
                plt.savefig(buf, format='png', bbox_inches='tight')
                buf.seek(0)
            except:
                logger.exception('Failed to create plot')
                buf = None
            finally:
                plt.close()
                return buf

        await ctx.trigger_typing()
        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_plot)

        if not data:
            await ctx.send('Failed to create plot')
            return

        await ctx.send(file=File(data, 'plot.png'))


def setup(bot):
    bot.add_cog(BotAdmin(bot))
