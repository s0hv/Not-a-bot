"""
MIT License

Copyright (c) 2017 s0hvaperuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import asyncio
import inspect
import itertools
import logging
import sys
import traceback

import discord
from aiohttp import ClientSession
from discord import state
from discord.ext import commands
from discord.ext.commands import CommandNotFound, bot_has_permissions
from discord.ext.commands.bot import _mention_pattern, _mentions_transforms
from discord.ext.commands.errors import CommandError
from discord.ext.commands.formatter import HelpFormatter, Paginator
from discord.http import HTTPClient

from bot.cooldowns import Cooldown, CooldownMapping
from bot.formatter import Formatter
from bot.globals import Auth
from utils.utilities import is_owner, check_blacklist, no_dm, seconds2str

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass


from bot import exceptions


log = logging.getLogger('discord')
logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class Context(commands.context.Context):
    __slots__ = ('override_perms', 'skip_check', 'original_user', 'domain',
                 'received_at')

    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.override_perms = attrs.pop('override_perms', None)
        self.original_user = self.author  # Used to determine original user with runas
        # Used when wanting to skip database check like in help command
        self.skip_check = attrs.pop('skip_check', False)
        self.domain = attrs.get('domain', None)
        self.received_at = attrs.get('received_at', None)


class Command(commands.Command):
    def __init__(self, name, callback, **kwargs):
        super(Command, self).__init__(name=name, callback=callback, **kwargs)
        self.level = kwargs.pop('level', 0)
        self.owner_only = kwargs.pop('owner_only', False)
        self.auth = kwargs.pop('auth', Auth.NONE)

        if 'required_perms' in kwargs:
            raise DeprecationWarning('Required perms is deprecated, use "from bot.bot import has_permissions" instead')

        self.checks.insert(0, check_blacklist)

        if self.owner_only:
            terminal.info('registered owner_only command %s' % name)
            self.checks.insert(0, is_owner)

        if 'no_pm' in kwargs or 'no_dm' in kwargs:
            self.checks.insert(0, no_dm)

    def undo_use(self, ctx):
        """Undoes one use of command"""
        if self._buckets.valid:
            bucket = self._buckets.get_bucket(ctx.message)
            bucket.undo_one()

    async def can_run(self, ctx):
        original = ctx.command
        ctx.command = self

        try:
            if not (await ctx.bot.can_run(ctx)):
                raise commands.errors.CheckFailure('The global check functions for command {0.qualified_name} failed.'.format(self))

            cog = self.instance
            if cog is not None:
                try:
                    local_check = getattr(cog, '_{0.__class__.__name__}__local_check'.format(cog))
                except AttributeError:
                    pass
                else:
                    ret = await discord.utils.maybe_coroutine(local_check, ctx)
                    if not ret:
                        return False

            predicates = self.checks
            if not predicates:
                # since we have no checks, then we just return True.
                return True

            return ctx.override_perms or await discord.utils.async_all(predicate(ctx) for predicate in predicates)

        finally:
            ctx.command = original


class Group(Command, commands.Group):
    def __init__(self, **attrs):
        Command.__init__(self, **attrs)
        self.invoke_without_command = attrs.pop('invoke_without_command', False)

    def group(self, *args, **kwargs):
        def decorator(func):
            result = group(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    def command(self, *args, **kwargs):
        def decorator(func):
            if 'owner_only' not in kwargs:
                kwargs['owner_only'] = self.owner_only

            result = command(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator


class ConnectionState(state.ConnectionState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def parse_message_delete_bulk(self, data):
        message_ids = set(data.get('ids', []))
        to_be_deleted = []
        for msg in self._messages:
            if msg.id in message_ids:
                to_be_deleted.append(msg)
                message_ids.remove(msg.id)

        for msg in to_be_deleted:
            self._messages.remove(msg)

        if to_be_deleted:
            self.dispatch('bulk_message_delete', to_be_deleted)
        if message_ids:
            self.dispatch('raw_bulk_message_delete', message_ids)


class Client(discord.Client):
    def __init__(self, loop=None, **options):
        self.ws = None
        self._exit_code = 0
        self.loop = asyncio.get_event_loop() if loop is None else loop
        self._listeners = {}
        self.shard_id = options.get('shard_id')
        self.shard_count = options.get('shard_count')

        connector = options.pop('connector', None)
        proxy = options.pop('proxy', None)
        proxy_auth = options.pop('proxy_auth', None)
        self.http = HTTPClient(connector, proxy=proxy, proxy_auth=proxy_auth, loop=self.loop)

        self._handlers = {
            'ready': self._handle_ready
        }

        self._connection = ConnectionState(dispatch=self.dispatch, chunker=self._chunker, handlers=self._handlers,
                                           syncer=self._syncer, http=self.http, loop=self.loop, **options)

        self._connection.shard_count = self.shard_count
        self._closed = asyncio.Event(loop=self.loop)
        self._ready = asyncio.Event(loop=self.loop)
        self._connection._get_websocket = lambda g: self.ws

        if discord.VoiceClient.warn_nacl:
            discord.VoiceClient.warn_nacl = False
            log.warning("PyNaCl is not installed, voice will NOT be supported")


class Bot(commands.Bot, Client):
    def __init__(self, prefix, config, aiohttp=None, **options):
        if 'formatter' not in options:
            options['formatter'] = Formatter(width=150)

        super().__init__(prefix, owner_id=config.owner, **options)
        self._runas = None
        self.remove_command('help')

        @self.group(invoke_without_command=True)
        @bot_has_permissions(embed_links=True)
        @cooldown(1, 10, commands.BucketType.guild)
        async def help(ctx, *commands_: str):
            """Shows all commands you can use on this server.
            Use {prefix}{name} all to see all commands"""
            await self._help(ctx, *commands_)

        @help.command(name='all')
        @bot_has_permissions(embed_links=True)
        @cooldown(1, 10, commands.BucketType.guild)
        async def all_(ctx, *commands_: str):
            """Shows all available commands even if you don't have the correct
            permissions to use the commands. Bot owner only commands are still hidden tho"""
            await self._help(ctx, *commands_, type=Formatter.Generic)

        log.debug('Using loop {}'.format(self.loop))
        if aiohttp is None:
            aiohttp = ClientSession(loop=self.loop)

        self.aiohttp_client = aiohttp
        self.config = config
        self.voice_clients_ = {}
        self._error_cdm = CooldownMapping(commands.Cooldown(2, 5, commands.BucketType.guild))

    @property
    def runas(self):
        return self._runas

    def _check_error_cd(self, message):
        if self._error_cdm.valid:
            bucket = self._error_cdm.get_bucket(message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                return False

        return True

    async def on_command_error(self, context, exception):
        """|coro|

        The default command error handler provided by the bot.

        By default this prints to ``sys.stderr`` however it could be
        overridden to have a different implementation.

        This only fires if you do not specify any listeners for command error.
        """
        if self.extra_events.get('on_command_error', None):
            return
        if hasattr(context.command, "on_error"):
            return

        if hasattr(exception, 'original'):
            exception = exception.original

        if isinstance(exception, commands.errors.CommandNotFound):
            return

        if isinstance(exception, exceptions.SilentException):
            return

        if isinstance(exception, exceptions.PermException):
            return

        if isinstance(exception, discord.Forbidden):
            return

        if isinstance(exception, exceptions.NotOwner):
            return

        channel = context.channel

        if isinstance(exception, commands.errors.BotMissingPermissions) or isinstance(exception, commands.errors.MissingPermissions):
            if self._check_error_cd(context.message):
                try:
                    return await channel.send(str(exception))
                except discord.Forbidden:
                    pass
            return

        if isinstance(exception, commands.errors.CheckFailure):
            return

        error_msg = None
        if isinstance(exception, commands.errors.CommandOnCooldown):
            error_msg = 'Command on cooldown. Try again in {}'.format(seconds2str(exception.retry_after, False))

        if isinstance(exception, commands.errors.BadArgument) or isinstance(exception, commands.errors.MissingRequiredArgument) or isinstance(exception, commands.BadUnionArgument):
            error_msg = str(exception)

        if isinstance(exception, exceptions.BotException):
            error_msg = str(exception)

        if error_msg:
            if self._check_error_cd(context.message):
                try:
                    await channel.send(error_msg, delete_after=300)
                except discord.Forbidden:
                    pass
            return

        terminal.warning('Ignoring exception in command {}'.format(context.command))
        traceback.print_exception(type(exception), exception,
                                  exception.__traceback__, file=sys.stderr)

    @staticmethod
    def get_role_members(role, guild):
        members = []
        for member in guild.members:
            if role in member.roles:
                members.append(member)

        return members

    async def _help(self, ctx, *commands, type=Formatter.ExtendedFilter):
        """Shows this message."""
        author = ctx.author
        if isinstance(ctx.author, discord.User):
            type = Formatter.Generic

        bot = ctx.bot
        destination = ctx.message.channel
        is_owner = author.id == self.owner_id

        def repl(obj):
            return _mentions_transforms.get(obj.group(0), '')

        # help by itself just lists our own commands.
        if len(commands) == 0:
            pages = await self.formatter.format_help_for(ctx, self, is_owner=is_owner, type=type)
        elif len(commands) == 1:
            # try to see if it is a cog name
            name = _mention_pattern.sub(repl, commands[0])
            command = None
            if name in bot.cogs:
                command = bot.cogs[name]
            else:
                command = bot.all_commands.get(name)
                if command is None:
                    await destination.send(bot.command_not_found.format(name))
                    return

            pages = await self.formatter.format_help_for(ctx, command, is_owner=is_owner, type=type)
        else:
            name = _mention_pattern.sub(repl, commands[0])
            command = bot.all_commands.get(name)
            if command is None:
                await destination.send(bot.command_not_found.format(name))
                return

            for key in commands[1:]:
                try:
                    key = _mention_pattern.sub(repl, key)
                    command = command.all_commands.get(key)
                    if command is None:
                        await destination.send(bot.command_not_found.format(key))
                        return
                except AttributeError:
                    await destination.send(bot.command_has_no_subcommands.format(command, key))
                    return

            pages = await self.formatter.format_help_for(ctx, command, is_owner=is_owner, type=type)

        for page in pages:
            await destination.send(embed=page)

    async def invoke(self, ctx):
        """|coro|

        Invokes the command given under the invocation context and
        handles all the internal event dispatch mechanisms.

        Parameters
        -----------
        ctx: :class:`.Context`
            The invocation context to invoke.
        """
        if ctx.command is not None:
            self.dispatch('command', ctx)
            try:
                if (await self.can_run(ctx, call_once=True)):
                    await ctx.command.invoke(ctx)
            except CommandError as e:
                await ctx.command.dispatch_error(ctx, e)
            else:
                self.dispatch('command_completion', ctx)
        elif ctx.invoked_with:
            exc = CommandNotFound('Command "{}" is not found'.format(ctx.invoked_with))
            self.dispatch('command_error', ctx, exc)

    async def get_context(self, message, *, cls=Context):
        ctx = await super().get_context(message, cls=cls)
        if self.runas is not None and message.author.id == self.owner_id:
            if ctx.guild:
                member = ctx.guild.get_member(self.runas.id)
                if not member:
                    return ctx
            else:
                member = self.runas

            ctx.author = member
            ctx.message.author = member

        return ctx

    async def process_commands(self, message, local_time=None):
        ctx = await self.get_context(message, cls=Context)
        ctx.received_at = local_time
        await self.invoke(ctx)

    def command(self, *args, **kwargs):
        """A shortcut decorator that invokes :func:`command` and adds it to
        the internal command list via :meth:`add_command`.
        """
        def decorator(func):
            result = command(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    def group(self, *args, **kwargs):
        def decorator(func):
            result = group(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    def handle_reaction_changed(self, reaction, user):
        removed = []
        event = 'reaction_changed'
        listeners = self._listeners.get(event)
        if not listeners:
            return
        for i, (future, condition) in enumerate(listeners):
            if future.cancelled():
                removed.append(i)
                continue

            try:
                result = condition(reaction, user)
            except Exception as e:
                future.set_exception(e)
                removed.append(i)
            else:
                if result:
                    future.set_result((reaction, user))
                    removed.append(i)

        if len(removed) == len(listeners):
            self._listeners.pop(event)
        else:
            for idx in reversed(removed):
                del listeners[idx]

    async def on_reaction_add(self, reaction, user):
        self.handle_reaction_changed(reaction, user)

    async def on_reaction_remove(self, reaction, user):
        self.handle_reaction_changed(reaction, user)

    @staticmethod
    def get_role(role_id, guild):
        if role_id is None:
            return
        return discord.utils.find(lambda r: r.id == role_id, guild.roles)


def command(*args, **attrs):
    if 'cls' not in attrs:
        attrs['cls'] = Command
    return commands.command(*args, **attrs)


def group(name=None, **attrs):
    """Uses custom Group class"""
    if 'cls' not in attrs:
        attrs['cls'] = Group
    return commands.command(name=name, **attrs)


def cooldown(rate, per, type=commands.BucketType.default):
    """See `commands.cooldown` docs"""

    def decorator(func):
        if isinstance(func, Command):
            func._buckets = CooldownMapping(Cooldown(rate, per, type))
        else:
            func.__commands_cooldown__ = Cooldown(rate, per, type)
        return func
    return decorator


def has_permissions(**perms):
    """
    Same as the default discord.ext.commands.has_permissions
    except this one supports overriding perms
    """
    def predicate(ctx):
        if ctx.override_perms:
            return True

        ch = ctx.channel
        permissions = ch.permissions_for(ctx.author)

        missing = [perm for perm, value in perms.items() if getattr(permissions, perm, None) != value]

        if not missing:
            return True

        raise commands.MissingPermissions(missing)

    return commands.check(predicate)



class FormatterDeprecated(HelpFormatter):
    Generic = 0
    Cog = 1
    Command = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format_help_for(self, context, command_or_bot, is_owner=False):
        self.context = context
        self.command = command_or_bot
        return self.format(is_owner=is_owner)

    def format(self, is_owner=False, generic=False):
        """Handles the actual behaviour involved with formatting.

        To change the behaviour, this method should be overridden.

        Returns
        --------
        list
            A paginated output of the help command.
        """
        if generic:
            self._paginator = Paginator(prefix='```Markdown\n')
        else:
            self._paginator = Paginator(prefix='', suffix='')

        # we need a padding of ~80 or so

        description = self.command.description if not self.is_cog() else inspect.getdoc(self.command)

        if description:
            # <description> portion
            self._paginator.add_line(description, empty=True)

        if isinstance(self.command, Command):
            # <signature portion>
            signature = self.get_command_signature()
            if self.command.owner_only:
                signature = 'This command is owner only\n' + signature

            self._paginator.add_line(signature, empty=True)

            # <long doc> section
            if self.command.help:
                self._paginator.add_line(self.command.help, empty=True)

            # end it here if it's just a regular command
            if not self.has_subcommands():
                self._paginator.close_page()
                return self._paginator.pages

        max_width = self.max_name_size

        def category(tup):
            cog = tup[1].cog_name
            # we insert the zero width space there to give it approximate
            # last place sorting position.
            return cog + ':' if cog is not None else '\u200bNo Category:'

        if self.is_bot():
            data = sorted(self.filter_command_list(), key=category)
            for category, commands in itertools.groupby(data, key=category):
                # there simply is no prettier way of doing this.
                commands = list(commands)
                if len(commands) > 0:
                    self._paginator.add_line('#' + category)

                self._add_subcommands_to_page(max_width, commands, is_owner=is_owner)
        else:
            self._paginator.add_line('Commands:')
            self._add_subcommands_to_page(max_width, self.filter_command_list(), is_owner=is_owner)

        # add the ending note
        self._paginator.add_line()
        ending_note = self.get_ending_note()
        self._paginator.add_line(ending_note)
        return self._paginator.pages

    def _add_subcommands_to_page(self, max_width, commands, is_owner=False):
        for name, command in commands:
            if name in command.aliases:
                # skip aliases
                continue

            if command.owner_only and not is_owner:
                continue

            entry = '  {0:<{width}} {1}'.format(name, command.short_doc, width=max_width)
            shortened = self.shorten(entry)
            self._paginator.add_line(shortened)
