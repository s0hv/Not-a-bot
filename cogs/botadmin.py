import asyncio
import functools
import inspect
import logging
import os
import pprint
import re
import shlex
import subprocess
import sys
import textwrap
import time
import traceback
from enum import IntEnum
from importlib import reload, import_module
from io import BytesIO, StringIO
from pprint import PrettyPrinter
from types import ModuleType

import aiohttp
import discord
from discord.errors import HTTPException, InvalidArgument
from discord.ext.commands.core import GroupMixin
from discord.user import BaseUser
from sqlalchemy.exc import SQLAlchemyError

from bot.bot import command
from bot.config import Config
from bot.converters import PossibleUser
from bot.globals import SFX_FOLDER
from cogs.cog import Cog
from utils.utilities import split_string
from utils.utilities import (y_n_check, basic_check, y_check, check_import,
                             parse_timeout,
                             call_later, seconds2str)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class ExitStatus(IntEnum):
    PreventRestart = 2
    ForceRestart = 3
    RestartNormally = 0


class NoStringWrappingPrettyPrinter(PrettyPrinter):
    def _format_str(self, s):
        if '\n' in s:
            s = f'"""{s}"""'
        else:
            s = f'"{s}"'

        return s

    def _format(self, object, stream, *args):
        if isinstance(object, str):
            stream.write(self._format_str(object))
        else:
            super()._format(object, stream, *args)


class NonFormatted:
    def __init__(self, original):
        self.original = original


