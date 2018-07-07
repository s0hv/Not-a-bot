import asyncio
import logging
import pprint
import shlex
import subprocess
import time
import os
import re
from functools import partial
from importlib import reload, import_module
from io import BytesIO
from bot.globals import SFX_FOLDER
import pprint

import aiohttp
import discord
from discord.errors import HTTPException, InvalidArgument
from discord.ext.commands.core import GroupMixin
from sqlalchemy.exc import SQLAlchemyError, InvalidRequestError
from utils.utilities import y_n_check, basic_check, y_check
from bot.converters import PossibleUser

from bot.bot import command
from bot.globals import Auth
from cogs.cog import Cog
from discord.user import BaseUser

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class BotAdmin(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(name='eval', owner_only=True)
    async def eval_(self, ctx, *, code: str):
        context = globals().copy()
        context.update({'ctx': ctx,
                        'author': ctx.author,
                        'guild': ctx.guild,
                        'message': ctx.message,
                        'channel': ctx.channel,
                        'bot': ctx.bot,
                        'loop': ctx.bot.loop})

        if '\n' in code:
            lines = list(filter(bool, code.split('\n')))
            last = lines[-1]
            if not last.strip().startswith('return'):
                whitespace = len(last) - len(last.strip())
                lines[-1] = ' ' * whitespace + 'return ' + last  # if code doesn't have a return make one

            lines = '\n'.join('    ' + i for i in lines)
            code = f'async def f():\n{lines}\nx = asyncio.run_coroutine_threadsafe(f(), loop).result()'  # Transform the code to a function
            local = {}  # The variables outside of the function f() get stored here

            try:
                await self.bot.loop.run_in_executor(self.bot.threadpool, exec, compile(code, '<eval>', 'exec'), context, local)
                retval = pprint.pformat(local['x'])
            except Exception as e:
                retval = f'{type(e).__name__}: {e}'

        else:
            try:
                retval = await self.bot.loop.run_in_executor(self.bot.threadpool, eval, code, context)
                if asyncio.iscoroutine(retval):
                    retval = await retval

            except Exception as e:
                logger.exception('Failed to eval')
                retval = f'{type(e).__name__}: {e}'

        if not isinstance(retval, str):
            retval = str(retval)

        if len(retval) > 2000:
            await ctx.send(file=discord.File(retval, filename='result.txt'))
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
            retval = 'Exception\n%s' % e

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
        t = time.time()
        try:
            cog_name = 'cogs.%s' % name if not name.startswith('cogs.') else name

            def unload_load():
                self.bot.unload_extension(cog_name)
                self.bot.load_extension(cog_name)

            await self.bot.loop.run_in_executor(self.bot.threadpool, unload_load)
        except Exception as e:
            command_ = self.bot.get_command(name)
            if not command_:
                return await ctx.send('Could not reload %s because of an error\n%s' % (name, e))
            try:
                if isinstance(command_, GroupMixin):
                    commands = self._recursively_remove_all_commands(command_, self.bot)
                    self._recursively_add_all_commands([commands], self.bot)
                else:
                    self.bot.remove_command(command_.name)
                    self.bot.add_command(command_)
            except Exception as e:
                return await ctx.send('Could not reload command(s) %s because of an error\n%s' % (name, e))

        await ctx.send('Reloaded {} in {:.0f}ms'.format(name, (time.time()-t)*1000))

    @command(owner_only=True)
    async def reload_all(self, ctx):
        t = time.time()
        self.bot._unload_cogs()
        errors = await self.bot.loop.run_in_executor(self.bot.threadpool, partial(self.bot._load_cogs, print_err=False))
        t = (time.time() - t) * 1000
        for error in errors:
            await ctx.send(error)
        await ctx.send('Reloaded all default cogs in {:.0f}ms'.format(t))

    @command(owner_only=True)
    async def shutdown(self, ctx):
        try:
            ctx.send('Beep boop')
        except HTTPException:
            pass

        try:
            audio = self.bot.get_cog('Audio')
            if audio:
                await audio.shutdown()

            pending = asyncio.Task.all_tasks(loop=self.bot.loop)
            gathered = asyncio.gather(*pending, loop=self.bot.loop)
            try:
                gathered.cancel()
                self.bot.loop.run_until_complete(gathered)

                # we want to retrieve any exceptions to make sure that
                # they don't nag us about it being un-retrieved.
                gathered.exception()
            except:
                pass

        except Exception:
            terminal.exception('Bot shutdown error')
        finally:
            await self.bot.logout()

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
            return await ctx.send('Failed to reload module %s because of an error\n```%s```' % (module_name, e))
        await ctx.send('Reloaded module %s' % module_name)

    @command(owner_only=True)
    async def runas(self, ctx, user: discord.User=None):
        self.bot._runas = user
        await ctx.send(f'Now running as {user}')

    @command(auth=Auth.ADMIN, ignore_extra=True)
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

            def do_reload():
                messages = []
                for file in files:
                    try:
                        self.bot.unload_extension(file)
                        self.bot.load_extension(file)
                    except Exception as e:
                        messages.append('Failed to load extension {}\n{}: {}'.format(file, type(e).__name__, e))
                    else:
                        messages.append(f'Reloaded {file}')

                return messages

            messages = await self.bot.loop.run_in_executor(self.bot.threadpool, do_reload)
            if messages:
                await ctx.send('\n'.join(messages))

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


def setup(bot):
    bot.add_cog(BotAdmin(bot))