class BotAdmin(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._last_result = None

    def load_extension(self, name, lib=None):
        """
        Reworked implementation of the default bot extension loader
        It works exactly the same unless you provide the lib argument manually
        That way you can import the lib before this method to check for
        errors in the file and pass the returned lib to this function if no errors were thrown.

        Args:
            name: str
                name of the extension
            lib: Module
                lib returned from `import_module`
        Raises:
            ClientException
                Raised when no setup function is found or when lib isn't a valid module
        """
        if lib is None:
            # Fall back to default implementation when lib isn't provided
            return self.bot.load_extension(name)

        if name in self.bot.extensions:
            return

        if not isinstance(lib, ModuleType):
            raise discord.ClientException("lib isn't a valid module")

        lib = import_module(name)
        if not hasattr(lib, 'setup'):
            del lib
            del sys.modules[name]
            raise discord.ClientException('extension does not have a setup function')

        lib.setup(self.bot)
        self.bot.extensions[name] = lib

    async def reload_extension(self, name):
        """
        Reload an cog with the given import path
        """
        def do_reload():
            t = time.perf_counter()
            # Check that the module is importable
            try:
                # Check if code compiles. If not returns the error
                # Only check this cog as the operation takes a while and
                # Other cogs can be reloaded if they fail unlike this
                if name == 'cogs.botadmin':
                    e = check_import(name)
                    if e:
                        return f'```py\n{e}\n```'

                lib = import_module(name)
            except:
                logger.exception(f'Failed to reload extension {name}')
                return f'Failed to import module {name}.\nError has been logged'

            try:
                self.bot.unload_extension(name)
                self.load_extension(name, lib=lib)
            except Exception:
                logger.exception('Failed to reload extension %s' % name)
                terminal.exception('Failed to reload extension %s' % name)
                return 'Could not reload %s because of an error' % name

            return 'Reloaded {} in {:.0f}ms'.format(name, (time.perf_counter()-t)*1000)

        return await self.bot.loop.run_in_executor(self.bot.threadpool, do_reload)

    async def reload_multiple(self, names):
        """
        Same as reload_extension but for multiple files
        """
        if not names:
            return "No module names given",

        messages = []

        def do_reload():

            for name in names:
                t = time.perf_counter()
                # Check that the module is importable
                try:
                    # Check if code compiles. If not returns the error
                    # Only check this cog as the operation takes a while and
                    # Other cogs can be reloaded if they fail unlike this
                    if name == 'cogs.botadmin':
                        e = check_import(name)
                        if e:
                            return f'```py\n{e}\n```'

                    lib = import_module(name)
                except:
                    logger.exception(f'Failed to reload extension {name}')
                    messages.append(f'Failed to import module {name}.\nError has been logged')
                    continue

                try:
                    self.bot.unload_extension(name)
                    self.load_extension(name, lib=lib)
                except Exception:
                    logger.exception('Failed to reload extension %s' % name)
                    messages.append('Could not reload %s because of an error' % name)
                    continue

                t = time.perf_counter() - t
                messages.append('Reloaded {} in {:.0f}ms'.format(name, t * 1000))

            return messages

        return await self.bot.loop.run_in_executor(self.bot.threadpool, do_reload)

    @command(name='eval', owner_only=True)
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
                return asyncio.run_coroutine_threadsafe(asyncio.wait_for(coro_or_fut, 60, loop=ctx.bot.loop), loop=ctx.bot.loop).result()
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
        context['source'] = get_source
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
        code = f'def f():\n{lines}\nx = f()'  # Transform the code to a function
        local = {}  # The variables outside of the function f() get stored here

        try:
            def run():
                exec(compile(code, '<eval>', 'exec'), context, local)
            await self.bot.loop.run_in_executor(self.bot.threadpool, run)
            retval = local['x']
            self._last_result = retval
            if not isinstance(retval, str) and not isinstance(retval, NonFormatted):
                retval = NoStringWrappingPrettyPrinter(width=1).pformat(retval)
        except Exception as e:
            self._last_result = e
            retval = f'```py\n{e}\n{traceback.format_exc()}\n```'

        if not isinstance(retval, str):
            retval = str(retval)

        if len(retval) > 2000:
            await ctx.send(file=discord.File(StringIO(retval), filename='result.py'))
        else:
            await ctx.send(retval)

    @command(name='exec', owner_only=True)
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

    @command(owner_only=True, aliases=['db_eval'])
    async def dbeval(self, ctx, *, query):
        try:
            r, t = await self.bot.dbutil.execute(query, commit=True, measure_time=True)
        except SQLAlchemyError:
            logger.exception('Failed to execute eval query')
            return await ctx.send('Failed to execute query. Exception logged')

        embed = discord.Embed(title='sql', description=f'Query ran succesfully in {t*1000:.0f} ms')
        embed.add_field(name='input', value=f'```sql\n{query}\n```', inline=False)

        if r.returns_rows:
            rows = r.fetchall()
            if len(rows) > 30:
                value = f'Too many results {len(rows)} > 30'
            else:
                value = '```py\n' + pprint.pformat(rows, compact=True)[:1000] + '```'

        else:
            value = f'{r.rowcount} rows were inserted/modified/deleted'

        embed.add_field(name='output', value=value, inline=False)
        await ctx.send(embed=embed)

    def _recursively_remove_all_commands(self, command, bot=None):
        commands = []
        for _command in command.commands.copy().values():
            if isinstance(_command, GroupMixin):
                l = self._recursively_remove_all_commands(_command)
                command.remove_command(_command.name)
                commands.append(l)
            else:
                commands.append(command.remove_command(_command.name))

        if bot:
            bot.remove_command(command.name)
        return command, commands

    def _recursively_add_all_commands(self, commands, bot):
        for command_ in commands:
            if isinstance(command_, tuple):
                command_, commands_ = command_
                bot.add_command(command_)
                self._recursively_add_all_commands(commands_, command_)
            else:
                bot.add_command(command_)

    @command(owner_only=True)
    async def reload(self, ctx, *, name):
        cog_name = 'cogs.%s' % name if not name.startswith('cogs.') else name
        await ctx.send(await self.reload_extension(cog_name))

    @command(owner_only=True)
    async def reload_all(self, ctx):
        messages = await self.reload_multiple(self.bot.default_cogs)
        messages = split_string(messages, list_join='\n', splitter='\n')
        for msg in messages:
            await ctx.send(msg)

    @command(owner_only=True)
    async def load(self, ctx, cog):
        cog_name = 'cogs.%s' % cog if not cog.startswith('cogs.') else cog
        t = time.perf_counter()
        try:
            await self.bot.loop.run_in_executor(self.bot.threadpool,
                                                self.bot.load_extension, cog_name)
        except Exception as e:
            logger.exception('Failed to load')
            return await ctx.send('Could not load %s because of %s' % (cog_name, e.__name__))

        await ctx.send('Loaded {} in {:.0f}ms'.format(cog_name, (time.perf_counter() - t) * 1000))

    @command(owner_only=True)
    async def unload(self, ctx, cog):
        cog_name = 'cogs.%s' % cog if not cog.startswith('cogs.') else cog
        t = time.perf_counter()
        try:
            await self.bot.loop.run_in_executor(self.bot.threadpool,
                                                self.bot.unload_extension, cog_name)
        except Exception as e:
            return await ctx.send('Could not unload %s because of %s' % (cog_name, e.__name__))

        await ctx.send('Unloaded {} in {:.0f}ms'.format(cog_name, (time.perf_counter() - t) * 1000))

    @command(owner_only=True)
    async def shutdown(self, ctx):
        await self._shutdown(ctx, ExitStatus.PreventRestart)

    @command(owner_only=True)
    async def restart(self, ctx):
        await self._shutdown(ctx, ExitStatus.ForceRestart)

    async def _shutdown(self, ctx, exit_code):
        try:
            await ctx.send('Beep boop :wave:')
        except HTTPException:
            pass

        logger.info('Unloading extensions')

        def unload_all():
            for ext in list(self.bot.extensions.keys()):
                try:
                    self.bot.unload_extension(ext)
                except:
                    pass

        logger.info('Unloaded extensions')
        await self.bot.loop.run_in_executor(self.bot.threadpool, unload_all)
        await self.bot.aiohttp_client.close()
        logger.info('Closed aiohttp client')

        redis = getattr(self.bot, 'redis', None)
        if redis:
            redis.close()
            await redis.wait_closed()

        try:
            audio = self.bot.get_cog('Audio')
            if audio:
                await audio.shutdown()

            try:
                logger.info('Logging out')
                await self.bot.logout()
                logger.info('Logged out')
            except:
                pass


            try:
                session = self.bot._Session
                engine = self.bot._engine

                session.close_all()
                engine.dispose()
            except:
                logger.exception('Failed to shut db down gracefully')
            logger.info('Closed db connection')

        except Exception:
            logger.exception('Bot shutdown error')

        finally:
            # We have systemctl set up in a way that different exit codes
            # have different effects on restarting behavior
            exit(exit_code)

    @command(owner_only=True)
    async def notice_me(self, ctx):
        guild = ctx.message.guild
        if guild.id == 217677285442977792:
            try:
                await self.bot.request_offline_members(guild)
            except InvalidArgument:
                pass
            for member in list(guild.members):
                await self.bot._wants_to_be_noticed(member, guild)

    @command(owner_only=True)
    async def reload_dbutil(self, ctx):
        reload(import_module('bot.dbutil'))
        from bot import dbutil
        self.bot._dbutil = dbutil.DatabaseUtils(self.bot)
        await ctx.send(':ok_hand:')

    @command(owner_only=True)
    async def reload_config(self, ctx):
        try:
            config = Config()
        except:
            logger.exception('Failed to reload config')
            await ctx.send('Failed to reload config')
            return

        self.bot.config = config
        await ctx.send(':ok_hand:')

    @command(owner_only=True)
    async def cache_guilds(self):
        for guild in self.bot.guilds:
            sql = 'SELECT * FROM `guilds` WHERE guild=%s' % guild.id
            row = await self.bot.dbutil.execute(sql).first()
            if not row:
                sql = 'INSERT INTO `guilds` (`guild`, `prefix`) ' \
                      'VALUES (%s, "%s")' % (guild.id, self.bot.command_prefix)
                try:
                    await self.bot.dbutil.execute(sql, commit=True)
                except SQLAlchemyError:
                    logger.exception('Failed to cache guild')

                d = {'prefix': self.bot.command_prefix}
            else:
                d = {**row}
                del d['guild']

            self.bot.guild_cache.update_guild(guild.id, **d)

    @command(owner_only=True)
    async def reload_module(self, ctx, module_name):
        try:
            reload(import_module(module_name))
        except Exception as e:
            return await ctx.send('Failed to reload module %s because of %s' % (module_name, e.__name__))
        await ctx.send('Reloaded module %s' % module_name)

    @command(owner_only=True)
    async def runas(self, ctx, user: discord.User=None):
        self.bot._runas = user
        await ctx.send(f'Now running as {user}')

    @command(owner_only=True, ignore_extra=True)
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

            messages = split_string(await self.reload_multiple(files), list_join='\n', splitter='\n')
            for msg in messages:
                await ctx.send(msg)

    @command(owner_only=True)
    async def add_sfx(self, ctx, file=None, name=None):
        client = self.bot.aiohttp_client
        if file and name:
            url = file
        else:
            if not ctx.message.attachments:
                return await ctx.send('No files found')

            if not file:
                return await ctx.send('No filename specified')

            url = ctx.message.attachments[0].url
            name = file

        p = os.path.join(SFX_FOLDER, name)
        if os.path.exists(p):
            return await ctx.send(f'File {name} already exists')

        try:
            async with client.get(url) as r:
                data = BytesIO()
                chunk = 4096
                async for d in r.content.iter_chunked(chunk):
                    data.write(d)
            data.seek(0)

        except aiohttp.ClientError:
            logger.exception('Could not download image %s' % url)
            await ctx.send('Failed to download %s' % url)
        else:
            def write():
                with open(p, 'wb') as f:
                    f.write(data.getvalue())

            if os.path.exists(p):
                return await ctx.send(f'File {name} already exists')

            await self.bot.loop.run_in_executor(self.bot.threadpool, write)
            await ctx.send(f'Added sfx {name}')

    @command(owner_only=True)
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
        except SQLAlchemyError:
            logger.exception(f'Failed to botban user {name}{user_id}')
            return await ctx.send(f'Failed to ban user {name}`{user_id}`')

        await ctx.send(f'Banned {name}`{user_id}` from using this bot')

    @command(owner_only=True)
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
        except SQLAlchemyError:
            logger.exception(f'Failed to remove botban of user {name}{user_id}')
            return await ctx.send(f'Failed to remove botban of user {name}`{user_id}`')

        await ctx.send(f'Removed the botban of {name}`{user_id}`')

    @command(owner_only=True)
    async def leave_guild(self, ctx, guild_id: int):
        g = self.bot.get_guild(guild_id)
        if not g:
            return await ctx.send(f'Guild {guild_id} not found')

        await g.leave()
        await ctx.send(f'Left guild {g.name} `{g.id}`')

    @command(owner_only=True)
    async def blacklist_guild(self, ctx, guild_id: int, *, reason):
        try:
            await self.bot.dbutil.blacklist_guild(guild_id, reason)
        except SQLAlchemyError:
            logger.exception('Failed to blacklist guild')
            return await ctx.send('Failed to blacklist guild\nException has been logged')

        guild = self.bot.get_guild(guild_id)
        if guild:
            await guild.leave()

        s = f'{guild} `{guild_id}`' if guild else guild_id
        await ctx.send(f'Blacklisted guild {s}')

    @command(owner_only=True)
    async def unblacklist_guild(self, ctx, guild_id: int):
        try:
            await self.bot.dbutil.unblacklist_guild(guild_id)
        except SQLAlchemyError:
            logger.exception('Failed to unblacklist guild')
            return await ctx.send('Failed to unblacklist guild\nException has been logged')

        guild = self.bot.get_guild(guild_id)
        s = f'{guild} `{guild_id}`' if guild else guild_id
        await ctx.send(f'Unblacklisted guild {s}')

    @command(owner_only=True, ignore_extra=True)
    async def restart_db(self, ctx):
        def reconnect():
            t = time.perf_counter()
            session = self.bot._Session
            engine = self.bot._engine

            session.close_all()
            engine.dispose()

            self.bot._setup_db()

            del session
            del engine
            return (time.perf_counter()-t)*1000

        t = await self.bot.loop.run_in_executor(self.bot.threadpool, reconnect)

        await ctx.send(f'Reconnected to db in {t:.0f}ms')

    def remove_call(self, _, msg_id):
        self.bot.call_laters.pop(msg_id, None)

    @command(owner_only=True)
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

    @command(owner_only=True)
    async def add_todo(self, ctx, priority: int=0, *, todo):
        try:
            rowid = await self.bot.dbutil.add_todo(todo, priority=priority)
        except SQLAlchemyError:
            logger.exception('Failed to add todo')
            return await ctx.send('Failed to add to todo')

        await ctx.send(f'Added todo with priority {priority} and id {rowid}')

    @command(owner_only=True, name='todo')
    async def list_todo(self, ctx, limit: int=3):
        try:
            rows = (await self.bot.dbutil.get_todo(limit)).fetchall()
        except SQLAlchemyError:
            logger.exception('Failed to get todo')
            return await ctx.send('Failed to get todo')

        if not rows:
            return await ctx.send('Nothing to do')

        s = ''
        for row in rows:
            s += f'{row["id"]} {row["time"]} `{row["priority"]}` {row["todo"]}\n\n'

        if len(rows) > 2000:
            return await ctx.send('Too long todo')
        await ctx.send(s)

    @command(owner_only=True)
    async def complete_todo(self, ctx, id: int):
        sql = 'UPDATE `todo` SET completed_at=CURRENT_TIMESTAMP, completed=TRUE WHERE id=%s AND completed=FALSE' % id

        res = await self.bot.dbutil.execute(sql)
        await ctx.send(f'{res.rowcount} rows updated')

    @command(owner_only=True)
    async def reset_cooldown(self, ctx, command):
        cmd = self.bot.all_commands.get(command, None)
        if not cmd:
            return await ctx.send(f'Command {command} not found')

        cmd.reset_cooldown(ctx)
        await ctx.send(f'Cooldown of {cmd.name} reset')

    @command(owner_only=True)
    async def send_message(self, ctx, channel: discord.TextChannel, *, message):
        try:
            await channel.send(message)
        except discord.HTTPException as e:
            await ctx.send(f'Failed to send message\n```py\n{e}\n```')
        except:
            await ctx.send('Failed to send message')

    @command(owner_only=True, aliases=['add_changelog'])
    async def add_changes(self, ctx, *, changes):
        try:
            rowid = await self.bot.dbutil.add_changes(changes)
        except SQLAlchemyError:
            logger.exception('Failed to add changes')
            return await ctx.send('Failed to add to todo')

        await ctx.send(f'Added changes with id {rowid}')


def setup(bot):
    bot.add_cog(BotAdmin(bot))
